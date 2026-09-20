from __future__ import annotations

import ctypes
import json
import os
import random
import sys
import time
from pathlib import Path

import psutil
from PIL import Image, ImageChops, ImageFilter
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass


SOURCE_W = 1024
SOURCE_H = 1108
DISPLAY_W = 512
DISPLAY_H = 554
ROWS = {
    "sit_normal_idle": (0, 1),
    "sit_normal_blink": (1, 4),
    "sit_full_idle": (2, 1),
    "sit_full_blink": (3, 4),
    "stand_normal_idle": (4, 1),
    "stand_normal_blink": (5, 4),
    "stand_full_idle": (6, 1),
    "stand_full_blink": (7, 4),
    "waving": (8, 4),
    "jumping": (9, 5),
    "normal_knead": (10, 4),
    "full_knead": (11, 4),
    "typing_normal": (12, 4),
    "typing_full": (13, 4),
}
FRAME_MS = {
    "sit_normal_idle": 260,
    "sit_normal_blink": 135,
    "sit_full_idle": 260,
    "sit_full_blink": 135,
    "stand_normal_idle": 260,
    "stand_normal_blink": 135,
    "stand_full_idle": 260,
    "stand_full_blink": 135,
    "waving": 150,
    "jumping": 110,
    "normal_knead": 180,
    "full_knead": 180,
    "typing_normal": 155,
    "typing_full": 155,
}
POSES = ("bow", "sit_smile", "shy", "dance", "read", "read_full", "tea")
THEMES = {
    "original": "浅蓝星光",
}


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / relative


def settings_path() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home())) / "YuliPetDeluxe"
    root.mkdir(parents=True, exist_ok=True)
    return root / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pil_to_pixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    qimage = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage.copy())


def display_frame(source: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Downsample once, then sharpen color without altering the alpha outline."""
    resized = source.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")
    alpha = resized.getchannel("A")
    rgb = resized.convert("RGB")
    # Broad, low-strength detail contrast followed by fine line definition.
    detailed = rgb.filter(ImageFilter.UnsharpMask(radius=1.6, percent=18, threshold=3))
    detailed = detailed.filter(ImageFilter.UnsharpMask(radius=0.65, percent=72, threshold=2))
    # Do not sharpen transparent pixels or produce a fringe on the silhouette.
    solid_weight = ImageChops.multiply(alpha, alpha)
    result = Image.composite(detailed, rgb, solid_weight).convert("RGBA")
    result.putalpha(alpha)
    return result


class YuliDeluxeQt(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.setWindowTitle("闪光少女 · 桌宠")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.size_percent = min(100, max(20, int(self.settings.get("size_percent", 50))))
        self.theme = "original"
        self.form = self.settings.get("form", "human")
        if self.form not in {"human", "cat"}:
            self.form = "human"
        self.full_meal_state = bool(self.settings.get("full_meal_state", False))
        self.stats_light_text = bool(self.settings.get("stats_light_text", False))
        self.posture = self.settings.get("posture", "sitting")
        if self.posture not in {"sitting", "standing"}:
            self.posture = "sitting"
        self.activity_state = self.settings.get("activity_state", self.posture)
        if self.activity_state not in {"sitting", "standing", "reading", "typing"}:
            self.activity_state = self.posture
        self.paused = False
        self.closing = False
        self.saved_position: tuple[int, int] | None = None

        self.stats_enabled = {
            "cpu": bool(self.settings.get("stats", {}).get("cpu", False)),
            "memory": bool(self.settings.get("stats", {}).get("memory", False)),
            "disk": bool(self.settings.get("stats", {}).get("disk", False)),
            "network": bool(self.settings.get("stats", {}).get("network", False)),
        }
        self.last_net = psutil.net_io_counters()
        self.last_net_time = time.monotonic()

        self.atlas: Image.Image
        self.poses: dict[str, Image.Image] = {}
        self.cat_poses: dict[str, Image.Image] = {}
        self.load_theme(self.theme)
        self.frame_cache: dict[tuple, QPixmap] = {}
        self.current_pixmap: QPixmap | None = None

        primary = QGuiApplication.primaryScreen()
        if primary is None:
            raise RuntimeError("No display available")
        available = primary.availableGeometry()
        target_x = int(self.settings.get("x", available.right() - self.display_width - 60))
        target_y = int(self.settings.get("y", available.bottom() - self.display_height - 80))
        target_x, target_y = self.clamp_position(target_x, target_y)
        self.target_position = (target_x, target_y)
        self.window_x = target_x
        self.window_y = available.bottom() - 45
        self.resize(self.display_width, self.display_height)
        self.move(self.window_x, self.window_y)

        meal_key = "full" if self.full_meal_state else "normal"
        if self.form == "cat":
            self.visual_type, self.visual_name = "cat", "idle"
        elif self.activity_state == "reading":
            self.visual_type = "pose"
            self.visual_name = "read_full" if self.full_meal_state else "read"
        elif self.activity_state == "typing":
            self.visual_type, self.visual_name = "base", f"typing_{meal_key}"
        else:
            posture_key = "sit" if self.activity_state == "sitting" else "stand"
            self.visual_type, self.visual_name = "base", f"{posture_key}_{meal_key}_idle"
        self.frame = 0
        self.frame_phase = 0
        self.last_tick = time.monotonic()
        self.action_until = 0.0
        self.drag_origin: tuple[int, int, int, int] | None = None
        self.dragged = False
        self.press_zone = "body"
        self.next_random_action = time.monotonic() + random.uniform(22, 38)
        self.next_blink = time.monotonic() + random.uniform(4.0, 8.0)

        self.stats_window = QLabel()
        self.stats_window.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.stats_window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.stats_window.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.apply_stats_style()
        self.stats_window.hide()

        self.build_menu()
        self.render()
        self.show()

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.tick)
        self.tick_timer.start(30)
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.update_stats)
        self.stats_timer.start(1000)
        QTimer.singleShot(80, lambda: self.animate_intro(0))

    @property
    def scale(self) -> float:
        return self.size_percent / 100.0

    @property
    def display_width(self) -> int:
        return max(1, round(DISPLAY_W * self.scale))

    @property
    def display_height(self) -> int:
        return max(1, round(DISPLAY_H * self.scale))

    def load_theme(self, theme: str) -> None:
        self.theme = theme
        self.atlas = Image.open(resource_path(f"assets/atlases/{theme}.png")).convert("RGBA")
        self.poses = {
            name: Image.open(resource_path(f"assets/poses/{theme}/{name}.png")).convert("RGBA")
            for name in POSES
        }
        self.cat_poses = {}
        for name in ("idle", "shy"):
            image = Image.open(resource_path(f"assets/cat/{theme}/{name}.png")).convert("RGBA")
            if image.size != (SOURCE_W, SOURCE_H):
                image = image.resize((SOURCE_W, SOURCE_H), Image.Resampling.LANCZOS)
            self.cat_poses[name] = image
        if hasattr(self, "frame_cache"):
            self.frame_cache.clear()

    def build_menu(self) -> None:
        self.menu = QMenu(self)
        action_menu = self.menu.addMenu("手动动作")
        action_menu.addAction("招手", lambda: self.play_base("waving", 1200))
        action_menu.addAction("跳一下", lambda: self.play_base("jumping", 900))
        action_menu.addAction("揉揉肚子", self.play_belly_knead)
        action_menu.addAction("鞠躬", lambda: self.play_pose("bow", 1200))
        action_menu.addAction("害羞", lambda: self.play_pose("shy", 1400))
        action_menu.addAction("跳舞", lambda: self.play_pose("dance", 2800))
        action_menu.addAction("喝茶", lambda: self.play_pose("tea", 3000))

        posture_menu = self.menu.addMenu("持续状态")
        self.posture_group = QActionGroup(self)
        self.posture_group.setExclusive(True)
        self.sitting_action = posture_menu.addAction("坐下")
        self.sitting_action.setCheckable(True)
        self.sitting_action.setChecked(self.activity_state == "sitting")
        self.sitting_action.triggered.connect(self.sit_down)
        self.posture_group.addAction(self.sitting_action)
        self.standing_action = posture_menu.addAction("站立")
        self.standing_action.setCheckable(True)
        self.standing_action.setChecked(self.activity_state == "standing")
        self.standing_action.triggered.connect(self.stand_up)
        self.posture_group.addAction(self.standing_action)
        self.reading_action = posture_menu.addAction("看书")
        self.reading_action.setCheckable(True)
        self.reading_action.setChecked(self.activity_state == "reading")
        self.reading_action.triggered.connect(self.read_continuously)
        self.posture_group.addAction(self.reading_action)
        self.typing_action = posture_menu.addAction("敲键盘")
        self.typing_action.setCheckable(True)
        self.typing_action.setChecked(self.activity_state == "typing")
        self.typing_action.triggered.connect(self.type_continuously)
        self.posture_group.addAction(self.typing_action)

        form_menu = self.menu.addMenu("变身")
        form_menu.addAction("少女形态", lambda: self.transform("human"))
        form_menu.addAction("胖乎乎银蓝小猫", lambda: self.transform("cat"))

        self.full_meal_action = self.menu.addAction("吃饱饭状态（持续）")
        self.full_meal_action.setCheckable(True)
        self.full_meal_action.setChecked(self.full_meal_state)
        self.full_meal_action.triggered.connect(self.toggle_full_meal_state)

        tools = self.menu.addMenu("系统工具")
        self.stats_actions: dict[str, QAction] = {}
        for key, label in (
            ("cpu", "CPU 使用率"),
            ("memory", "内存使用率"),
            ("disk", "存储使用率"),
            ("network", "网络速度与状态"),
        ):
            action = tools.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.stats_enabled[key])
            action.triggered.connect(self.on_stats_toggle)
            self.stats_actions[key] = action
        tools.addSeparator()
        self.stats_light_action = tools.addAction("浅色文字模式（深色背景）")
        self.stats_light_action.setCheckable(True)
        self.stats_light_action.setChecked(self.stats_light_text)
        self.stats_light_action.triggered.connect(self.toggle_stats_light_mode)

        self.menu.addAction("重设大小（20%～100%）", self.open_size_dialog)
        self.menu.addAction("暂停 / 继续", self.toggle_pause)
        self.menu.addSeparator()
        self.menu.addAction("退出雨璃", self.close_pet)

    def base_frame(self, state: str, frame: int) -> Image.Image:
        row, count = ROWS[state]
        frame %= count
        image = self.atlas.crop(
            (
                frame * SOURCE_W,
                row * SOURCE_H,
                (frame + 1) * SOURCE_W,
                (row + 1) * SOURCE_H,
            )
        )
        return image

    def animated_static(self, image: Image.Image, name: str, phase: int) -> Image.Image:
        phase %= 4
        angle = 0.0
        offset_y = 0
        if name == "dance":
            angle = (-1.0, 0.0, 1.0, 0.0)[phase]
            offset_y = (0, -2, 0, 1)[phase]
        rotated = image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False) if angle else image
        canvas = Image.new("RGBA", (SOURCE_W, SOURCE_H), (0, 0, 0, 0))
        canvas.alpha_composite(rotated, (0, offset_y))
        return canvas

    def current_source_frame(self) -> Image.Image:
        if self.visual_type == "base":
            return self.base_frame(self.visual_name, self.frame)
        if self.visual_type == "pose":
            return self.animated_static(self.poses[self.visual_name], self.visual_name, self.frame_phase)
        image = self.cat_poses[self.visual_name]
        return self.animated_static(image, self.visual_name, self.frame_phase)

    def render(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        dpr = max(1.0, float(screen.devicePixelRatio()) if screen is not None else 1.0)
        key = (
            self.theme,
            self.form,
            self.visual_type,
            self.visual_name,
            self.frame,
            self.frame_phase,
            self.size_percent,
            round(dpr, 2),
        )
        pixmap = self.frame_cache.get(key)
        if pixmap is None:
            source = self.current_source_frame()
            pixel_size = (
                max(1, round(self.display_width * dpr)),
                max(1, round(self.display_height * dpr)),
            )
            image = display_frame(source, pixel_size)
            if self.visual_type == "pose" and self.visual_name in {"read", "read_full"}:
                # Move by a whole output pixel, not a fraction of a downsampled
                # source pixel; breathing therefore keeps the same sharpness.
                offset = (0, -1, -1, 0)[self.frame_phase % 4]
                if offset:
                    shifted = Image.new("RGBA", pixel_size, (0, 0, 0, 0))
                    shifted.alpha_composite(image, (0, offset))
                    image = shifted
            pixmap = pil_to_pixmap(image)
            pixmap.setDevicePixelRatio(dpr)
            self.frame_cache[key] = pixmap
        self.current_pixmap = pixmap
        self.update()

    def paintEvent(self, _event) -> None:
        if self.current_pixmap is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(0, 0, self.current_pixmap)

    def play_base(self, state: str, duration_ms: int = 1000) -> None:
        if self.form == "cat":
            self.play_cat("shy" if state in {"waving", "review"} else "idle", duration_ms)
            return
        self.visual_type, self.visual_name = "base", state
        self.frame = self.frame_phase = 0
        self.action_until = time.monotonic() + duration_ms / 1000.0
        self.last_tick = time.monotonic()
        self.render()

    def play_blink(self) -> None:
        posture_key = "sit" if self.posture == "sitting" else "stand"
        meal_key = "full" if self.full_meal_state else "normal"
        state = f"{posture_key}_{meal_key}_blink"
        self.play_base(state, 680)
        self.next_blink = time.monotonic() + random.uniform(4.0, 8.0)

    def play_belly_knead(self) -> None:
        state = "full_knead" if self.full_meal_state else "normal_knead"
        self.play_base(state, 1800)

    def play_pose(self, name: str, duration_ms: int = 1400) -> None:
        if self.form == "cat":
            self.play_cat("shy", duration_ms)
            return
        self.visual_type, self.visual_name = "pose", name
        self.frame_phase = 0
        self.action_until = time.monotonic() + duration_ms / 1000.0
        self.last_tick = time.monotonic()
        self.render()

    def play_cat(self, name: str, duration_ms: int = 1400) -> None:
        self.visual_type, self.visual_name = "cat", name
        self.frame_phase = 0
        self.action_until = time.monotonic() + duration_ms / 1000.0
        self.last_tick = time.monotonic()
        self.render()

    def set_idle(self) -> None:
        self.action_until = 0.0
        if self.form == "cat":
            self.visual_type, self.visual_name = "cat", "idle"
        elif self.activity_state == "reading":
            self.visual_type = "pose"
            self.visual_name = "read_full" if self.full_meal_state else "read"
        elif self.activity_state == "typing":
            meal_key = "full" if self.full_meal_state else "normal"
            self.visual_type, self.visual_name = "base", f"typing_{meal_key}"
        else:
            posture_key = "sit" if self.activity_state == "sitting" else "stand"
            meal_key = "full" if self.full_meal_state else "normal"
            state = f"{posture_key}_{meal_key}_idle"
            self.visual_type, self.visual_name = "base", state
        self.frame = self.frame_phase = 0
        self.render()

    def tick(self) -> None:
        if self.paused or self.closing:
            return
        now = time.monotonic()
        if self.action_until and now >= self.action_until:
            self.set_idle()
        if (
            self.form == "human"
            and self.activity_state in {"sitting", "standing"}
            and now >= self.next_blink
            and self.action_until <= now
        ):
            self.play_blink()
        if self.activity_state in {"sitting", "standing"} and now >= self.next_random_action and self.action_until <= now:
            self.random_action()
            self.next_random_action = now + random.uniform(28, 48)

        interval = FRAME_MS[self.visual_name] if self.visual_type == "base" else 150
        if (now - self.last_tick) * 1000 >= interval:
            self.last_tick = now
            if self.visual_type == "base":
                self.frame = (self.frame + 1) % ROWS[self.visual_name][1]
            else:
                self.frame_phase = (self.frame_phase + 1) % 4
            self.render()

    def random_action(self) -> None:
        if self.form == "cat":
            self.play_cat("shy", 1800)
            return
        action = random.choice(("dance", "read", "tea", "shy"))
        self.play_pose(action, random.randint(2400, 4200))

    def current_screen_geometry(self):
        center = QPoint(self.window_x + self.display_width // 2, self.window_y + self.display_height // 2)
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("No display available")
        return screen.availableGeometry()

    def clamp_position(self, x: int, y: int) -> tuple[int, int]:
        center = QPoint(x + self.display_width // 2, y + self.display_height // 2)
        screen = QGuiApplication.screenAt(center)
        if screen is None:
            screens = QGuiApplication.screens()
            screen = min(
                screens,
                key=lambda item: abs(item.availableGeometry().center().x() - center.x())
                + abs(item.availableGeometry().center().y() - center.y()),
            )
        bounds = screen.availableGeometry()
        max_x = max(bounds.left(), bounds.right() - self.display_width + 1)
        max_y = max(bounds.top(), bounds.bottom() - self.display_height + 1)
        return min(max(bounds.left(), x), max_x), min(max(bounds.top(), y), max_y)

    def move_pet(self, x: int, y: int) -> None:
        self.window_x, self.window_y = int(x), int(y)
        self.move(self.window_x, self.window_y)
        self.position_stats()

    def zone_at(self, y: int) -> str:
        ratio = y / max(1, self.display_height)
        if ratio < 0.38:
            return "head"
        if ratio > 0.80:
            return "feet"
        return "body"

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.press_zone = self.zone_at(round(event.position().y()))
        point = event.globalPosition().toPoint()
        self.drag_origin = (point.x(), point.y(), self.window_x, self.window_y)
        self.dragged = False
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self.drag_origin is not None:
            sx, sy, wx, wy = self.drag_origin
            point = event.globalPosition().toPoint()
            dx, dy = point.x() - sx, point.y() - sy
            if abs(dx) + abs(dy) > 4 and not self.dragged:
                self.dragged = True
                self.action_until = 0.0
                self.set_idle()
            self.move_pet(wx + dx, wy + dy)
            event.accept()
            return

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        was_dragged = self.dragged
        zone = self.press_zone
        self.drag_origin = None
        self.dragged = False
        if was_dragged:
            x, y = self.clamp_position(self.window_x, self.window_y)
            self.move_pet(x, y)
            self.set_idle()
            self.save_settings()
            return
        if zone == "head":
            if self.form == "cat":
                self.play_cat("shy", 1200)
            else:
                self.play_blink()
        elif zone == "body":
            self.play_pose("bow", 1200)
        else:
            self.play_base("jumping", 800)

    def wheelEvent(self, event) -> None:
        self.set_size(self.size_percent + (5 if event.angleDelta().y() > 0 else -5))

    def contextMenuEvent(self, event) -> None:
        self.menu.exec(event.globalPos())

    def transform(self, form: str) -> None:
        if form == self.form:
            return
        self.form = form
        self.frame_cache.clear()
        self.play_cat("shy", 1500) if form == "cat" else self.play_base("waving", 1500)
        self.save_settings()

    def sit_down(self) -> None:
        self.posture = "sitting"
        self.activity_state = "sitting"
        self.sitting_action.setChecked(True)
        self.set_idle()
        self.save_settings()

    def stand_up(self) -> None:
        self.posture = "standing"
        self.activity_state = "standing"
        self.standing_action.setChecked(True)
        self.set_idle()
        self.save_settings()

    def read_continuously(self) -> None:
        self.activity_state = "reading"
        self.reading_action.setChecked(True)
        self.set_idle()
        self.save_settings()

    def type_continuously(self) -> None:
        self.activity_state = "typing"
        self.typing_action.setChecked(True)
        self.set_idle()
        self.save_settings()

    def toggle_full_meal_state(self, checked: bool) -> None:
        self.full_meal_state = bool(checked)
        self.set_idle()
        self.save_settings()

    def on_stats_toggle(self) -> None:
        self.stats_enabled = {key: action.isChecked() for key, action in self.stats_actions.items()}
        self.update_stats()
        self.save_settings()

    def apply_stats_style(self) -> None:
        if self.stats_light_text:
            style = (
                "QLabel { background: rgba(12, 18, 30, 138); color: rgba(248, 250, 255, 248); "
                "border: 1px solid rgba(255, 255, 255, 54); "
                "font: 12px 'Cascadia Mono'; padding: 6px 8px; border-radius: 7px; }"
            )
        else:
            style = (
                "QLabel { background: rgba(255, 255, 255, 118); color: rgba(8, 10, 14, 245); "
                "border: 1px solid rgba(30, 35, 45, 42); "
                "font: 12px 'Cascadia Mono'; padding: 6px 8px; border-radius: 7px; }"
            )
        self.stats_window.setStyleSheet(style)

    def toggle_stats_light_mode(self, checked: bool) -> None:
        self.stats_light_text = bool(checked)
        self.apply_stats_style()
        self.stats_window.adjustSize()
        self.position_stats()
        self.save_settings()

    def toggle_pause(self) -> None:
        self.paused = not self.paused

    def open_size_dialog(self) -> None:
        dialog = QDialog(self, Qt.WindowType.WindowStaysOnTopHint)
        dialog.setWindowTitle("重设大小")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("桌宠大小：20%～100%"))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(20, 100)
        slider.setValue(self.size_percent)
        layout.addWidget(slider)
        buttons = QHBoxLayout()
        apply_button = QPushButton("应用")
        cancel_button = QPushButton("取消")
        apply_button.clicked.connect(lambda: (self.set_size(slider.value()), dialog.accept()))
        cancel_button.clicked.connect(dialog.reject)
        buttons.addWidget(apply_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)
        dialog.adjustSize()
        dialog.move(
            self.window_x + max(0, (self.display_width - dialog.width()) // 2),
            max(0, self.window_y - dialog.height() - 10),
        )
        dialog.exec()

    def set_size(self, percent: int) -> None:
        self.size_percent = min(100, max(20, int(percent)))
        self.frame_cache.clear()
        self.resize(self.display_width, self.display_height)
        x, y = self.clamp_position(self.window_x, self.window_y)
        self.move_pet(x, y)
        self.render()
        self.save_settings()

    def update_stats(self) -> None:
        lines = []
        if self.stats_enabled["cpu"]:
            lines.append(f"CPU   {psutil.cpu_percent(interval=None):5.1f}%")
        if self.stats_enabled["memory"]:
            lines.append(f"MEM   {psutil.virtual_memory().percent:5.1f}%")
        if self.stats_enabled["disk"]:
            root_drive = Path.home().anchor or "C:\\"
            lines.append(f"DISK  {psutil.disk_usage(root_drive).percent:5.1f}%")
        if self.stats_enabled["network"]:
            now = time.monotonic()
            net = psutil.net_io_counters()
            elapsed = max(0.1, now - self.last_net_time)
            down = (net.bytes_recv - self.last_net.bytes_recv) / elapsed / 1024.0
            up = (net.bytes_sent - self.last_net.bytes_sent) / elapsed / 1024.0
            online = any(
                stat.isup and name.lower() != "loopback"
                for name, stat in psutil.net_if_stats().items()
            )
            lines.append(f"NET   {'ON ' if online else 'OFF'} ↓{down:5.1f} ↑{up:5.1f} KB/s")
            self.last_net, self.last_net_time = net, now
        if lines:
            self.stats_window.setText("\n".join(lines))
            self.stats_window.adjustSize()
            self.position_stats()
            self.stats_window.show()
        else:
            self.stats_window.hide()

    def position_stats(self) -> None:
        if not any(self.stats_enabled.values()):
            return
        bounds = self.current_screen_geometry()
        bbox = self.current_source_frame().getchannel("A").getbbox()
        if bbox is None:
            return
        scale_x = self.display_width / SOURCE_W
        scale_y = self.display_height / SOURCE_H
        subject_left = self.window_x + round(bbox[0] * scale_x)
        subject_right = self.window_x + round(bbox[2] * scale_x)
        subject_top = self.window_y + round(bbox[1] * scale_y)
        gap = 4
        x = subject_right + gap
        if x + self.stats_window.width() > bounds.right() + 1:
            x = subject_left - self.stats_window.width() - gap
        y = min(
            max(bounds.top(), subject_top + 8),
            max(bounds.top(), bounds.bottom() - self.stats_window.height() + 1),
        )
        self.stats_window.move(max(bounds.left(), x), y)

    def animate_intro(self, step: int) -> None:
        steps = 22
        target_x, target_y = self.target_position
        bounds = self.current_screen_geometry()
        t = min(1.0, step / steps)
        eased = 1.0 - (1.0 - t) ** 3
        y = round((bounds.bottom() - 45) * (1.0 - eased) + target_y * eased)
        self.setWindowOpacity(0.25 + 0.75 * eased)
        self.move_pet(target_x, y)
        if step < steps:
            QTimer.singleShot(35, lambda: self.animate_intro(step + 1))
        else:
            self.setWindowOpacity(1.0)
            self.play_base("waving", 1500)

    def close_pet(self) -> None:
        if self.closing:
            return
        self.saved_position = (self.window_x, self.window_y)
        self.closing = True
        if self.form == "human":
            self.visual_type, self.visual_name = "base", "waving"
        else:
            self.visual_type, self.visual_name = "cat", "shy"
        self.frame = 0
        self.render()
        QTimer.singleShot(80, lambda: self.animate_outro(0))

    def animate_outro(self, step: int) -> None:
        steps = 20
        t = step / steps
        self.move_pet(self.window_x, self.window_y + 8)
        self.setWindowOpacity(max(0.05, 1.0 - t))
        if step < steps:
            QTimer.singleShot(45, lambda: self.animate_outro(step + 1))
        else:
            self.save_settings()
            self.stats_window.close()
            self.hide()
            QApplication.quit()

    def closeEvent(self, event) -> None:
        if self.closing:
            event.accept()
            return
        event.ignore()
        self.close_pet()

    def save_settings(self) -> None:
        x, y = self.saved_position if self.closing and self.saved_position else (self.window_x, self.window_y)
        data = {
            "x": x,
            "y": y,
            "size_percent": self.size_percent,
            "theme": self.theme,
            "form": self.form,
            "full_meal_state": self.full_meal_state,
            "stats_light_text": self.stats_light_text,
            "posture": self.posture,
            "activity_state": self.activity_state,
            "stats": self.stats_enabled,
        }
        try:
            settings_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass


def smoke_test() -> int:
    for theme in THEMES:
        atlas = Image.open(resource_path(f"assets/atlases/{theme}.png")).convert("RGBA")
        if atlas.size != (SOURCE_W * 6, SOURCE_H * len(ROWS)):
            print(f"bad atlas {theme}: {atlas.size}")
            return 1
        for state, (row, count) in ROWS.items():
            for frame in range(count):
                box = (frame * SOURCE_W, row * SOURCE_H, (frame + 1) * SOURCE_W, (row + 1) * SOURCE_H)
                if atlas.crop(box).getbbox() is None:
                    print(f"blank {theme}:{state}[{frame}]")
                    return 1
        for pose in POSES:
            if Image.open(resource_path(f"assets/poses/{theme}/{pose}.png")).convert("RGBA").getbbox() is None:
                print(f"blank pose {theme}:{pose}")
                return 1
        for name in ("idle", "shy"):
            if Image.open(resource_path(f"assets/cat/{theme}/{name}.png")).convert("RGBA").getbbox() is None:
                print(f"blank cat pose {theme}:{name}")
                return 1
    print("Yuli Deluxe Qt smoke test passed")
    return 0


def main() -> int:
    if "--smoke-test" in sys.argv:
        return smoke_test()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    pet = YuliDeluxeQt()
    if "--runtime-test" in sys.argv:
        QTimer.singleShot(20000, app.quit)
    code = app.exec()
    if "--runtime-test" in sys.argv:
        print("Yuli Deluxe Qt runtime test passed")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
