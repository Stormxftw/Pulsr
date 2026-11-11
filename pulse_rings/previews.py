"""Two dispatches per draft, one per poll, through ordinary durable host gates."""
import copy
from .net import Net
from .kinds import KINDS
from .sources.base import Deferred, SourceError
from .sources.discord import DiscordSource
from .events import emit

FIXED_KINDS = frozenset(('discord.invite', 'github.search', 'github.repo'))


def eligible(engine, definition):
    kind = definition['source']['kind'].split('@')[0]
    adapter = engine.adapter(definition)
    return (kind in FIXED_KINDS and KINDS[kind]['pre_approval_sample'] is True
            and adapter is not None and not getattr(adapter, 'arbitrary_host', False)
            and getattr(adapter, 'pre_approval_sample', True) is not False)


class PreviewNet(Net):
    def __init__(self, engine, draft_id, token, hosts, *, feed=None):
        super().__init__(engine.store, clock=engine.clock, ceiling=engine.net.ceiling)
        self.draft_id, self.token, self.hosts = draft_id, token, hosts
        self.feed = feed
        self.calls = 0

    def call(self, host, callback):
        if host not in self.hosts or host not in ('discord.com', 'api.github.com'):
            raise SourceError('Host is not allowed before approval')
        if self.calls:
            raise Deferred('Next preview operation waits for another tick.', 429, 2)
        def dispatch():
            self.store.preview_call(self.draft_id, self.token, self.clock(), feed=self.feed)
            self.calls += 1
            return callback()
        return super().call(host, dispatch)


def tick(engine, draft_id=None):
    claimed = engine.store.claim_preview(engine.clock(), draft_id)
    if claimed is None:
        return False
    if len(claimed) == 3:
        from .feed_previews import tick as feed_tick
        return feed_tick(engine, claimed)
    id, token = claimed
    now = engine.clock()
    try:
        draft = engine.store.draft(id, now)
        definition = draft['definition']
        if (definition['source']['kind'].split('@')[0] not in FIXED_KINDS
                or draft['origin'].get('kind') != 'session'):
            engine.store.finish_preview(id, token, due=now + 7 * 86400)
            return True
        adapter = engine.adapter(definition)
        kind = definition['source']['kind'].split('@')[0]
        if (adapter is None or KINDS[kind]['pre_approval_sample'] is not True
                or getattr(adapter, 'arbitrary_host', False)
                or getattr(adapter, 'pre_approval_sample', True) is False):
            raise SourceError('Source is not available before approval')
        if isinstance(adapter, DiscordSource):
            # Icons are post-approval only. Never leak an auxiliary request
            # through the adapter's original (non-preview) IconCache net handle.
            adapter = copy.copy(adapter)
            adapter.icons = None
        net = PreviewNet(engine, id, token, draft['budget']['hosts'])
        result = adapter.poll(definition, draft['sample'], draft['source_state'], now=now, net=net)
        preview = engine.preview(definition, result.sample, draft['budget']) if result.sample is not None else None
        engine.store.finish_preview(id, token, state=result.state, sample=result.sample, preview=preview,
                                    due=max(now + 2, result.next_due or now + 2))
        emit('draft.updated', {'id': id})
    except Deferred as exc:
        engine.store.finish_preview(id, token, due=now + max(2, exc.retry_after))
    except Exception as exc:
        delay = exc.retry_after if isinstance(exc, SourceError) else 600
        engine.store.finish_preview(id, token, due=now + max(2, delay), error='Preview unavailable; sample after approval.')
    return True
