"""Native-size contact sheets from the real-SDK synthetic preview captures."""
from pathlib import Path
import sys
from PIL import Image, ImageDraw

root = Path(sys.argv[1])
scenes = ["hint", "groups-collapsed", "sessions-expanded", "sessions-collapsed"]
for width in (320, 670):
    for theme in ("dark", "light"):
        bg, fg = ((22, 30, 28), (225, 235, 230)) if theme == "dark" else ((248, 249, 250), (32, 36, 44))
        height = 720 if width == 320 else 640
        sheet = Image.new("RGB", (2 * (width + 24), 2 * (height + 40)), bg)
        draw = ImageDraw.Draw(sheet)
        for i, scene in enumerate(scenes):
            image = Image.open(root / f"{scene}-{width}-{theme}-pane.png").convert("RGB")
            # Use the exact DOM screenshot, not guessed fixture coordinates.
            crop = image.crop((0, 0, image.width, height))
            ox, oy = (i % 2) * (width + 24) + 12, (i // 2) * (height + 40) + 28
            sheet.paste(crop, (ox, oy))
            draw.text((ox, oy - 20), f"{scene} / {width}px / {theme}", fill=fg)
        target = root / f"review-{width}-{theme}.png"
        sheet.save(target)
        print(target)
