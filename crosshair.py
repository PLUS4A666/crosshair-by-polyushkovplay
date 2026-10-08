"""Прицел поверх игры.

Запуск: pip install PyQt5 && python crosshair.py

Игра должна быть в оконном или безрамочном режиме. Исключительный
полноэкранный режим рисует поверх всех обычных окон, и прицел туда не попадёт.
Если игра запущена от имени администратора, этот скрипт тоже нужно запустить
от администратора — иначе Windows не даст окну остаться сверху.

В OBS прицел берётся отдельным источником «Браузер» (адрес печатается в окне
настроек). Захват всего экрана для этого не нужен: игру добавляйте своим
источником «Захват игры», прицел ляжет поверх в сцене.
"""

import json
import os
import sys
import ctypes
import threading
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

user32 = ctypes.windll.user32

# До создания QApplication, иначе на масштабе 125/150% прицел уезжает и мылится.
def enable_dpi_awareness():
    try:
        set_context = user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = wintypes.BOOL
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if set_context(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        set_awareness = ctypes.windll.shcore.SetProcessDpiAwareness
        set_awareness.argtypes = [ctypes.c_int]
        set_awareness.restype = ctypes.c_int
        set_awareness(2)
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


try:
    from PyQt5.QtCore import Qt, QTimer, QPointF, QLineF, pyqtSignal
    from PyQt5.QtGui import QPainter, QColor, QPen, QIcon, QPixmap
    from PyQt5.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QLabel, QSlider, QComboBox,
        QPushButton, QColorDialog, QSystemTrayIcon, QMenu, QAction, QCheckBox,
    )
except ImportError:
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user32.MessageBoxW.restype = ctypes.c_int
    user32.MessageBoxW(
        0,
        "Не установлен PyQt5.\n\nВыполните в консоли:\npython -m pip install PyQt5\n\nи запустите скрипт снова.",
        "Прицел",
        0x10,
    )
    raise SystemExit(1)


VK_RBUTTON = 0x02
VK_F6 = 0x75
VK_F7 = 0x76
VK_F8 = 0x77

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
OVERLAY_EXSTYLE = (
    WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
)

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
HWND_TOPMOST = -1

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetForegroundWindow.restype = wintypes.HWND
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

_SHELL_CLASSES = {
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
}
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL

if ctypes.sizeof(ctypes.c_void_p) == 8:
    _get_exstyle = user32.GetWindowLongPtrW
    _set_exstyle = user32.SetWindowLongPtrW
    _long_ptr = ctypes.c_ssize_t
else:
    _get_exstyle = user32.GetWindowLongW
    _set_exstyle = user32.SetWindowLongW
    _long_ptr = ctypes.c_long

_get_exstyle.argtypes = [wintypes.HWND, ctypes.c_int]
_get_exstyle.restype = _long_ptr
_set_exstyle.argtypes = [wintypes.HWND, ctypes.c_int, _long_ptr]
_set_exstyle.restype = _long_ptr


def key_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


_SHAPES = ("Круг", "Перекрестие")


def _settings_path():
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "Прицел" / "settings.json"


def _default_settings():
    return {
        "shape": "Круг",
        "size": 6,
        "alpha": 230,
        "color": "#00ff00",
        "hide_on_aim": True,
    }


def _as_int(value, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if low <= number <= high:
        return number
    return None


def load_settings():
    data = _default_settings()
    try:
        raw = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return data
    if not isinstance(raw, dict):
        return data

    if raw.get("shape") in _SHAPES:
        data["shape"] = raw["shape"]
    size = _as_int(raw.get("size"), 2, 40)
    if size is not None:
        data["size"] = size
    alpha = _as_int(raw.get("alpha"), 20, 255)
    if alpha is not None:
        data["alpha"] = alpha
    color = QColor(str(raw.get("color", "")))
    if color.isValid():
        data["color"] = color.name()
    if isinstance(raw.get("hide_on_aim"), bool):
        data["hide_on_aim"] = raw["hide_on_aim"]
    return data


def save_settings(overlay):
    payload = {
        "shape": overlay.shape_type if overlay.shape_type in _SHAPES else "Круг",
        "size": int(overlay.dot_size),
        "alpha": int(overlay.alpha),
        "color": QColor(overlay.color).name(),
        "hide_on_aim": bool(overlay.hide_on_aim),
    }
    path = _settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        return


def _hwnd_of(widget):
    value = widget.winId()
    return int(value) if value else 0


def apply_overlay_style(hwnd):
    """Клики проходят сквозь прицел, фокус не крадётся, окно держится сверху игры."""
    if not hwnd:
        return
    handle = wintypes.HWND(hwnd)
    current = int(_get_exstyle(handle, GWL_EXSTYLE)) & 0xFFFFFFFF
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    if (current & OVERLAY_EXSTYLE) != OVERLAY_EXSTYLE:
        _set_exstyle(handle, GWL_EXSTYLE, current | OVERLAY_EXSTYLE)
        flags |= SWP_FRAMECHANGED
    user32.SetWindowPos(handle, wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, flags)


def _screen_for_point(px, py):
    """Монитор, чей центр ближе всего к точке. Координаты точки — пиксели Windows."""
    best = None
    best_dist = None
    for screen in QApplication.screens():
        geo = screen.geometry()
        dpr = screen.devicePixelRatio() or 1.0
        cx = geo.x() * dpr + geo.width() * dpr / 2.0
        cy = geo.y() * dpr + geo.height() * dpr / 2.0
        dist = (cx - px) ** 2 + (cy - py) ** 2
        if best_dist is None or dist < best_dist:
            best = screen
            best_dist = dist
    return best


_OBS_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body { margin: 0; background: transparent; overflow: hidden; }
  canvas { display: block; width: 100vw; height: 100vh; }
</style>
</head>
<body>
<canvas id="c"></canvas>
<script>
const canvas = document.getElementById("c");
const ctx = canvas.getContext("2d");
function resize() {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(window.innerWidth * dpr);
  canvas.height = Math.round(window.innerHeight * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener("resize", resize);
resize();
let state = null;
function draw() {
  const dpr = window.devicePixelRatio || 1;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const w = window.innerWidth;
  const h = window.innerHeight;
  ctx.clearRect(0, 0, w, h);
  if (!state || !state.visible) return;
  const cx = w / 2;
  const cy = h / 2;
  ctx.translate(cx, cy);
  ctx.scale(2, 2);
  ctx.translate(-cx, -cy);
  ctx.globalAlpha = (state.alpha || 255) / 255;
  ctx.fillStyle = state.color || "#00ff00";
  ctx.strokeStyle = state.color || "#00ff00";
  if (state.shape === "Круг") {
    ctx.beginPath();
    ctx.arc(cx, cy, (state.size || 6) / 2, 0, Math.PI * 2);
    ctx.fill();
  } else {
    const radius = state.size || 6;
    let gap = Math.min(4, radius * 0.35);
    if (gap < 1.5) gap = 0;
    ctx.lineWidth = radius >= 8 ? 2 : 1;
    ctx.lineCap = "butt";
    ctx.beginPath();
    ctx.moveTo(cx - radius, cy); ctx.lineTo(cx - gap, cy);
    ctx.moveTo(cx + gap, cy); ctx.lineTo(cx + radius, cy);
    ctx.moveTo(cx, cy - radius); ctx.lineTo(cx, cy - gap);
    ctx.moveTo(cx, cy + gap); ctx.lineTo(cx, cy + radius);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}
async function poll() {
  try {
    const response = await fetch("/state", { cache: "no-store" });
    state = await response.json();
    draw();
  } catch (e) {}
}
setInterval(poll, 50);
poll();
</script>
</body>
</html>
"""


class _ObsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/state":
            body = json.dumps(self.server.bridge.snapshot(), ensure_ascii=False).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        elif path in ("/", "/crosshair.html"):
            body = _OBS_PAGE.encode("utf-8")
            content_type = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        return


class ObsBrowserBridge:
    """Локальная страница с тем же прицелом. OBS берёт её источником «Браузер»."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {
            "shape": "Круг",
            "size": 6,
            "alpha": 230,
            "color": "#00ff00",
            "visible": True,
        }
        self.url = ""
        self._httpd = None

    def update(self, **fields):
        with self._lock:
            self._state.update(fields)

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def start(self):
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _ObsHandler)
        self._httpd.bridge = self
        port = self._httpd.server_address[1]
        self.url = f"http://127.0.0.1:{port}/"
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()


class CrosshairOverlay(QWidget):
    status_changed = pyqtSignal(str)
    hide_on_aim_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        saved = load_settings()
        self.shape_type = saved["shape"]
        self.dot_size = saved["size"]
        self.color = QColor(saved["color"])
        self.alpha = saved["alpha"]

        self.user_enabled = True
        self.hide_on_aim = saved["hide_on_aim"]
        self._remember = False
        self.rmb_held = key_down(VK_RBUTTON)
        self._drawing = self._should_draw()
        self._status = self.status_text()
        self._ignored_widgets = []
        self._key_prev = {
            VK_F6: key_down(VK_F6),
            VK_F7: key_down(VK_F7),
            VK_F8: key_down(VK_F8),
        }
        self._tick = 0
        self._screen = None

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | getattr(Qt, "WindowTransparentForInput", 0)
            | getattr(Qt, "WindowDoesNotAcceptFocus", 0)
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWindowTitle("Прицел")

        self._relayout()
        self._remember = True

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    def _remember_settings(self):
        if self._remember:
            save_settings(self)

    def ignore_widget(self, widget):
        self._ignored_widgets.append(widget)

    def _own_hwnds(self):
        handles = {_hwnd_of(self)}
        for widget in self._ignored_widgets:
            handles.add(_hwnd_of(widget))
        handles.discard(0)
        return handles

    def _should_draw(self):
        if not self.user_enabled:
            return False
        if self.hide_on_aim and self.rmb_held:
            return False
        return True

    def status_text(self):
        if not self.user_enabled:
            return "Прицел выключен (F6)"
        if not self.hide_on_aim:
            return "Скрытие по ПКМ выключено"
        if self.rmb_held:
            return "ПКМ зажата — прицел скрыт"
        return "Прицел показан"

    def _canvas_size(self):
        margin = 8
        if self.shape_type == "Перекрестие":
            return self.dot_size * 2 + margin * 2
        return self.dot_size + margin * 2

    def _target_screen(self):
        screen = self._screen or QApplication.primaryScreen()
        raw = user32.GetForegroundWindow()
        if not raw:
            return screen
        hwnd = int(raw)
        handle = wintypes.HWND(hwnd)
        if hwnd in self._own_hwnds() or user32.IsIconic(handle):
            return screen

        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(handle, class_name, 256)
        if class_name.value in _SHELL_CLASSES:
            return screen

        rect = wintypes.RECT()
        if not user32.GetWindowRect(handle, ctypes.byref(rect)):
            return screen
        if rect.right - rect.left < 640 or rect.bottom - rect.top < 480:
            return screen

        found = _screen_for_point(
            (rect.left + rect.right) / 2.0,
            (rect.top + rect.bottom) / 2.0,
        )
        if found is not None:
            self._screen = found
            return found
        return screen

    def _relayout(self):
        screen = self._target_screen()
        if screen is None:
            return
        geo = screen.geometry()
        size = self._canvas_size()
        x = int(round(geo.x() + (geo.width() - size) / 2.0))
        y = int(round(geo.y() + (geo.height() - size) / 2.0))
        if (self.x(), self.y(), self.width(), self.height()) != (x, y, size, size):
            self.setGeometry(x, y, size, size)
            if self.isVisible():
                apply_overlay_style(_hwnd_of(self))

    def showEvent(self, event):
        super().showEvent(event)
        apply_overlay_style(_hwnd_of(self))
        QTimer.singleShot(0, lambda: apply_overlay_style(_hwnd_of(self)))

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            # Иначе прошлый кадр остаётся на прозрачном окне, когда прицел прячется.
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
            if not self._drawing:
                return

            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setRenderHint(QPainter.Antialiasing, True)

            draw_color = QColor(self.color)
            draw_color.setAlpha(self.alpha)
            cx = self.width() / 2.0
            cy = self.height() / 2.0

            if self.shape_type == "Круг":
                painter.setPen(Qt.NoPen)
                painter.setBrush(draw_color)
                painter.drawEllipse(QPointF(cx, cy), self.dot_size / 2.0, self.dot_size / 2.0)
                return

            radius = float(self.dot_size)
            gap = min(4.0, radius * 0.35)
            if gap < 1.5:
                gap = 0.0
            pen_width = 2 if self.dot_size >= 8 else 1
            pen = QPen(draw_color, pen_width)
            pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            painter.drawLine(QLineF(cx - radius, cy, cx - gap, cy))
            painter.drawLine(QLineF(cx + gap, cy, cx + radius, cy))
            painter.drawLine(QLineF(cx, cy - radius, cx, cy - gap))
            painter.drawLine(QLineF(cx, cy + gap, cx, cy + radius))
        finally:
            painter.end()

    def _refresh_visual(self):
        drawing = self._should_draw()
        status = self.status_text()
        if drawing != self._drawing:
            self._drawing = drawing
            self.update()
        if status != self._status:
            self._status = status
            self.status_changed.emit(status)

        if self.user_enabled:
            if not self.isVisible():
                self.show()
                apply_overlay_style(_hwnd_of(self))
        elif self.isVisible():
            self.hide()
        self._push_obs()

    def _push_obs(self):
        bridge = getattr(self, "obs_bridge", None)
        if bridge is None:
            return
        bridge.update(
            shape=self.shape_type,
            size=int(self.dot_size),
            alpha=int(self.alpha),
            color=QColor(self.color).name(),
            visible=bool(self._drawing),
        )

    def set_enabled(self, enabled):
        self.user_enabled = bool(enabled)
        self._refresh_visual()

    def toggle(self):
        self.set_enabled(not self.user_enabled)

    def set_hide_on_aim(self, enabled):
        enabled = bool(enabled)
        if enabled == self.hide_on_aim:
            return
        self.hide_on_aim = enabled
        self.hide_on_aim_changed.emit(enabled)
        self._refresh_visual()
        self._remember_settings()

    def toggle_hide_on_aim(self):
        self.set_hide_on_aim(not self.hide_on_aim)

    def _poll(self):
        self.rmb_held = key_down(VK_RBUTTON)
        self._edge(VK_F6, self.toggle)
        self._edge(VK_F7, self._toggle_settings)
        self._edge(VK_F8, self.toggle_hide_on_aim)
        self._refresh_visual()

        self._tick += 1
        if self.isVisible() and self._tick % 3 == 0:
            apply_overlay_style(_hwnd_of(self))
        if self._tick % 12 == 0:
            self._relayout()

    def _edge(self, vk, handler):
        down = key_down(vk)
        if down and not self._key_prev.get(vk, False):
            handler()
        self._key_prev[vk] = down

    def _toggle_settings(self):
        callback = getattr(self, "on_toggle_settings", None)
        if callback is not None:
            callback()

    def set_shape(self, name):
        if name not in _SHAPES or name == self.shape_type:
            return
        self.shape_type = name
        self._relayout()
        self.update()
        self._remember_settings()

    def set_size(self, value):
        value = _as_int(value, 2, 40)
        if value is None or value == self.dot_size:
            return
        self.dot_size = value
        self._relayout()
        self.update()
        self._remember_settings()

    def set_alpha(self, value):
        value = _as_int(value, 20, 255)
        if value is None or value == self.alpha:
            return
        self.alpha = value
        self.update()
        self._remember_settings()

    def set_color(self, color):
        color = QColor(color)
        if not color.isValid() or color.name() == self.color.name():
            return
        self.color = color
        self.update()
        self._remember_settings()


class SettingsWindow(QWidget):
    def __init__(self, overlay: CrosshairOverlay, obs_url=""):
        super().__init__()
        self.overlay = overlay
        self._obs_url = obs_url
        self._force_close = False
        self._build()

    def _build(self):
        self.setWindowTitle("Настройки прицела")
        self.setFixedWidth(340)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout()

        layout.addWidget(QLabel("Тип прицела:"))
        self.combo_type = QComboBox()
        self.combo_type.addItems(list(_SHAPES))
        shape_index = self.combo_type.findText(self.overlay.shape_type)
        if shape_index >= 0:
            self.combo_type.setCurrentIndex(shape_index)
        self.combo_type.currentTextChanged.connect(self.overlay.set_shape)
        layout.addWidget(self.combo_type)

        self.label_size = QLabel(f"Размер: {self.overlay.dot_size}px")
        layout.addWidget(self.label_size)
        self.slider_size = QSlider(Qt.Horizontal)
        self.slider_size.setRange(2, 40)
        self.slider_size.setValue(self.overlay.dot_size)
        self.slider_size.valueChanged.connect(self._change_size)
        layout.addWidget(self.slider_size)

        self.label_alpha = QLabel(self._alpha_text(self.overlay.alpha))
        layout.addWidget(self.label_alpha)
        self.slider_alpha = QSlider(Qt.Horizontal)
        self.slider_alpha.setRange(20, 255)
        self.slider_alpha.setValue(self.overlay.alpha)
        self.slider_alpha.valueChanged.connect(self._change_alpha)
        layout.addWidget(self.slider_alpha)

        self.btn_color = QPushButton("Выбрать цвет")
        self.btn_color.clicked.connect(self._choose_color)
        layout.addWidget(self.btn_color)
        self._paint_color_button()

        self.chk_aim = QCheckBox("Скрывать прицел, пока зажата ПКМ")
        self.chk_aim.setChecked(self.overlay.hide_on_aim)
        self.chk_aim.setToolTip(
            "Пока правая кнопка мыши зажата, нарисованный прицел пропадает. "
            "Отпустили — появляется снова. Свой прицел игры при этом не трогается."
        )
        self.chk_aim.toggled.connect(self.overlay.set_hide_on_aim)
        layout.addWidget(self.chk_aim)

        self.status_label = QLabel(self.overlay.status_text())
        self.status_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.status_label)

        hint = QLabel(
            "F6 — показать или скрыть прицел\n"
            "F7 — это окно\n"
            "F8 — скрытие по ПКМ вкл/выкл\n"
            "Настройки запоминаются между запусками\n"
            "Игра: оконный или безрамочный режим"
        )
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        if self._obs_url:
            obs = QLabel(
                "OBS: источник «Браузер», размер 200×200, по центру сцены.\n"
                "Игру захватывайте отдельно. Экран целиком не нужен.\n"
                + self._obs_url
            )
            obs.setWordWrap(True)
            obs.setTextInteractionFlags(Qt.TextSelectableByMouse)
            obs.setStyleSheet("color: gray; font-size: 11px;")
            layout.addWidget(obs)
            copy_obs = QPushButton("Копировать адрес для OBS")
            copy_obs.clicked.connect(self._copy_obs_url)
            layout.addWidget(copy_obs)

        self.setLayout(layout)
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height() + 8)

        self.overlay.status_changed.connect(self.status_label.setText)
        self.overlay.hide_on_aim_changed.connect(self._sync_aim_checkbox)

    def showEvent(self, event):
        super().showEvent(event)
        user32.SetWindowPos(
            wintypes.HWND(_hwnd_of(self)),
            wintypes.HWND(HWND_TOPMOST),
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE,
        )

    def _sync_aim_checkbox(self, enabled):
        self.chk_aim.blockSignals(True)
        self.chk_aim.setChecked(enabled)
        self.chk_aim.blockSignals(False)

    def _alpha_text(self, value):
        return f"Непрозрачность: {int(round(value / 255 * 100))}%"

    def _change_size(self, value):
        self.overlay.set_size(value)
        self.label_size.setText(f"Размер: {value}px")

    def _change_alpha(self, value):
        self.overlay.set_alpha(value)
        self.label_alpha.setText(self._alpha_text(value))

    def _paint_color_button(self):
        color = self.overlay.color
        text = "#000000" if color.lightness() > 140 else "#ffffff"
        self.btn_color.setStyleSheet(f"background-color: {color.name()}; color: {text};")

    def _choose_color(self):
        color = QColorDialog.getColor(self.overlay.color, self, "Выберите цвет прицела")
        if color.isValid():
            self.overlay.set_color(color)
            self._paint_color_button()

    def _copy_obs_url(self):
        QApplication.clipboard().setText(self._obs_url)

    def toggle_settings(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event):
        if self._force_close:
            event.accept()
            return
        event.ignore()
        self.hide()


def _build_tray_icon():
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 255, 0))
    painter.drawEllipse(1, 1, 14, 14)
    painter.end()
    return QIcon(pixmap)


def main():
    enable_dpi_awareness()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Прицел")

    overlay = CrosshairOverlay()
    obs_bridge = ObsBrowserBridge()
    overlay.obs_bridge = obs_bridge
    overlay._push_obs()
    obs_bridge.start()
    app.aboutToQuit.connect(lambda: save_settings(overlay))
    settings = SettingsWindow(overlay, obs_bridge.url)
    overlay.ignore_widget(settings)
    overlay.on_toggle_settings = settings.toggle_settings

    overlay.show()
    apply_overlay_style(_hwnd_of(overlay))
    settings.show()
    overlay._timer.start(16)

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(_build_tray_icon(), app)
        tray.setToolTip("Прицел")
        menu = QMenu()

        action_settings = QAction("Настройки", app)
        action_settings.triggered.connect(settings.show)
        menu.addAction(action_settings)

        action_aim = QAction("Скрывать при ПКМ", app)
        action_aim.setCheckable(True)
        action_aim.setChecked(overlay.hide_on_aim)
        action_aim.toggled.connect(overlay.set_hide_on_aim)

        def sync_tray(enabled):
            action_aim.blockSignals(True)
            action_aim.setChecked(enabled)
            action_aim.blockSignals(False)

        overlay.hide_on_aim_changed.connect(sync_tray)
        menu.addAction(action_aim)

        action_quit = QAction("Выход", app)

        def quit_app():
            settings._force_close = True
            app.quit()

        action_quit.triggered.connect(quit_app)
        menu.addAction(action_quit)

        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: settings.toggle_settings()
            if reason == QSystemTrayIcon.Trigger
            else None
        )
        tray.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
