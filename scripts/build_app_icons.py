"""Convert the original transparent artwork into native application icons.

Run with Pillow installed when the artwork changes. Release builders consume the
committed ICO and ICNS files and do not need Pillow.
"""

from pathlib import Path


def main():
    from PIL import Image

    directory = Path(__file__).resolve().parents[1] / "assets/ui"
    source = directory / "sitting-dog-v1.png"
    with Image.open(source) as image:
        artwork = image.convert("RGBA")
        if artwork.width != artwork.height:
            raise ValueError("Application artwork must be square")
        artwork.save(source.with_suffix(".ico"), sizes=[(size, size) for size in (16, 24, 32, 48, 64, 128, 256)])
        artwork.save(source.with_suffix(".icns"))
    for extension in (".ico", ".icns"):
        print(source.with_suffix(extension))


if __name__ == "__main__":
    main()
