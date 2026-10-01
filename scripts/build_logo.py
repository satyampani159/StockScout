"""Generate the browser-tab icon: two overlapping dollar signs (blue and green).

Run from the project root: python scripts/build_logo.py
Writes stockscout/ui/assets/favicon.png (committed, so hosts do not need the font).
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "stockscout" / "ui" / "assets" / "favicon.png"
SIZE = 256
BLUE, GREEN = (37, 99, 235, 255), (22, 163, 74, 235)


def _font(px: int):
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = _font(230)
    for (dx, dy), color in (((-42, -6), BLUE), ((42, 10), GREEN)):  # second sign overlaps the first
        box = d.textbbox((0, 0), "$", font=f)
        w, h = box[2] - box[0], box[3] - box[1]
        d.text(((SIZE - w) / 2 - box[0] + dx, (SIZE - h) / 2 - box[1] + dy), "$", font=f, fill=color)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print("saved", OUT)


if __name__ == "__main__":
    main()
