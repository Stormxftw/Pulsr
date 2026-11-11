"""Namespace-scoped routes; plain def handlers run in FastAPI's threadpool."""
import importlib.util
import json
from io import StringIO
from contextlib import closing
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

# Dashboard loads this file independently of the agent package. Load only our
# adjacent source, never mutate Hermes modules or rely on sys.path changes.
_spec = importlib.util.spec_from_file_location('pulse_rings_core', Path(__file__).with_name('pulse.py'))
assert _spec is not None and _spec.loader is not None
_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)
router = APIRouter()


def get_pulse():
    pulse = _core.Pulse()
    _core.ensure_collection(pulse)
    return pulse


class DraftBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    definition: dict[str, Any] | str
    replaces: str | None = None
    note: str | None = Field(default=None, max_length=1000)


@router.get('/custom.css')
def custom_css(format: str | None = None, pulse=Depends(get_pulse)):
    """Optional plugin-local CSS; never follow links or read unbounded files."""
    import os
    import stat
    target = pulse.store.root / 'custom.css'
    try:
        before = target.lstat()
        if not stat.S_ISREG(before.st_mode) or target.is_symlink() or before.st_size > 65536:
            raise OSError('Not a bounded regular file')
        # O_NOFOLLOW on platforms that support it; compare file identity as well
        # for platforms (Windows) without O_NOFOLLOW and concurrent replacement.
        fd = os.open(target, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0))
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise OSError('File changed')
            data = stream.read(65537)
        if len(data) > 65536 or target.is_symlink():
            raise OSError('File changed or oversized')
        text = data.decode('utf-8')
    except (OSError, UnicodeError):
        raise HTTPException(404, 'Custom CSS not found') from None
    return Response(json.dumps(text) if format == 'json' else text,
                    media_type='application/json' if format == 'json' else 'text/css', headers={
        'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
    })


def builder_module(pulse, name='builder'):
    # Same package instance as the owning Engine: preserves profile MCP bindings.
    return importlib.import_module(pulse.__class__.__module__.rsplit('.', 1)[0] + '.' + name)


# === Groups & arrangement ===
class ArrangementBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    layout: dict[str, Any]
    revision: str = Field(min_length=64, max_length=64, pattern=r'^[a-f0-9]{64}$')


def arrangement_result(pulse, response, body=None):
    module = builder_module(pulse, 'arrangement')
    response.headers['Cache-Control'] = 'no-store'
    try:
        ids, enabled = module.inventory(pulse)
        if body is None:
            return module.read(pulse.store, ids, show_sessions=enabled)
        return module.write(pulse.store, body.layout, body.revision, ids, show_sessions=enabled)
    except module.StaleLayout as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400 if body else 409, str(exc)) from None
    except OSError:
        raise HTTPException(503, 'Local arrangement could not be saved or read.') from None


def get_arrangement_pulse():
    # UI state never starts the optional collector or calls a source.
    return _core.Pulse()


@router.get('/layout')
def get_layout(response: Response, pulse=Depends(get_arrangement_pulse)):
    return arrangement_result(pulse, response)


@router.put('/layout')
def put_layout(body: ArrangementBody, response: Response, pulse=Depends(get_arrangement_pulse)):
    return arrangement_result(pulse, response, body)
# === End groups & arrangement ===


class LayoutBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    definition: dict[str, Any] | str


class PreviewBody(LayoutBody):
    mode: Literal['sample'] = 'sample'
    state: Literal['measured', 'learning', 'unknown', 'over', 'under', 'stale', 'degraded'] = 'measured'
    seed: StrictInt = Field(default=0, ge=0, le=2147483647)


@router.post('/layout-check')
def layout_check(body: LayoutBody, response: Response, pulse=Depends(get_pulse)):
    response.headers['Cache-Control'] = 'no-store'
    return builder_module(pulse).layout_check(body.definition)


@router.post('/builder/preview')
def builder_preview(body: PreviewBody, response: Response, pulse=Depends(get_pulse)):
    response.headers['Cache-Control'] = 'no-store'
    return builder_module(pulse).sample_preview(body.definition, body.state, body.seed)


def pure_builder_module(name):
    # Import our adjacent package without constructing an Engine, resolving a
    # profile, touching storage, or starting an opted-in background collector.
    package = _core.Pulse.__module__.rsplit('.', 1)[0]
    return importlib.import_module(package + '.' + name)


class FromTemplateBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    template: str = Field(max_length=64)
    values: dict[str, Any] = Field(default_factory=dict)


class BuilderLayoutsBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    feeds: dict[str, Any]
    metrics: list[str] = Field(max_length=8)
    title: str | None = Field(default=None, max_length=60)
    icon: dict[str, Any] | str | None = None


class BuilderLookupBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['city', 'steam']
    q: str = Field(min_length=1, max_length=100)
    confirm: StrictBool


@router.get('/builder/templates')
def builder_templates(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return pure_builder_module('templates').catalog()


@router.post('/builder/from-template')
def builder_from_template(body: FromTemplateBody, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return pure_builder_module('templates').from_template(body.template, body.values)


@router.post('/builder/layouts')
def builder_layouts(body: BuilderLayoutsBody, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return pure_builder_module('layout_presets').layouts(body.feeds, body.metrics, body.title, body.icon)
    except ValueError as exc:
        raise HTTPException(400, {'errors': getattr(exc, 'errors', [{'path': '/', 'message': 'Invalid layout inputs.'}])}) from None


@router.post('/builder/lookup')
def builder_lookup(body: BuilderLookupBody, response: Response, pulse=Depends(get_pulse)):
    response.headers['Cache-Control'] = 'no-store'
    module = builder_module(pulse, 'builder_lookup')
    try:
        return module.lookup(pulse.store.root, body.kind, body.q, body.confirm)
    except module.LookupError as exc:
        raise HTTPException(exc.status, str(exc)) from None


@router.get('/brands')
def brands(q: str = '', pulse=Depends(get_pulse)):
    if len(q) > 100:
        raise HTTPException(422, 'Search is limited to 100 characters.')
    return {'brands': builder_module(pulse).search_brands(q)}


@router.get('/builder/mcp-tools')
def builder_mcp_tools(response: Response, pulse=Depends(get_pulse)):
    response.headers['Cache-Control'] = 'no-store'
    return builder_module(pulse, 'builder_mcp').tool_inventory(pulse.store.root)


class McpTestBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    server: str = Field(max_length=64)
    tool: str = Field(max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)
    confirm: StrictBool


@router.post('/builder/mcp-test-call')
def builder_mcp_test(body: McpTestBody, response: Response, pulse=Depends(get_pulse)):
    if body.confirm is not True:
        raise HTTPException(400, 'Explicit confirmation required for exactly one MCP call.')
    module = builder_module(pulse, 'builder_mcp')
    response.headers['Cache-Control'] = 'no-store'
    try:
        return module.test_call(pulse.store.root, body.server, body.tool, body.args)
    except module.TestCallError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, {'errors': getattr(exc, 'errors', [{'path': '/', 'message': 'Invalid MCP test parameters.'}])}) from None


@router.get('/catalog')
def catalog():
    return _core.catalog()


@router.get('/drafts')
def drafts(pulse=Depends(get_pulse)):
    return {'drafts': pulse.status(poll=False)['drafts']}


@router.post('/drafts')
def propose(body: DraftBody, pulse=Depends(get_pulse)):
    try:
        # Origin is host-derived, never accepted from import content.
        return pulse.create_draft(body.definition, origin={'kind': 'session', 'surface': 'desktop'},
                                  replaces=body.replaces, note=body.note)
    except _core.ValidationError as exc:
        raise HTTPException(400, {'errors': exc.errors}) from None
    except ValueError as exc:
        # Dependency overrides may supply the equivalent public Engine class.
        errors = getattr(exc, 'errors', [{'path': '/', 'message': str(exc)}])
        raise HTTPException(400, {'errors': errors}) from None


@router.get('/drafts/{draft_id}')
def draft(draft_id: str, pulse=Depends(get_pulse)):
    try:
        return pulse.draft(draft_id)
    except KeyError:
        raise HTTPException(404, 'Draft not found') from None
    except (ValueError, TypeError):
        raise HTTPException(409, 'Invalid stored draft') from None


def decision(pulse, draft_id, action):
    try:
        return pulse.decide_draft(draft_id, action)
    except KeyError:
        raise HTTPException(404, 'Draft not found') from None
    except (ValueError, TypeError):
        raise HTTPException(409, 'Draft cannot be decided; refresh or propose again.') from None


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirm: StrictBool


@router.post('/drafts/{draft_id}/approve')
def approve(draft_id: str, body: DecisionBody, pulse=Depends(get_pulse)):
    """Human click, host-authenticated and enable-gated by Hermes's route mount."""
    if body.confirm is not True:
        raise HTTPException(400, 'Explicit confirmation required')
    return decision(pulse, draft_id, 'approve')


@router.post('/drafts/{draft_id}/reject')
def reject(draft_id: str, body: DecisionBody, pulse=Depends(get_pulse)):
    if body.confirm is not True:
        raise HTTPException(400, 'Explicit confirmation required')
    return decision(pulse, draft_id, 'reject')


class CollectionBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    background_collection: StrictBool | None = None
    show_sessions: StrictBool | None = None
    confirm: StrictBool

    @model_validator(mode='after')
    def require_setting(self):
        if not self.model_fields_set.intersection({'background_collection', 'show_sessions'}):
            raise ValueError('At least one setting required')
        if any(getattr(self, key) is None for key in self.model_fields_set if key != 'confirm'):
            raise ValueError('Settings must be strict booleans')
        return self


@router.get('/settings')
def collection_settings(response: Response, pulse=Depends(get_pulse)):
    response.headers['Cache-Control'] = 'no-store'
    return {**builder_module(pulse, 'background').settings(pulse),
            'show_sessions': builder_module(pulse, 'sessions').enabled(pulse)}


@router.put('/settings')
def update_collection_settings(body: CollectionBody, response: Response, pulse=Depends(get_pulse)):
    """Authenticated human click only; not registered as an agent tool."""
    if body.confirm is not True:
        raise HTTPException(400, 'Explicit confirmation required')
    response.headers['Cache-Control'] = 'no-store'
    try:
        if body.show_sessions is not None:
            builder_module(pulse, 'sessions').set_setting(pulse, body.show_sessions)
        if body.background_collection is not None:
            builder_module(pulse, 'background').set_setting(pulse, body.background_collection)
        return collection_settings(response, pulse)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from None


# === Session pulses ===
def get_local_pulse():
    # No ensure_collection here: this route must never start network collection.
    return _core.Pulse()


@router.get('/sessions')
def session_status(response: Response, pulse=Depends(get_local_pulse)):
    response.headers['Cache-Control'] = 'no-store'
    return builder_module(pulse, 'sessions').status(pulse)


@router.get('/status')
def status(poll: bool = True, pulse=Depends(get_pulse)):
    """Refresh at most one due public endpoint, otherwise serve the local cache."""
    return pulse.status(poll=poll)


class PauseBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    paused: StrictBool


@router.get('/icons/{identity}')
def icon(identity: str, response: Response, pulse=Depends(get_pulse)):
    import re
    match = re.fullmatch(r'([0-9]{15,22})-((?:a_)?[a-f0-9]{32})', identity)
    if match is not None:
        data = pulse.icons.data({'id': match[1], 'icon_hash': match[2]})
    elif re.fullmatch(r'sha256-[a-f0-9]{64}', identity):
        data = pulse.icon_resolver.data(identity)
    else:
        raise HTTPException(404, 'Icon not found')
    if data is None:
        raise HTTPException(404, 'Icon not found')
    response.headers['Cache-Control'] = 'private, max-age=31536000, immutable'
    return {'icon_data': data}


@router.get('/pulses/{pulse_id}/definition')
def pulse_definition(pulse_id: str, pulse=Depends(get_pulse)):
    from ruamel.yaml import YAML
    with closing(pulse.store.db()) as db:
        row = db.execute('SELECT definition FROM pulses WHERE id=?', (pulse_id,)).fetchone()
    if row is None:
        raise HTTPException(404, 'Pulse not found')
    output = StringIO()
    yaml = YAML(typ='safe')
    yaml.default_flow_style = False
    yaml.dump(json.loads(row['definition']), output)
    return {'yaml': output.getvalue()}


@router.patch('/pulses/{pulse_id}')
def pause_pulse(pulse_id: str, body: PauseBody, pulse=Depends(get_pulse)):
    """Human UI action only; changing definitions always requires a new draft."""
    if not pulse.store.pause(pulse_id, body.paused, now=pulse.clock()):
        raise HTTPException(404, 'Pulse not found')
    return {'id': pulse_id, 'paused': body.paused}


@router.delete('/pulses/{pulse_id}')
def remove_pulse(pulse_id: str, pulse=Depends(get_pulse)):
    """Unwatch, preserving samples and notes. Host authentication is inherited."""
    if not pulse.store.remove(pulse_id):
        raise HTTPException(404, 'Pulse not found')
    return {'ok': True}


class OpenAppBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirm: StrictBool


@router.post('/pulses/{pulse_id}/open-app')
def open_pulse_app(pulse_id: str, body: OpenAppBody, response: Response, pulse=Depends(get_arrangement_pulse)):
    """Human click only: bring the one curated app a notifications pulse watches forward.

    Not an agent tool. The target comes from the code-owned app table, never from the
    request or from definition text; nothing is polled and nothing is read back.
    """
    if body.confirm is not True:
        raise HTTPException(400, 'Explicit confirmation required')
    response.headers['Cache-Control'] = 'no-store'
    module = builder_module(pulse, 'app_open')
    try:
        return module.open_for_pulse(pulse, pulse_id)
    except module.OpenError as exc:
        raise HTTPException(exc.status, str(exc)) from None


def discord_importer(pulse):
    package = pulse.__class__.__module__.rsplit('.', 1)[0]
    module = importlib.import_module(package + '.migrate')
    return module.DiscordPulseImporter(pulse.store, clock=pulse.clock,
                                      ceiling=pulse.net.ceiling)


class DiscordImportBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    consent: StrictBool
    token: str = Field(pattern=r'^[a-f0-9]{64}$')


@router.get('/migrate/discord-pulse')
def plan_discord_import(pulse=Depends(get_pulse)):
    """Human review; enclosing Hermes mount owns authentication and origin guards."""
    try:
        return discord_importer(pulse).plan()
    except (ValueError, TypeError):
        raise HTTPException(409, 'Draft cannot be decided; refresh or propose again.') from None
    except Exception:
        raise HTTPException(503, 'Discord Pulse import is unavailable.') from None


@router.post('/migrate/discord-pulse')
def apply_discord_import(body: DiscordImportBody, pulse=Depends(get_pulse)):
    if body.consent is not True:
        raise HTTPException(400, 'Explicit human consent is required.')
    try:
        return discord_importer(pulse).apply(consent=True, token=body.token)
    except (ValueError, TypeError):
        raise HTTPException(409, 'Draft cannot be decided; refresh or propose again.') from None
    except Exception:
        raise HTTPException(503, 'Discord Pulse import is unavailable.') from None
