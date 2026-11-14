"""Starting point for a LinkedIn banner generator. Copy it, then replace draw_banner().

Run: python -X utf8 banner_base.py <out.png> [--guides]
Draws at 3x and downsamples to exactly 1584 x 396. --guides tints the profile-photo zone.
"""
import random
import sys

from PIL import Image, ImageDraw, ImageFont

W, H, S = 1584, 396, 3                    # final size and supersampling factor
PHOTO_ZONE = (0, 200, 350, H)             # the profile photo covers roughly this area
MIN_READABLE = 20                         # px in the source; LinkedIn shows the banner at about half size
SEED = 1                                  # change for a different random layout


def px(*values):
    """Design-space coordinates to render-space coordinates."""
    return [value * S for value in values]


def font(path, size):
    """Load a font file at a design-space size. Use installed fonts; ask before downloading any."""
    return ImageFont.truetype(path, int(size * S))


def draw_banner(draw, layout_rng, style_rng):
    """Replace this. Use layout_rng for positions and style_rng for decoration, so style tweaks keep the layout."""
    draw.rectangle(px(0, 0, W, H), fill="#0c1110")
    for _ in range(40):
        x, y = layout_rng.uniform(0, W), layout_rng.uniform(0, H)
        radius = style_rng.choice((2, 3, 5))
        draw.ellipse(px(x - radius, y - radius, x + radius, y + radius), fill="#68cdc0")


def compose_banner():
    """The banner at 3x, before downsampling."""
    image = Image.new("RGBA", (W * S, H * S), "#000000")
    draw_banner(ImageDraw.Draw(image), random.Random(SEED), random.Random(SEED + 1))
    return image


def tint_photo_zone(image):
    """The same image with the profile-photo zone tinted red, for checking the layout."""
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle(px(*PHOTO_ZONE), fill=(255, 0, 0, 70))
    return Image.alpha_composite(image, overlay)


def save_banner(image, out_path):
    image.convert("RGB").resize((W, H), Image.LANCZOS).save(out_path)
    assert Image.open(out_path).size == (W, H)
    print(out_path)


if __name__ == "__main__":
    arguments = [a for a in sys.argv[1:] if a != "--guides"]
    if not arguments:
        sys.exit(__doc__)
    banner = compose_banner()
    save_banner(tint_photo_zone(banner) if "--guides" in sys.argv else banner, arguments[0])
