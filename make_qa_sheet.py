from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
OUT = ROOT / "qa-supplemental.png"
CELL = (192, 208)
HD_CELL = (1024, 1108)


def thumb(image: Image.Image) -> Image.Image:
    return image.resize(CELL, Image.Resampling.LANCZOS)


def main() -> None:
    items = []
    original_atlas = Image.open(ASSETS / "atlases" / "original.png").convert("RGBA")
    for row, label, count in (
        (0, "sit_idle", 1),
        (1, "sit_blink", 4),
        (2, "stand_idle", 1),
        (3, "stand_blink", 4),
        (4, "wave", 4),
        (5, "jump", 5),
        (6, "knead", 4),
        (7, "typing", 4),
    ):
        for frame in range(count):
            left = frame * HD_CELL[0]
            top = row * HD_CELL[1]
            items.append((
                f"{label}_{frame + 1}",
                original_atlas.crop((left, top, left + HD_CELL[0], top + HD_CELL[1])),
            ))
    for name in ("bow", "sit_smile", "shy", "dance", "read", "tea"):
        items.append((name, Image.open(ASSETS / "poses" / "original" / f"{name}.png").convert("RGBA")))
    for name in ("idle", "shy"):
        items.append(
            (
                f"cat_original_{name}",
                Image.open(ASSETS / "cat" / "original" / f"{name}.png").convert("RGBA"),
            )
        )

    cols = 5
    slot_w, slot_h = 208, 244
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * slot_w, rows * slot_h), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(items):
        col, row = index % cols, index // cols
        x, y = col * slot_w + 8, row * slot_h + 28
        checker = Image.new("RGB", CELL, "#f8f8f8")
        cdraw = ImageDraw.Draw(checker)
        for cy in range(0, CELL[1], 16):
            for cx in range(0, CELL[0], 16):
                if (cx // 16 + cy // 16) % 2:
                    cdraw.rectangle((cx, cy, cx + 15, cy + 15), fill="#dddddd")
        pose = thumb(image)
        checker.paste(pose, (0, 0), pose)
        sheet.paste(checker, (x, y))
        draw.text((x, row * slot_h + 8), label, fill="#222222")
    sheet.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()

