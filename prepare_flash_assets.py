from pathlib import Path
from collections import deque

import numpy as np
from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
NORMAL_MASTER = ROOT / "generated" / "flash-girl-normal-master-blue-green-v6.png"
FULL_MASTER = ROOT / "generated" / "flash-girl-full-master-blue-green-v3.png"
NORMAL_BLINK = ROOT / "generated" / "flash-girl-normal-blink-blue-green-v6.png"
FULL_BLINK = ROOT / "generated" / "flash-girl-full-blink-blue-green-v3.png"
STAND_NORMAL_MASTER = ROOT / "generated" / "flash-girl-stand-normal-master-blue-green-v2.png"
STAND_FULL_MASTER = ROOT / "generated" / "flash-girl-stand-full-master-blue-green-v3.png"
STAND_NORMAL_BLINK = ROOT / "generated" / "flash-girl-stand-normal-blink-blue-green-v2.png"
STAND_FULL_BLINK = ROOT / "generated" / "flash-girl-stand-full-blink-blue-green-v3.png"
ACTIONS = ROOT / "generated" / "flash-girl-actions-blue-green.png"
EXTRA = ROOT / "generated" / "flash-girl-poses-blue-green.png"
NORMAL_KNEAD = ROOT / "generated" / "flash-girl-knead-normal-blue-green.png"
FULL_KNEAD = ROOT / "generated" / "flash-girl-knead-full-blue-green-v2.png"
READ_FULL = ROOT / "generated" / "flash-girl-read-full-blue-green-v1.png"
READ_NORMAL = ROOT / "generated" / "flash-girl-read-normal-hd-v5.png"
TYPING_NORMAL = ROOT / "generated" / "flash-girl-typing-normal-blue-green-v1.png"
TYPING_FULL = ROOT / "generated" / "flash-girl-typing-full-blue-green-v1.png"
CELL = (1024, 1108)
THEMES = {
    "original": (0, 1.0, 1.0),
}


def alpha_safe_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    rgba = np.asarray(image.convert("RGBA"), dtype=np.float32) / 255.0
    alpha = rgba[..., 3]
    premultiplied = rgba[..., :3] * alpha[..., None]
    resized_alpha = np.asarray(
        Image.fromarray(alpha, mode="F").resize(size, Image.Resampling.LANCZOS),
        dtype=np.float32,
    )
    resized_alpha = np.clip(resized_alpha, 0.0, 1.0)
    resized_pm = np.stack(
        [
            np.asarray(
                Image.fromarray(premultiplied[..., channel], mode="F").resize(
                    size, Image.Resampling.LANCZOS
                ),
                dtype=np.float32,
            )
            for channel in range(3)
        ],
        axis=-1,
    )
    rgb = np.clip(
        resized_pm / np.maximum(resized_alpha[..., None], 1.0 / 255.0),
        0.0,
        1.0,
    )
    rgb_u8 = np.round(rgb * 255.0).astype(np.uint8)
    sharpened = np.asarray(
        Image.fromarray(rgb_u8, "RGB").filter(
            ImageFilter.UnsharpMask(radius=0.75, percent=58, threshold=2)
        ),
        dtype=np.float32,
    )
    weight = resized_alpha[..., None] ** 2
    final_rgb = np.clip(
        np.round(rgb_u8.astype(np.float32) * (1.0 - weight) + sharpened * weight),
        0,
        255,
    ).astype(np.uint8)
    alpha_u8 = np.round(resized_alpha * 255.0).astype(np.uint8)
    final_rgb[alpha_u8 == 0] = 0
    return Image.fromarray(np.dstack([final_rgb, alpha_u8]), "RGBA")


def repair_pinholes(image: Image.Image) -> Image.Image:
    """Close tiny matte holes without expanding the outer silhouette."""
    data = np.asarray(image.convert("RGBA")).copy()
    alpha = data[..., 3]
    alpha_image = Image.fromarray(alpha, "L")
    closed = np.asarray(
        alpha_image.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3)),
        dtype=np.uint8,
    )
    fill = (closed > alpha) & (closed > 48)
    if not np.any(fill):
        return image
    for channel in range(3):
        seeded = np.where(alpha > 0, data[..., channel], 0).astype(np.uint8)
        expanded = np.asarray(
            Image.fromarray(seeded, "L").filter(ImageFilter.MaxFilter(3)),
            dtype=np.uint8,
        )
        data[..., channel][fill] = expanded[fill]
    data[..., 3][fill] = closed[fill]
    data[data[..., 3] == 0, :3] = 0
    return Image.fromarray(data, "RGBA")


def apply_theme(image: Image.Image, theme: str) -> Image.Image:
    delta, saturation_factor, value_factor = THEMES[theme]
    if theme == "original":
        return image.copy()
    rgba = image.convert("RGBA")
    hsv = np.asarray(rgba.convert("RGB").convert("HSV"), dtype=np.uint8).copy()
    alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    hue = hsv[..., 0].astype(np.int16)
    saturation = hsv[..., 1]
    value = hsv[..., 2]
    luminous_blue = (alpha > 8) & (saturation > 35) & ((hue >= 145) | (hue <= 15))
    hue[luminous_blue] = (hue[luminous_blue] + delta) % 256
    saturation[luminous_blue] = np.clip(
        saturation[luminous_blue].astype(np.float32) * saturation_factor, 0, 255
    ).astype(np.uint8)
    value[luminous_blue] = np.clip(
        value[luminous_blue].astype(np.float32) * value_factor, 0, 255
    ).astype(np.uint8)
    hsv[..., 0] = hue.astype(np.uint8)
    rgb = Image.fromarray(hsv, "HSV").convert("RGB")
    rgb.putalpha(rgba.getchannel("A"))
    data = np.asarray(rgb).copy()
    data[alpha == 0, :3] = 0
    return Image.fromarray(data, "RGBA")


def isolate_largest_subject(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    mask = np.asarray(rgba.getchannel("A"), dtype=np.uint8) > 24
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    best: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            component: list[tuple[int, int]] = []
            queue = deque([(x, y)])
            visited[y, x] = True
            while queue:
                cx, cy = queue.popleft()
                component.append((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((nx, ny))
            if len(component) > len(best):
                best = component
    if not best:
        raise ValueError("empty generated subject")
    subject = np.zeros_like(mask, dtype=bool)
    for x, y in best:
        subject[y, x] = True

    # Pale face, dress and teacup details can be mistaken for the baked white
    # checkerboard. Restore only small transparent islands fully enclosed by
    # the main subject; true background remains connected to the cell edge.
    inverse = ~subject
    visited_holes = np.zeros_like(mask, dtype=bool)
    fill_holes = np.zeros_like(mask, dtype=bool)
    for y in range(height):
        for x in range(width):
            if not inverse[y, x] or visited_holes[y, x]:
                continue
            component: list[tuple[int, int]] = []
            queue = deque([(x, y)])
            visited_holes[y, x] = True
            touches_edge = False
            while queue:
                cx, cy = queue.popleft()
                component.append((cx, cy))
                touches_edge |= cx == 0 or cy == 0 or cx == width - 1 or cy == height - 1
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < width and 0 <= ny < height and inverse[ny, nx] and not visited_holes[ny, nx]:
                        visited_holes[ny, nx] = True
                        queue.append((nx, ny))
            if not touches_edge and len(component) <= 24:
                for cx, cy in component:
                    fill_holes[cy, cx] = True

    data = np.asarray(rgba).copy()
    data[..., 3][fill_holes] = 255
    subject |= fill_holes
    keep = subject.astype(np.uint8) * 255
    keep = np.asarray(Image.fromarray(keep, "L").filter(ImageFilter.MaxFilter(5)))
    data[keep == 0] = 0
    return Image.fromarray(data, "RGBA")


def extract_cell(sheet: Image.Image, cols: int, rows: int, col: int, row: int) -> Image.Image:
    left = round(col * sheet.width / cols)
    right = round((col + 1) * sheet.width / cols)
    top = round(row * sheet.height / rows)
    bottom = round((row + 1) * sheet.height / rows)
    crop = isolate_largest_subject(sheet.crop((left, top, right, bottom)))
    bbox = crop.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError(f"empty generated cell {col},{row}")
    subject = crop.crop(bbox)
    max_size = (940, 1050)
    ratio = min(max_size[0] / subject.width, max_size[1] / subject.height)
    resized = alpha_safe_resize(
        subject,
        (max(1, round(subject.width * ratio)), max(1, round(subject.height * ratio))),
    )
    resized = repair_pinholes(resized)
    canvas = Image.new("RGBA", CELL, (0, 0, 0, 0))
    x = (CELL[0] - resized.width) // 2
    y = CELL[1] - resized.height - 8
    canvas.alpha_composite(resized, (x, y))
    return canvas


def load_source_with_alpha(path: Path) -> Image.Image:
    source = Image.open(path)
    source_alpha = source.convert("RGBA").getchannel("A")
    corner_points = (
        (0, 0),
        (source.width - 1, 0),
        (0, source.height - 1),
        (source.width - 1, source.height - 1),
    )
    has_clean_transparent_background = (
        "A" in source.getbands()
        and source_alpha.getextrema()[0] < 254
        and all(source_alpha.getpixel(point) <= 2 for point in corner_points)
    )
    if not has_clean_transparent_background:
        rgb = np.asarray(source.convert("RGB"), dtype=np.float32)
        corner_samples = np.concatenate(
            [
                rgb[:24, :24].reshape(-1, 3),
                rgb[:24, -24:].reshape(-1, 3),
                rgb[-24:, :24].reshape(-1, 3),
                rgb[-24:, -24:].reshape(-1, 3),
            ],
            axis=0,
        )
        background = np.median(corner_samples, axis=0)
        green_screen = (
            background[1] > 100
            and background[1] > background[0] + 30
            and background[1] > background[2] + 30
        )
        if green_screen:
            # Use a steep green-screen transition: true green stays transparent,
            # while cyan clothing and highlights become fully opaque instead of
            # turning into translucent spots.
            green_dominance = rgb[..., 1] - np.maximum(rgb[..., 0], rgb[..., 2])
            background_dominance = background[1] - max(background[0], background[2])
            key_cutoff = max(48.0, background_dominance * 0.74)
            alpha = np.clip((key_cutoff - green_dominance) * 12.0, 0, 255).astype(np.uint8)
            foreground = alpha > 0
            clean_green = np.maximum(rgb[..., 0], rgb[..., 2]) * 1.02
            rgb[..., 1][foreground] = np.minimum(rgb[..., 1][foreground], clean_green[foreground])
        else:
            chroma = rgb.max(axis=-1) - rgb.min(axis=-1)
            mean = rgb.mean(axis=-1)
            # Fallback for older sources with a nearly-white checkerboard.
            signal = np.maximum(
                np.maximum(0.0, chroma - 4.0) * 8.0,
                np.maximum(0.0, 225.0 - mean) * 6.0,
            )
            alpha = np.clip((signal - 12.0) * 3.0, 0, 255).astype(np.uint8)
        alpha = np.asarray(
            Image.fromarray(alpha, "L").filter(ImageFilter.GaussianBlur(0.35)),
            dtype=np.uint8,
        ).copy()
        alpha[alpha < 48] = 0
        alpha[[0, -1], :] = 0
        alpha[:, [0, -1]] = 0
        data = np.dstack([rgb.astype(np.uint8), alpha])
        image = Image.fromarray(data, "RGBA")
    else:
        image = source.convert("RGBA")
        data = np.asarray(image).copy()
        source_alpha = data[..., 3]
        # Image generation can return a mostly translucent subject. Make the
        # character itself solid while retaining a narrow antialiased outline.
        solid_alpha = np.where(
            source_alpha >= 80,
            255,
            np.clip(source_alpha.astype(np.float32) * 3.2, 0, 255),
        ).astype(np.uint8)
        data[..., 3] = solid_alpha
        data[solid_alpha == 0, :3] = 0
        image = Image.fromarray(data, "RGBA")
    alpha = image.getchannel("A")
    if alpha.getextrema()[0] != 0 or alpha.getbbox() is None:
        raise ValueError(f"invalid alpha source: {path}")
    for point in corner_points:
        if image.getpixel(point)[3] > 2:
            raise ValueError(f"opaque source corner: {path} {point}")
    return image


def main() -> None:
    normal_master_sheet = load_source_with_alpha(NORMAL_MASTER)
    full_master_sheet = load_source_with_alpha(FULL_MASTER)
    normal_blink_sheet = load_source_with_alpha(NORMAL_BLINK)
    full_blink_sheet = load_source_with_alpha(FULL_BLINK)
    stand_normal_master_sheet = load_source_with_alpha(STAND_NORMAL_MASTER)
    stand_full_master_sheet = load_source_with_alpha(STAND_FULL_MASTER)
    stand_normal_blink_sheet = load_source_with_alpha(STAND_NORMAL_BLINK)
    stand_full_blink_sheet = load_source_with_alpha(STAND_FULL_BLINK)
    action_sheet = load_source_with_alpha(ACTIONS)
    extra_sheet = load_source_with_alpha(EXTRA)
    normal_knead_sheet = load_source_with_alpha(NORMAL_KNEAD)
    full_knead_sheet = load_source_with_alpha(FULL_KNEAD)
    read_full_sheet = load_source_with_alpha(READ_FULL)
    read_normal_sheet = load_source_with_alpha(READ_NORMAL)
    typing_normal_sheet = load_source_with_alpha(TYPING_NORMAL)
    typing_full_sheet = load_source_with_alpha(TYPING_FULL)
    normal_master = extract_cell(normal_master_sheet, 1, 1, 0, 0)
    full_master = extract_cell(full_master_sheet, 1, 1, 0, 0)
    normal_blink = [[extract_cell(normal_blink_sheet, 2, 2, col, row) for col in range(2)] for row in range(2)]
    full_blink = [[extract_cell(full_blink_sheet, 2, 2, col, row) for col in range(2)] for row in range(2)]
    stand_normal_master = extract_cell(stand_normal_master_sheet, 1, 1, 0, 0)
    stand_full_master = extract_cell(stand_full_master_sheet, 1, 1, 0, 0)
    stand_normal_blink = [[extract_cell(stand_normal_blink_sheet, 2, 2, col, row) for col in range(2)] for row in range(2)]
    stand_full_blink = [[extract_cell(stand_full_blink_sheet, 2, 2, col, row) for col in range(2)] for row in range(2)]
    action = [[extract_cell(action_sheet, 2, 2, col, row) for col in range(2)] for row in range(2)]
    extra = [[extract_cell(extra_sheet, 2, 2, col, row) for col in range(2)] for row in range(2)]
    normal_knead = [[extract_cell(normal_knead_sheet, 2, 2, col, row) for col in range(2)] for row in range(2)]
    full_knead = [[extract_cell(full_knead_sheet, 2, 2, col, row) for col in range(2)] for row in range(2)]
    read_full = extract_cell(read_full_sheet, 1, 1, 0, 0)
    read_normal = extract_cell(read_normal_sheet, 1, 1, 0, 0)
    typing_normal = [[extract_cell(typing_normal_sheet, 2, 2, col, row) for col in range(2)] for row in range(2)]
    typing_full = [[extract_cell(typing_full_sheet, 2, 2, col, row) for col in range(2)] for row in range(2)]

    row_frames = {
        0: [normal_master],
        1: [normal_blink[0][0], normal_blink[0][1], normal_blink[1][0], normal_blink[1][1]],
        2: [full_master],
        3: [full_blink[0][0], full_blink[0][1], full_blink[1][0], full_blink[1][1]],
        4: [stand_normal_master],
        5: [stand_normal_blink[0][0], stand_normal_blink[0][1], stand_normal_blink[1][0], stand_normal_blink[1][1]],
        6: [stand_full_master],
        7: [stand_full_blink[0][0], stand_full_blink[0][1], stand_full_blink[1][0], stand_full_blink[1][1]],
        8: [action[0][0]] * 4,
        9: [action[0][1]] * 5,
        10: [normal_knead[0][0], normal_knead[0][1], normal_knead[1][0], normal_knead[1][1]],
        11: [full_knead[0][0], full_knead[0][1], full_knead[1][0], full_knead[1][1]],
        12: [typing_normal[0][0], typing_normal[0][1], typing_normal[1][0], typing_normal[1][1]],
        13: [typing_full[0][0], typing_full[0][1], typing_full[1][0], typing_full[1][1]],
    }
    pose_images = {
        "bow": action[1][0],
        "shy": action[1][1],
        "dance": extra[0][0],
        "read": read_normal,
        "read_full": read_full,
        "tea": extra[1][0],
        "sit_smile": extra[1][1],
    }

    written: list[Path] = []
    for theme in THEMES:
        atlas = Image.new("RGBA", (CELL[0] * 6, CELL[1] * len(row_frames)), (0, 0, 0, 0))
        for row, frames in row_frames.items():
            for col, frame in enumerate(frames):
                atlas.alpha_composite(apply_theme(frame, theme), (col * CELL[0], row * CELL[1]))
        atlas_path = ASSETS / "atlases" / f"{theme}.png"
        atlas.save(atlas_path, "PNG", optimize=True)
        written.append(atlas_path)

        pose_dir = ASSETS / "poses" / theme
        pose_dir.mkdir(parents=True, exist_ok=True)
        for name, image in pose_images.items():
            path = pose_dir / f"{name}.png"
            apply_theme(image, theme).save(path, "PNG", optimize=True)
            written.append(path)

    for path in written:
        rgba = np.asarray(Image.open(path).convert("RGBA"))
        transparent = rgba[..., 3] == 0
        residue = int(np.count_nonzero(rgba[..., :3][transparent]))
        if residue:
            raise ValueError(f"transparent RGB residue: {path}: {residue}")
        if Image.fromarray(rgba[..., 3], "L").getbbox() is None:
            raise ValueError(f"blank output: {path}")
    print({"ok": True, "atlases": len(THEMES), "poses": len(THEMES) * len(pose_images)})


if __name__ == "__main__":
    main()

