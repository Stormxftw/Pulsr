"""Create labelled visual review sheets from real, unmodified product crops."""
import json
from pathlib import Path
import sys
from PIL import Image, ImageDraw

root = Path(sys.argv[1])
widths = (320, 480, 670, 1280)
stages = ('source', 'design', 'review', 'approval', 'approval-decisions')
manifest = []
for stage in stages:
    sheet = Image.new('RGB', (4 * 324, 2 * 924), '#888888')
    draw = ImageDraw.Draw(sheet)
    for row, theme in enumerate(('light', 'dark')):
        for col, width in enumerate(widths):
            name = f'{stage}-{width}-{theme}.png'
            with Image.open(root / name) as source:
                image = source.convert('RGB')
                assert image.width == width + 2 and image.height > 100, name
                # Exclude the harness's 1px frame; never alter product styling.
                image = image.crop((1, 1, image.width - 1, image.height - 1))
                (root / 'product').mkdir(exist_ok=True)
                image.save(root / 'product' / name)
                manifest.append({'file': 'product/' + name, 'width': image.width, 'height': image.height})
                image.thumbnail((320, 900))
                x, y = col * 324 + 2, row * 924 + 24
                sheet.paste(image, (x, y))
                draw.text((x, y - 20), f'{stage} | {width} | {theme}', fill='white')
    sheet.save(root / f'review-sheet-{stage}.png')
assert len(manifest) == 40
(root / 'screenshot-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(json.dumps({'verified_screenshots': len(manifest), 'review_sheets': len(stages)}))
