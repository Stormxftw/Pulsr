"""Low-volume public verification; records raw fixtures, not credentials."""
import datetime
import json
import pathlib
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CODES = ['nousresearch', 'nvidiadeveloper', 'typesafe', '6EbMcWJHdb', 'ollama']
rows = []
for code in CODES:
    url = f'https://discord.com/api/v10/invites/{code}?with_counts=true'
    req = urllib.request.Request(url, headers={'User-Agent': 'DiscordPulse/0.1 (public community counts)'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = json.load(r)
        guild = raw['guild']
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        row = {'code': code, 'name': guild['name'], 'guild_id': guild['id'], 'verified_at': stamp,
               'members': raw.get('approximate_member_count'), 'online': raw.get('approximate_presence_count')}
        folder = ROOT / 'tests' / 'fixtures'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'{code}.json').write_text(json.dumps(raw, indent=2), encoding='utf-8')
        rows.append(row)
        print(json.dumps(row), flush=True)
    except urllib.error.HTTPError as e:
        print(f'{code}: HTTP {e.code}', flush=True)
        if e.code == 429:
            break
    time.sleep(1.5)
(ROOT / 'curated.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
