"""Mock each banner on a LinkedIn profile card, in LinkedIn's light and dark modes.

Run: python -X utf8 profile_preview.py <banner.png> [more.png ...] [--out preview.png]
Each banner is first reduced to the small JPEG copy LinkedIn actually serves, so the preview shows the
real loss of sharpness. Proportions approximate the desktop card: banner 792 x 198, photo 152 px, 24 px
from the left, overlapping the lower part of the banner. A grey disc stands in for the photo. Mobile is not covered.
"""
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

MODES = {"light": ("#f4f2ee", "#ffffff", "#191919", "#8a8a8a"), "dark": ("#000000", "#1b1f23", "#f2f2f2", "#6f757b")}
CARD_W, BANNER_H, CARD_H, PAD = 792, 198, 330, 24
SERVED = (842, 209)   # the JPEG copy LinkedIn sends to standard-density desktop screens


def as_served(banner_path):
    """The banner as LinkedIn serves it on a standard screen: an 842 x 209 JPEG, shown at 792 x 198.

    Measured on a live profile in November 2026: a 1584 x 396 PNG upload came back as 47 to 59 KB,
    which quality 70 roughly reproduces for a detailed image. It is an approximation: LinkedIn's own
    compression is not published, so check the live profile after uploading.
    """
    buffer = io.BytesIO()
    Image.open(banner_path).convert("RGB").resize(SERVED, Image.LANCZOS).save(buffer, "JPEG", quality=70)
    return Image.open(buffer).resize((CARD_W, BANNER_H), Image.LANCZOS)


def card(banner_path, mode):
    page, surface, text, muted = MODES[mode]
    image = Image.new("RGB", (CARD_W + 2 * PAD, CARD_H + 2 * PAD), page)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([PAD, PAD, PAD + CARD_W, PAD + CARD_H], radius=8, fill=surface)
    image.paste(as_served(banner_path), (PAD, PAD))
    left, top = PAD + 24, PAD + BANNER_H - 112
    draw.ellipse([left - 4, top - 4, left + 156, top + 156], fill=surface)
    draw.ellipse([left, top, left + 152, top + 152], fill="#9aa3ab")
    draw.rounded_rectangle([left, top + 176, left + 200, top + 196], radius=4, fill=text)      # name
    draw.rounded_rectangle([left, top + 208, left + 420, top + 220], radius=4, fill=muted)     # headline
    return image


def split_arguments(arguments):
    """Return (banner paths, output path) from the command line."""
    out = Path("linkedin-banner-preview.png")
    if "--out" in arguments:
        position = arguments.index("--out")
        if position + 1 >= len(arguments):
            sys.exit("--out needs a file path")
        out = Path(arguments[position + 1])
        arguments = arguments[:position] + arguments[position + 2:]
    return arguments, out


def profile_sheet(cards):
    """Lay out rows of (light card, dark card) pairs on one sheet."""
    width, height = cards[0][0].size
    sheet = Image.new("RGB", (2 * width, len(cards) * height), "#888888")
    for row, pair in enumerate(cards):
        for column, item in enumerate(pair):
            sheet.paste(item, (column * width, row * height))
    return sheet


if __name__ == "__main__":
    paths, out_path = split_arguments(sys.argv[1:])
    if not paths:
        sys.exit(__doc__)
    sheet = profile_sheet([[card(path, mode) for mode in MODES] for path in paths])
    sheet.save(out_path)
    print(out_path, sheet.size)
