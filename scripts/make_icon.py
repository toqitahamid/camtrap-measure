"""Draw the app icon from the mark the window already uses.

The mark is `mark` in frontend/src/Icon.tsx — four corner brackets and four ticks aiming at the middle,
a camera frame sighting an animal. Windows wants a .ico, so this draws the same shape big and lets
Pillow pack the sizes. Run it when the mark changes; the .ico it writes is committed.

    uv run python scripts/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

TILE = "#14171b"  # --pane: the app's own panel colour, so the icon reads as the app at 16 px
MARK = "#e8a13c"  # --amber
BIG = 1024
SIZES = [16, 24, 32, 48, 64, 128, 256]
OUT = Path(__file__).resolve().parent.parent / "src" / "camtrap_measure" / "assets" / "camtrap-measure.ico"


def draw(ticks: bool) -> Image.Image:
    """The mark at 1024 px. Below 32 px the four ticks close into a blur, so the small sizes are drawn
    from the brackets alone, wider apart and heavier - the same sight, still legible in a taskbar."""
    img = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = BIG / 24  # the mark's own 24-unit grid
    d.rounded_rectangle([0, 0, BIG - 1, BIG - 1], radius=int(4.5 * u), fill=TILE)

    w = int((1.55 if ticks else 2.2) * u)  # heavier than the screen mark's 2/24, which vanishes when small

    def line(*points):
        d.line([(x * u, y * u) for x, y in points], fill=MARK, width=w, joint="curve")

    inset, arm = (5, 3) if ticks else (4.4, 3.8)
    for x, y, dx, dy in ((inset, inset, 1, 1), (24 - inset, inset, -1, 1),
                         (inset, 24 - inset, 1, -1), (24 - inset, 24 - inset, -1, -1)):
        line((x, y + arm * dy), (x, y), (x + arm * dx, y))  # corner bracket
    if ticks:  # the sight closing on the middle
        line((12, 8.4), (12, 10.2))
        line((12, 15.6), (12, 13.8))
        line((8.4, 12), (10.2, 12))
        line((15.6, 12), (13.8, 12))
    return img


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    # Each size downsampled from its own 1024 render: letting Windows shrink one 256 loses the strokes
    frames = [draw(ticks=s >= 32).resize((s, s), Image.LANCZOS) for s in SIZES]
    frames[-1].save(OUT, sizes=[(s, s) for s in SIZES], append_images=frames)
    print(f"{OUT} - {', '.join(str(s) for s in SIZES)} px, {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
