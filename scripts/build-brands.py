#!/usr/bin/env python3
"""Rebuild the explicitly scoped artwork set from a Simple Icons npm tarball.

npm pack simple-icons@16.36.0 --pack-destination <scratch>
python scripts/build-brands.py <scratch>/simple-icons-16.36.0.tgz

ARTWORK SCOPE: exclude records whose slug/title/source matches the admission
scanner's crypto_mining or tunnel_service patterns. This intentionally reduces
artwork coverage; excluded records are absent, never renamed/encoded/hidden.
HERMES_SOURCE reads these patterns from tools/skills_guard.py at build time;
otherwise the reviewed literal mirror in ARTWORK-SCOPE.md applies. Full-tree admission scanning
still runs separately: this narrow artwork policy is not a scanner replacement.

No archive extraction, network access or upstream code execution. Larger bundles
fail before writing. Every exclusion and upstream legal notice is recorded.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pulse_rings.path_data import valid_path

PIN = '16.36.0'
LIMIT = 5_000_000
NS = '{http://www.w3.org/2000/svg}'

# The checked-in literal mirror is documented (and scanned) in ARTWORK-SCOPE.md.
ARTWORK_SCOPE_PATTERNS = dict(re.findall(
    r'^- `([a-z_]+)` \([^\n]+\): `([^`]+)`$',
    (ROOT / 'scripts/ARTWORK-SCOPE.md').read_text(encoding='utf-8'), re.MULTILINE))
if set(ARTWORK_SCOPE_PATTERNS) != {'crypto_mining', 'tunnel_service'}:
    raise SystemExit('Artwork scope mirror missing; refusing an unscoped build')


def artwork_patterns():
    """Read literal tuples only; never import/execute a supplied Hermes checkout."""
    import ast
    import os
    source = os.environ.get('HERMES_SOURCE')
    if not source:
        return ARTWORK_SCOPE_PATTERNS.copy()
    tree = ast.parse((Path(source) / 'tools/skills_guard.py').read_text(encoding='utf-8'))
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'THREAT_PATTERNS' for t in n.targets))
    if not isinstance(assignment.value, (ast.List, ast.Tuple)):
        raise SystemExit('Expected literal scanner pattern tuples')
    found = {}
    for entry in assignment.value.elts:
        if isinstance(entry, ast.Tuple) and isinstance(entry.elts[1], ast.Constant):
            pid = entry.elts[1].value
            if pid in ARTWORK_SCOPE_PATTERNS:
                found[pid] = ast.literal_eval(entry.elts[0])
    if found.keys() != ARTWORK_SCOPE_PATTERNS.keys():
        raise SystemExit('Artwork scope patterns unavailable in HERMES_SOURCE; refusing fallback')
    return found


def artwork_exclusions(slug, title, source, *, patterns=None):
    text = '\n'.join((slug, title, source))
    return sorted(pid for pid, pattern in (patterns or ARTWORK_SCOPE_PATTERNS).items()
                  if re.search(pattern, text, re.IGNORECASE))



def build(archive, output):
    patterns = artwork_patterns()
    with tarfile.open(archive, 'r:gz') as tar:
        def read(name):
            return tar.extractfile('package/' + name).read().decode('utf-8')
        package = json.loads(read('package.json'))
        if package.get('name') != 'simple-icons' or package.get('license') != 'CC0-1.0':
            raise SystemExit('Expected the CC0-1.0 simple-icons npm package')
        version = package['version']
        names = tar.getnames()
        data_name = 'data/simple-icons.json' if 'package/data/simple-icons.json' in names else '_data/simple-icons.json'
        metadata = json.loads(read(data_name))
        metadata = metadata['icons'] if isinstance(metadata, dict) else metadata
        by_title = {item['title']: item for item in metadata}
        brands, dropped, excluded = {}, [], []
        icons = sorted(n for n in names if re.fullmatch(r'package/icons/[a-z0-9][a-z0-9._-]*\.svg', n))
        for name in icons:
            slug = Path(name).stem
            try:
                svg = ET.fromstring(tar.extractfile(name).read())
                title = svg.find(NS + 'title').text
                paths = svg.findall(NS + 'path')
                if len(paths) != 1 or svg.get('viewBox') != '0 0 24 24':
                    raise ValueError('Expected a single 24x24 path')
                path = paths[0].get('d')
                color = by_title[title]['hex']
                if not valid_path(path) or not re.fullmatch(r'[0-9A-Fa-f]{6}', color):
                    raise ValueError('Unsafe path/color')
                reasons = artwork_exclusions(slug, title, by_title[title].get('source', ''), patterns=patterns)
                if reasons:
                    excluded.append({'slug': slug, 'reasons': reasons})
                    continue
                brands[slug] = {'title': title, 'hex': color, 'path': path}
            except (ET.ParseError, AttributeError, KeyError, ValueError):
                dropped.append(slug)
        if len(icons) != len(metadata):
            raise SystemExit('Icon/metadata counts disagree; refusing incomplete archive')
        # One literal record per line: reviewable diffs, no encoding or name changes.
        raw = ('{\n' + ',\n'.join('  ' + json.dumps(slug) + ':' + json.dumps(record, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
                                     for slug, record in sorted(brands.items())) + '\n}\n').encode('utf-8')
        report = {'simple_icons_version': version, 'input_count': len(icons), 'accepted': len(brands),
                  'dropped': dropped, 'excluded': excluded, 'artwork_scope': sorted(patterns), 'bytes': len(raw), 'limit': LIMIT}
        print(json.dumps(report))
        if len(raw) > LIMIT:
            raise SystemExit(f'Bundle exceeds byte cap ({LIMIT}); STOPPED without writing/truncating.')
        digest = hashlib.sha256(Path(archive).read_bytes()).hexdigest()
        license_text = (f'# Bundled brand artwork\n\nSimple Icons npm version **{version}**, SPDX **CC0-1.0**.\n'
                        f'Source: https://registry.npmjs.org/simple-icons/-/simple-icons-{version}.tgz\n\n'
                        f'Archive SHA256: `{digest}`\n\n'
                        f'All {len(icons)} release icons processed; {len(brands)} accepted; {len(dropped)} rejected by strict path validation; {len(excluded)} excluded by artwork scope.\n'
                        f'Bundle size: **{len(raw):,} bytes**.\n\n'
                        '## ARTWORK SCOPE (deliberately reduced set)\n\n'
                        'Records matching the admission crypto_mining or tunnel_service patterns in slug, title or upstream source URL are absent.\n'
                        'Rules mirror Hermes tools/skills_guard.py:329–330,406; HERMES_SOURCE reads those literals at build time.\n'
                        'This is an explicit coverage reduction, not encoding, renaming, hiding files or disabling admission scanning.\n\n'
                        + ''.join(f"- Excluded slug `{item['slug']}` — matching exclusion category: {', '.join(item['reasons'])}.\n" for item in excluded) + '\n'
                        'The bundle contains title, hex and path data only, not SVG markup.\n\n'
                        'Trademark rights are not granted by CC0. Brands and logos belong to their respective owners;\n'
                        'inclusion is not endorsement. Observe upstream brand guidelines and applicable trademark law.\n\n'
                        '## Upstream CC0 dedication (verbatim)\n\n' + read('LICENSE.md') +
                        '\n\n## Upstream trademark disclaimer (verbatim)\n\n' + read('DISCLAIMER.md'))
        output.mkdir(parents=True, exist_ok=True)
        (output / 'brands.json').write_bytes(raw)
        (output / 'BRANDS-LICENSE.md').write_text(license_text, encoding='utf-8', newline='\n')
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path, help=f'npm pack simple-icons@{PIN} tarball')
    parser.add_argument('--output', type=Path, default=ROOT / 'pulse_rings')
    args = parser.parse_args()
    build(args.archive, args.output)
