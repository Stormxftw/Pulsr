"""Durable per-feed preview caps/leases; shares the legacy draft decision gate."""
import json
import uuid


def claim(store, now, draft_id):
    token = uuid.uuid4().hex
    with store.transaction() as db:
        row = db.execute("""SELECT f.* FROM draft_feeds f JOIN drafts d ON d.id=f.draft_id
            WHERE d.status='pending' AND d.expires_ts>? AND f.preview_allowed=1
            AND f.preview_calls<2 AND f.sample IS NULL AND f.preview_due<=?
            AND (? IS NULL OR d.id=?) ORDER BY f.preview_due,d.created_ts,d.id,f.feed LIMIT 1""",
            (now, now, draft_id, draft_id)).fetchone()
        if row is None:
            return None
        db.execute('UPDATE draft_feeds SET preview_due=?,preview_lease=? WHERE draft_id=? AND feed=?',
                   (now + 90, token, row['draft_id'], row['feed']))
        return row['draft_id'], token, row['feed']


def call(store, draft_id, token, now, feed):
    with store.transaction() as db:
        changed = db.execute("""UPDATE draft_feeds SET preview_calls=preview_calls+1
            WHERE draft_id=? AND feed=? AND preview_lease=? AND preview_calls<2
            AND EXISTS(SELECT 1 FROM drafts d WHERE d.id=draft_id AND d.status='pending' AND d.expires_ts>?)""",
            (draft_id, feed, token, now)).rowcount
        if not changed:
            raise ValueError('Draft preview no longer available')
        db.execute('UPDATE drafts SET preview_calls=preview_calls+1 WHERE id=?', (draft_id,))


def records(store, draft_id, *, db=None):
    with store.read(db) as db:
        return {r['feed']: dict(r) for r in db.execute('SELECT * FROM draft_feeds WHERE draft_id=?', (draft_id,))}


def finish(store, draft_id, token, feed, *, state, sample, preview, due, error):
    with store.transaction() as db:
        changed = db.execute("""UPDATE draft_feeds SET source_state=COALESCE(?,source_state),sample=COALESCE(?,sample),
            metadata=COALESCE(?,metadata),preview_due=?,preview_error=?,preview_lease=NULL
            WHERE draft_id=? AND feed=? AND preview_lease=? AND EXISTS
            (SELECT 1 FROM drafts d WHERE d.id=draft_id AND d.status='pending')""",
            (json.dumps(state) if state is not None else None,
             json.dumps(sample) if sample is not None else None,
             json.dumps(sample.get('metadata', {})) if sample is not None else None,
             due, error, draft_id, feed, token)).rowcount
        if changed:
            rows = records(store, draft_id, db=db)
            observations = {name: json.loads(r['sample']) for name, r in rows.items() if r['sample']}
            states = {name: json.loads(r['source_state']) for name, r in rows.items()}
            db.execute('UPDATE drafts SET sample=?,source_state=?,preview=COALESCE(?,preview) WHERE id=?',
                       (json.dumps(observations) if observations else None, json.dumps(states),
                        json.dumps(preview) if preview is not None else None, draft_id))
        return bool(changed)


def tick(engine, claimed):
    """Exactly one claimed feed/dispatch, with the same per-kind preview policy."""
    import copy
    from .previews import PreviewNet, eligible
    from .feed_runtime import adapter_definition
    from .sources.base import SourceError, Deferred
    from .sources.discord import DiscordSource
    from .events import emit
    id, token, feed = claimed
    now = engine.clock()
    try:
        draft = engine.store.draft(id, now)
        original = draft['definition']
        definition = adapter_definition(original, feed)
        if draft['origin'].get('kind') != 'session' or not eligible(engine, definition):
            engine.store.finish_preview(id, token, due=now + 7 * 86400, feed=feed)
            return True
        adapter = engine.adapter(definition)
        if isinstance(adapter, DiscordSource):
            adapter = copy.copy(adapter)
            adapter.icons = None
        rows = records(engine.store, id)
        state = json.loads(rows[feed]['source_state'])
        previous = (draft['sample'] or {}).get(feed)
        net = PreviewNet(engine, id, token, draft['budget']['hosts'], feed=feed)
        result = adapter.poll(definition, previous, state, now=now, net=net)
        observations = dict(draft['sample'] or {})
        if result.sample is not None:
            observations[feed] = result.sample
        rows[feed].update(source_state=json.dumps(result.state), preview_error=None)
        if result.sample is not None:
            rows[feed]['metadata'] = json.dumps(result.metadata or result.sample.get('metadata', {}))
        preview = engine.preview(original, observations, draft['budget'], records=rows) if observations else None
        engine.store.finish_preview(id, token, state=result.state, sample=result.sample, preview=preview,
                                    due=max(now + 2, result.next_due or now + 2), feed=feed)
        emit('draft.updated', {'id': id})
    except Deferred as exc:
        engine.store.finish_preview(id, token, due=now + max(2, exc.retry_after), feed=feed)
    except Exception as exc:
        delay = exc.retry_after if isinstance(exc, SourceError) else 600
        engine.store.finish_preview(id, token, due=now + max(2, delay),
                                    error='Preview unavailable; sample after approval.', feed=feed)
    return True
