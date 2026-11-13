"""Frames out of a video: full-size stills at given times, or a labelled contact sheet to find moments in a take or
to check a render without watching it.

usage: python frames.py <video> <t> [<t> ...] --out <prefix>     # <prefix>-1.png, <prefix>-2.png, ... full size
       python frames.py <video> --sheet <png> [--every 5] [--start 0] [--end <s>] [--cols 4] [--width 480]
"""
import argparse

from PIL import Image, ImageDraw

from media import duration, grab


def stills(video, times, prefix):
    for i, t in enumerate(times, 1):
        Image.fromarray(grab(video, t)).save(f"{prefix}-{i}.png")
        print(f"{prefix}-{i}.png  ({t:.1f} s)")


def tile(video, t, width):
    img = Image.fromarray(grab(video, t))
    img.thumbnail((width, width))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 64, 16], fill=(0, 0, 0))
    d.text((4, 2), f"{t:7.1f}s", fill=(255, 255, 0))
    return img


def contact_sheet(video, times, out, cols, width):
    tiles = [tile(video, t, width) for t in times]
    w, h = tiles[0].size
    sheet = Image.new("RGB", (w * min(cols, len(tiles)), h * ((len(tiles) + cols - 1) // cols)))
    for i, img in enumerate(tiles):
        sheet.paste(img, ((i % cols) * w, (i // cols) * h))
    sheet.save(out)
    print(f"{out}: {len(tiles)} frames from {times[0]:.1f} to {times[-1]:.1f} s")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("video")
    ap.add_argument("times", nargs="*", type=float)
    ap.add_argument("--out", help="prefix for the stills")
    ap.add_argument("--sheet", help="write a contact sheet to this PNG")
    ap.add_argument("--every", type=float, default=5.0)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--width", type=int, default=480)
    args = ap.parse_args()
    if args.sheet:
        end = min(args.end or 1e9, duration(args.video) - 0.05)
        times = [args.start + k * args.every for k in range(int((end - args.start) / args.every) + 1)]
        contact_sheet(args.video, args.times or times, args.sheet, args.cols, args.width)
    elif args.times and args.out:
        stills(args.video, args.times, args.out)
    else:
        ap.error("give times and --out, or --sheet")


if __name__ == "__main__":
    main()
