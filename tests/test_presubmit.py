"""Pre-submit greps complement (not replace) the host install scanner."""
import ast
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.parse import urlsplit

from ruamel.yaml import YAML
from pulse_rings.version import VERSION
from pulse_rings.net import FIXED_HOSTS

ROOT = Path(__file__).resolve().parents[1]


def test_submission_metadata_version_and_capabilities():
    yaml = YAML(typ='safe')
    manifest = yaml.load((ROOT / 'plugin.yaml').read_text())
    entry = yaml.load((ROOT / 'submission/catalog-entry.yaml').read_text())
    assert entry['name'] == manifest['name'] == 'pulse-rings'
    assert entry['repo'] == 'https://github.com/Stormxftw/Pulsr'
    assert entry['version'] == manifest['version'] == VERSION
    assert entry['requires_hermes'] == manifest['requires_hermes'] == '>=0.22.7'
    assert entry['capabilities'] == {k: manifest[k] for k in
        ('provides_tools', 'provides_hooks', 'provides_middleware', 'requires_env')}
    # Actual register(ctx) introspection is test_authoring's companion gate.
    # Short enough to read on a catalog card; every host the plugin can contact
    # without a per-pulse approval is still named: the fixed hosts and the two
    # builder lookup hosts.
    assert len(entry['description']) <= 800
    assert all(host in entry['description'] for host in
               (*FIXED_HOSTS, 'geocoding-api.open-meteo.com', 'store.steampowered.com'))
    assert tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version'] == VERSION
    assert json.loads((ROOT / 'dashboard/manifest.json').read_text())['version'] == VERSION
    assert f'const VERSION = "{VERSION}";' in (ROOT / 'desktop/plugin.js').read_text()
    for name in ('README.md', 'submission/PR-BODY.md', 'submission/CHECKLIST.md'):
        assert VERSION in (ROOT / name).read_text(encoding='utf-8'), name
    # A draft is deliberately not installable; no invented publication SHA.
    assert (re.fullmatch(r'[a-f0-9]{40}', entry['sha']) or
            (entry['sha'] == 'TODO_PUBLISHED_40_HEX_SHA' and
             'Draft only' in (ROOT / 'submission/catalog-entry.yaml').read_text()))


def test_every_runtime_public_host_is_disclosed_in_readme_and_pr():
    # AST strings include literal/f-string hosts, even when not in FIXED_HOSTS.
    hosts: set[str] = set(FIXED_HOSTS)
    # Explicit non-host dotted strings: filenames, kind/event/metric identifiers.
    # Any newly added bare public domain (regardless of TLD) requires disclosure.
    non_host_names = {'curated.json', 'brands.json', 'discord.invite', 'github.repo', 'github.search',
                      'hermes.activity', 'mcp.tool', 'draft.created', 'draft.updated', 'draft.decided',
                      'sample.baselines.recent', 'hermes.waiting', 'feed.metric',
                      'weather.temp', 'air.aqi', 'desktop.notifications', 'wpndatabase.db', 'web.feed',
                      # Windows app IDs (AUMIDs) in desktop_apps.py, matched locally, never contacted.
                      'com.squirrel.slack.slack', 'com.nousresearch.hermes'}
    denied_or_metadata = {'metadata.google.internal', 'metadata.google', 'metadata.goog',
                          'instance-data.ec2.internal', 'json-schema.org',
                          # JSON Feed's version identifier, matched as text, never contacted.
                          'jsonfeed.org'}
    for path in (ROOT / 'pulse_rings').rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            # Ignore prose/docstrings/regexes; collect exact domains and URL origins.
            text = node.value
            if text not in non_host_names and re.fullmatch(r'(?:[a-z0-9-]+\.)+[a-z]{2,}', text):
                hosts.add(text)
            for url in re.findall(r'https://[a-z0-9.-]+', text):
                hosts.add(urlsplit(url).hostname)
    hosts -= denied_or_metadata
    for name in ('README.md', 'submission/PR-BODY.md'):
        text = (ROOT / name).read_text(encoding='utf-8')
        assert not (hosts - {h for h in hosts if h in text}), (name, hosts)
        assert 'user-approved HTTPS hosts' in text
        assert 'avatars.githubusercontent.com' in text and 'persisted' in text
        assert 'GitHub owner/org avatars' in text and '256 KiB' in text


def test_final_tree_documentation_facts_do_not_drift():
    yaml = YAML(typ='safe')
    manifest = yaml.load((ROOT / 'plugin.yaml').read_text())
    tools = manifest['provides_tools']
    brands_path = ROOT / 'pulse_rings/brands.json'
    count = len(json.loads(brands_path.read_text(encoding='utf-8')))
    size = len(brands_path.read_bytes())
    legal = (ROOT / 'pulse_rings/BRANDS-LICENSE.md').read_text(encoding='utf-8')
    version = re.search(r'Simple Icons npm version \*\*([^*]+)', legal)[1]
    # The catalog entry's description is one short paragraph (catalog schema: "One-line
    # description"); the detailed facts are disclosed in the README and PR body (rule 13).
    for name in ('README.md', 'submission/PR-BODY.md',
                 'submission/CHECKLIST.md', 'desktop/ICONS-CONTRACT.md', 'spec/INTERFACE.md',
                 'skills/authoring/SKILL.md'):
        text = (ROOT / name).read_text(encoding='utf-8')
        assert f'{count:,}' in text and version in text and f'{size:,}' in text, name
    for name in ('README.md', 'submission/PR-BODY.md',
                 'submission/CHECKLIST.md', 'spec/INTERFACE.md', 'skills/authoring/SKILL.md'):
        text = (ROOT / name).read_text(encoding='utf-8')
        assert len(tools) == 4
        assert all(tool in text for tool in tools), name
        assert 'up to 6' in text and 'per eligible fixed-host feed' in text, name
        assert 'Test call' in text and '64 KiB' in text and '10-second' in text, name
        assert 'zero pre-approval MCP calls' not in text, name
        assert 'two total**' not in text and 'exactly 3 tools' not in text, name


def test_renderer_sdk_only_security_greps():
    js = (ROOT / 'desktop/plugin.js').read_text(encoding='utf-8')
    assert not re.search(r'\beval\s*\(|new\s+Function\b|import\s*\(|<script|innerHTML|outerHTML|MutationObserver|\.prototype\s*[.\[]', js)
    assert not re.search(r'https?://|data-slot|data-tour|data-sidebar|data-testid|data-tree-|document\.querySelector|window\.hermesDesktop', js)
    imports = re.findall(r'\bfrom\s+[\'"]([^\'"]+)', js)
    assert imports and set(imports) <= {'react', 'react/jsx-runtime', '@hermes/plugin-sdk'}
    assert all(selector.startswith('.pr-') for selector in re.findall(r'\.closest\([\'"]([^\'"]+)', js))


def test_no_shipped_bytecode_executables_or_opaque_archives():
    files = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'])
    magic = (b'MZ', b'\x7fELF', b'\x00asm', b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf',
             b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca')
    for relative in set(files.decode().split('\0')) - {''}:
        path = ROOT / relative
        assert path.suffix.lower() not in {'.pyc', '.pyo', '.zip', '.gz', '.tar', '.7z', '.exe', '.dll', '.so', '.wasm'}, relative
        with path.open('rb') as stream:
            header = stream.read(8)
        assert not any(header.startswith(m) for m in magic), relative
        assert not (len(header) >= 4 and header[2:4] == b'\r\n' and path.suffix != '.py'), relative


def test_runtime_has_no_self_updater_or_credential_file_reads():
    paths = [ROOT / '__init__.py', *(ROOT / 'pulse_rings').rglob('*.py'), ROOT / 'dashboard/plugin_api.py']
    for path in paths:
        text = path.read_text(encoding='utf-8')
        assert not re.search(r'(?<!\.)\b(?:eval|exec|compile|__import__)\s*\(|\b(?:subprocess|urlretrieve)\b|os\.system\s*\(', text), path
        assert not re.search(r'auth\.json|\.env[\'"]|os\.environ\[|getenv\([\'"]PULSE_RINGS_GITHUB_TOKEN', text), path
