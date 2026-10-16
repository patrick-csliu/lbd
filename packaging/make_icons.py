"""Generate the app/file icons in packaging/icons/ (ICO for Windows, PNG + SVG for Linux)."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "icons"
BLUE = (0, 114, 178, 255)  # Okabe–Ito blue, same as the UI accent
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="6" fill="#0072B2"/>
<path d="M6 22 L12 14 L17 18 L26 8" stroke="white" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def draw(size: int = 1024) -> Image.Image:
    s = size / 32
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=6 * s, fill=BLUE)
    pts = [(6 * s, 22 * s), (12 * s, 14 * s), (17 * s, 18 * s), (26 * s, 8 * s)]
    w = round(3 * s)
    d.line(pts, fill="white", width=w, joint="curve")
    for x, y in (pts[0], pts[-1]):  # round caps
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill="white")
    return img


def main() -> None:
    OUT.mkdir(exist_ok=True)
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(OUT / "lbd.png")
    big.save(OUT / "lbd.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    (OUT / "lbd.svg").write_text(SVG, encoding="utf-8")
    print(f"icons written to {OUT}")


if __name__ == "__main__":
    main()
