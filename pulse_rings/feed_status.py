"""Multi-feed status assembly. All reads reuse the caller's SQLite connection."""
import copy
import json

from .display import compute_display
from .feed_runtime import adapter_definition, hero_ref, icon_definition
from .limits import SPARKLINE_POINTS


def assemble(engine, definition, row, now, *, db=None, samples=None, records=None):
    # Preview passes in-memory persisted draft feed records, never reads live samples.
    from .engine import seconds, value_of, compute_alert
    preview = samples is not None
    records = records if records is not None else engine.store.feed_rows(row['id'], db=db)
    contexts, feed_rows, histories = {}, [], {}
    for name, spec in definition['feeds'].items():
        stored = records.get(name, {})
        allocation = json.loads(stored['budget']) if stored.get('budget') else None
        if allocation is None and not preview:
            raise ValueError('Stored feed budget is missing')
        history = ([samples[name]] if samples.get(name) else []) if preview else engine.store.history(
            row['id'], since=now - 7 * 86400, tail=SPARKLINE_POINTS, feed=name, db=db)
        histories[name] = history
        current = copy.deepcopy(history[-1]) if history else None
        adapter = engine.adapter(adapter_definition(definition, name))
        if current is not None and adapter is not None and hasattr(adapter, 'current'):
            current = adapter.current(current, json.loads(stored.get('source_state', '{}')), now=now)
        backoff = max([stored.get('backoff_until', 0)] + [engine.store.gate('remote:' + h, db=db)
            for h in (allocation or {}).get('hosts', [])]) if not preview else 0
        last_ok = stored.get('last_ok_ts', history[-1]['ts'] if history else None)
        error = stored.get('error') or stored.get('preview_error')
        stale = last_ok is not None and now - last_ok > 2 * seconds(spec['every'])
        state = ('unsupported_version' if adapter is None else 'paused' if row.get('paused') else
                 'backoff' if backoff > now else 'error' if error else 'stale' if stale else
                 'warming' if current is None else 'active')
        if spec['kind'].removesuffix('@1') == 'mcp.tool':
            from .sources.mcp import disclosure
            grant = disclosure(adapter_definition(definition, name), engine.root)
            if not row.get('paused') and (not grant['hermes_allowed'] or
                    json.loads(stored.get('source_state', '{}')).get('needs_mcp_grant')):
                state = 'needs_mcp_grant'
                from .mcp_access import grant_message
                grant['grant_message'] = grant_message(spec['params']['server'])
        else:
            grant = None
        status = {'name': name, 'kind': spec['kind'], 'state': state, 'last_ok_ts': last_ok,
                  'next_due': max(stored.get('next_due', 0), backoff), 'backoff_until': backoff,
                  'error': error, 'budget': allocation}
        if grant is not None:
            status['mcp'] = grant
        feed_rows.append(status)
        failed = bool(error or backoff > now or adapter is None or state == 'needs_mcp_grant')
        if failed:
            # Preserve last-good observations on disk/history, never paint them as
            # a current measured block while this feed is failing.
            current = {'ts': now, 'metrics': {}, 'unknown_reasons': {}}
            if not error:
                status['error'] = (grant['grant_message'] if state == 'needs_mcp_grant' else
                    'Source rate limited' if backoff > now else 'Source kind is not available in this engine.')
        contexts[name] = {'current': current, 'history': history if failed else history[:-1], 'status': status}
    blocks = compute_display(definition, contexts)
    assert blocks is not None  # Explicit feeds always require display at admission.
    ring = next((b['ring'] for b in blocks if b['type'] == 'score'),
                {'score': 0, 'warming': False, 'unknown': True, 'components': [], 'baseline_samples': 0, 'window_seconds': 0})
    item = next((b['items'][0] for b in blocks if b['type'] in ('rings', 'bar', 'bars')), None)
    capsule = ({'label': item['label'] + ' ' + (item['value_text'] or 'unknown'),
                'fill': item['fill'], 'caption': item['caption']} if item else
               {'label': definition['title'], 'fill': None, 'caption': ''})
    failed_count = sum(f['state'] in ('error', 'backoff', 'unsupported_version') for f in feed_rows)
    state = ('paused' if row.get('paused') else 'needs_mcp_grant' if any(f['state'] == 'needs_mcp_grant' for f in feed_rows) else
             'error' if failed_count == len(feed_rows) else
             'degraded' if failed_count else 'stale' if any(f['state'] == 'stale' for f in feed_rows) else
             'warming' if ring['warming'] or any(f['state'] == 'warming' for f in feed_rows) else 'active')
    hero, metric = hero_ref(definition).split('.')
    metadata = json.loads(records.get(hero, {}).get('metadata', '{}'))
    note, note_path = engine._notes(row['id'], metadata) if not preview else (None, None)
    history = histories[hero]
    latest = [f['last_ok_ts'] for f in feed_rows if f['last_ok_ts'] is not None]
    allocation = json.loads(row['budget'])
    from .sources.desktop_notifications import disclosure
    notifying = [spec['params'] for spec in definition['feeds'].values()
                 if spec['kind'].removesuffix('@1') == 'desktop.notifications']
    from .notification_preview import enabled
    enrichment = ({'notifications': disclosure(next((p for p in notifying if enabled(p)), notifying[0]))}
                  if notifying else {})
    if definition['feeds'][hero]['kind'].removesuffix('@1') == 'desktop.notifications' and history and not preview:
        # Notification mode reads the main feed; a failing feed's blanked sample stays unknown.
        from .inbox import summarize
        enrichment['inbox'] = summarize(contexts[hero]['current'], json.loads(records.get(hero, {}).get('source_state') or '{}'))
        if row.get('text') and enrichment['inbox'] is not None:
            # Opt-in message preview of the main feed: for the pane only, never the agent or disk.
            from .notification_preview import items_for
            items = items_for(engine.adapter(adapter_definition(definition, hero)), definition['feeds'][hero]['params'],
                              enrichment['inbox'], now)
            if items is not None:
                enrichment['inbox']['items'] = items
        from .app_open import describe
        opener = describe(engine, definition, json.loads(records.get(hero, {}).get('source_state') or '{}'))
        if opener:
            enrichment['open_app'] = opener
    if definition['feeds'][hero]['kind'].removesuffix('@1') == 'web.feed' and history and not preview:
        from .posts import summarize as posts_summary
        enrichment['posts'] = posts_summary(contexts[hero]['current'],
                                            json.loads(records.get(hero, {}).get('source_state') or '{}'), now=now)
    return {**enrichment, 'id': row['id'], 'title': str(definition['title']), 'kind': definition['feeds'][hero]['kind'],
            'state': state, 'ring': ring, 'capsule': capsule, 'lines': [],
            'display': blocks, 'feeds': feed_rows, 'theme': definition.get('theme'),
            'icon_data': None, 'icon_url': engine.icons.url(metadata) if row.get('include_icons', True) and not preview else None,
            'icon_resolved': engine.icon_resolver.resolve(icon_definition(definition),
                metadata=metadata if row.get('include_icons', True) else {}, budget=allocation,
                approved=not preview and row.get('include_icons', True)),
            'last_ok_ts': max(latest) if latest else None,
            'next_due': min(f['next_due'] for f in feed_rows),
            'backoff_until': max(f['backoff_until'] for f in feed_rows),
            'error': '; '.join(f"{f['name']}: {f['error']}" for f in feed_rows if f['error']) or None,
            'alert': compute_alert(definition, {}, ring, feeds=contexts),
            'history': [{'ts': s['ts'], 'value': value_of(s, metric)} for s in history[-SPARKLINE_POINTS:]],
            'budget': allocation, 'every': definition['feeds'][hero]['every'],
            'link': definition.get('link'), 'icon': definition.get('icon', 'source'), 'note': note, 'note_path': note_path}
