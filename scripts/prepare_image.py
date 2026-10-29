"""Make a photo or screenshot safe and small enough to publish in docs/images/.

    python3 scripts/prepare_image.py room_pics/connection.JPG docs/images/breadboard.jpg
    python3 scripts/prepare_image.py IN OUT --crop 0.3 0 1 0.65     # keep x 30–100 %, y 0–65 % of the picture

Phone photos carry the GPS position where they were taken (EXIF), plus camera and time data. This script rotates
the picture upright, optionally crops it (fractions of width and height, so you can read them off a preview),
shrinks it to at most --max pixels on the long side, and writes only the pixels: no EXIF, GPS, XMP or ICC data.
It then reopens the result and fails if any metadata survived. scripts/check_public.sh checks the same before a
commit. Needs Pillow (`python3 -m pip install pillow`); it never overwrites an existing file.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageOps


def metadata_left(path):
    """Names of the metadata blocks still in the file (empty list = clean)."""
    data = Path(path).read_bytes()
    markers = {"EXIF": b"Exif\x00\x00", "PNG eXIf": b"eXIf", "XMP": b"<x:xmpmeta", "ICC": b"ICC_PROFILE"}
    return [name for name, marker in markers.items() if marker in data]


def prepare(src, dst, crop=None, max_px=1600, quality=82):
    dst = Path(dst)
    if dst.exists():
        sys.exit(f"{dst} exists; choose a new name (this script never overwrites)")
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    if crop:
        x0, y0, x1, y1 = crop
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            sys.exit("--crop needs 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
        w, h = im.size
        im = im.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)))
    im.thumbnail((max_px, max_px))
    clean = Image.new("RGB", im.size)
    clean.paste(im)   # a fresh image holds the pixels only, none of the source's info blocks
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.suffix.lower() == ".png":
        clean.save(dst, optimize=True)
    else:
        clean.save(dst, quality=quality, optimize=True, progressive=True)
    left = metadata_left(dst)
    if left:
        dst.unlink()
        sys.exit(f"metadata survived ({', '.join(left)}); nothing written")
    return clean.size, dst.stat().st_size


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("src")
    parser.add_argument("dst", help="new file, normally docs/images/<name>.jpg (.png for screenshots)")
    parser.add_argument("--crop", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"))
    parser.add_argument("--max", type=int, default=1600, help="longest side in pixels (default 1600)")
    args = parser.parse_args()
    (w, h), size = prepare(args.src, args.dst, args.crop, args.max)
    print(f"{args.dst}: {w}×{h}, {size // 1024} KB, no metadata")


if __name__ == "__main__":
    main()
