"""Read-only Discord QA evidence; aggregate/public data only.

Usage: python scripts/qa-discord-inspect.py PATH_TO_PULSE_DB
No network requests. Database is opened with mode=ro.
"""
import argparse
import json
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('database', type=Path)
args = parser.parse_args()
db = sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True)
db.row_factory = sqlite3.Row
try:
    for row in db.execute('SELECT id,definition,source_state,metadata FROM pulses'):
        definition = json.loads(row['definition'])
        if definition.get('source', {}).get('kind', '').removesuffix('@1') != 'discord.invite':
            continue
        metadata = json.loads(row['metadata'])
        state = json.loads(row['source_state'])
        samples = [json.loads(r[0]) for r in db.execute('SELECT payload FROM samples WHERE pulse_id=? ORDER BY ts', (row['id'],))]
        print(json.dumps({'id': row['id'], 'name': metadata.get('name'), 'online': metadata.get('online'),
                          'members': metadata.get('members'), 'widget_state': state.get('widget_state'),
                          'voice_channels': state.get('widget', {}).get('voice_channels'), 'samples': len(samples),
                          'latest': samples[-1] if samples else None}, ensure_ascii=True))
finally:
    db.close()
