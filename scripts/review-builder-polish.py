"""Crop only the harness frame and make labelled product review matrices."""
import json
from pathlib import Path
import sys
from PIL import Image, ImageDraw

root = Path(sys.argv[1])
stages = ('source', 'source-selected', 'design', 'design-expanded', 'review', 'approval', 'approval-decisions')
widths = (320, 480, 670, 1280)
manifest = []
for stage in stages:
    sheet = Image.new('RGB', (4 * 324, 2 * 804), '#888888')
    draw = ImageDraw.Draw(sheet)
    for row, theme in enumerate(('light', 'dark')):
        for col, width in enumerate(widths):
            name = f'{stage}-{width}-{theme}.png'
            with Image.open(root / name) as source:
                assert source.width == width + 2, name
                image = source.convert('RGB').crop((1, 1, source.width - 1, source.height - 1))
                (root / 'product').mkdir(exist_ok=True)
                image.save(root / 'product' / name)
                manifest.append({'file': 'product/' + name, 'width': image.width, 'height': image.height})
                image.thumbnail((320, 770))
                x, y = col * 324 + 2, row * 804 + 24
                sheet.paste(image, (x, y))
                draw.text((x, y - 20), f'{stage} | {width} | {theme}', fill='white')
    sheet.save(root / f'review-sheet-{stage}.png')
assert len(manifest) == len(stages) * len(widths) * 2
(root / 'screenshot-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(json.dumps({'verified_screenshots': len(manifest), 'review_sheets': len(stages)}))
