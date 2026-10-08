import sys
import keyboard
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QPainter, QColor, QPen, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSlider, QComboBox, QPushButton, QColorDialog, QSystemTrayIcon,
    QMenu, QAction
)

class KeyEmitter(QObject):
    toggle_overlay = pyqtSignal()
    toggle_settings = pyqtSignal()


class CrosshairOverlay(QWidget):
    def __init__(self):
        super().__init__()
        self.shape_type = "Круг"
        self.dot_size = 6
        self.color = QColor(0, 255, 0)
        self.alpha = 230

        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.Tool |
            Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.update_geometry()

    def update_geometry(self):
        screen = QApplication.primaryScreen().geometry()
        # Холст чуть больше самого элемента, чтобы перекрестие не обрезалось
        canvas_size = max(self.dot_size * 2, 40)
        x = (screen.width() - canvas_size) // 2
        y = (screen.height() - canvas_size) // 2
        self.setGeometry(x, y, canvas_size, canvas_size)
        self.canvas_size = canvas_size
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        draw_color = QColor(self.color)
        draw_color.setAlpha(self.alpha)

        cx = self.canvas_size / 2.0
        cy = self.canvas_size / 2.0

        if self.shape_type == "Круг":
            painter.setBrush(draw_color)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(int(cx - self.dot_size / 2),
                               int(cy - self.dot_size / 2),
                               self.dot_size, self.dot_size)

        elif self.shape_type == "Перекрестие":
            pen = QPen(draw_color, 2)
            painter.setPen(pen)
            r = self.dot_size
            gap = 3
            # Горизонтальная линия с зазором в центре
            painter.drawLine(int(cx - r), int(cy), int(cx - gap), int(cy))
            painter.drawLine(int(cx + gap), int(cy), int(cx + r), int(cy))
            # Вертикальная линия с зазором в центре
            painter.drawLine(int(cx), int(cy - r), int(cx), int(cy - gap))
            painter.drawLine(int(cx), int(cy + gap), int(cx), int(cy + r))

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()


class SettingsWindow(QWidget):
    def __init__(self, overlay: CrosshairOverlay):
        super().__init__()
        self.overlay = overlay
        self.init_ui()

        # Задаем окну имя, чтобы OBS мог найти его в списке окон
        self.setWindowTitle("CrosshairOverlayWindow")

        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            # УБРАТЬ: Qt.Tool  <-- OBS часто игнорирует окна типа Tool
            Qt.WindowTransparentForInput
        )

    def init_ui(self):
        self.setWindowTitle("Настройки прицела")
        self.setFixedSize(300, 260)
        self.setWindowFlags(Qt.WindowStaysOnTopHint)

        layout = QVBoxLayout()

        # Форма
        layout.addWidget(QLabel("Тип прицела:"))
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Круг", "Перекрестие"])
        self.combo_type.currentTextChanged.connect(self.change_shape)
        layout.addWidget(self.combo_type)

        # Размер
        self.label_size = QLabel(f"Размер: {self.overlay.dot_size}px")
        layout.addWidget(self.label_size)
        self.slider_size = QSlider(Qt.Horizontal)
        self.slider_size.setRange(2, 40)
        self.slider_size.setValue(self.overlay.dot_size)
        self.slider_size.valueChanged.connect(self.change_size)
        layout.addWidget(self.slider_size)

        # Прозрачность
        self.label_alpha = QLabel(f"Прозрачность: {int((self.overlay.alpha / 255) * 100)}%")
        layout.addWidget(self.label_alpha)
        self.slider_alpha = QSlider(Qt.Horizontal)
        self.slider_alpha.setRange(20, 255)
        self.slider_alpha.setValue(self.overlay.alpha)
        self.slider_alpha.valueChanged.connect(self.change_alpha)
        layout.addWidget(self.slider_alpha)

        # Цвет
        self.btn_color = QPushButton("Выбрать цвет")
        self.btn_color.clicked.connect(self.choose_color)
        layout.addWidget(self.btn_color)

        # Подсказка
        hint = QLabel("Хоткеи:\n[F6] Вкл/Выкл точку\n[F7] Меню настроек")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(hint)

        self.setLayout(layout)

    def change_shape(self, text):
        self.overlay.shape_type = text
        self.overlay.update()

    def change_size(self, val):
        self.overlay.dot_size = val
        self.label_size.setText(f"Размер: {val}px")
        self.overlay.update_geometry()

    def change_alpha(self, val):
        self.overlay.alpha = val
        self.label_alpha.setText(f"Прозрачность: {int((val / 255) * 100)}%")
        self.overlay.update()

    def choose_color(self):
        color = QColorDialog.getColor(self.overlay.color, self, "Выберите цвет точки")
        if color.isValid():
            self.overlay.color = color
            self.overlay.update()

    def closeEvent(self, event):
        # При закрытии окна крестиком оно прячется, а не убивает приложение
        event.ignore()
        self.hide()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    overlay = CrosshairOverlay()
    overlay.show()

    settings = SettingsWindow(overlay)
    settings.show()

    # Иконка в системном трее
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setBrush(QColor(0, 255, 0))
    painter.drawEllipse(0, 0, 15, 15)
    painter.end()

    tray_icon = QSystemTrayIcon(QIcon(pixmap), app)
    tray_menu = QMenu()

    action_settings = QAction("Настройки", app)
    action_settings.triggered.connect(settings.show)
    tray_menu.addAction(action_settings)

    action_quit = QAction("Выход", app)
    action_quit.triggered.connect(app.quit)
    tray_menu.addAction(action_quit)

    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()

    # Привязка горячих клавиш
    emitter = KeyEmitter()
    emitter.toggle_overlay.connect(overlay.toggle)
    emitter.toggle_settings.connect(
        lambda: settings.hide() if settings.isVisible() else (settings.show(), settings.activateWindow())
    )

    keyboard.add_hotkey('f6', lambda: emitter.toggle_overlay.emit())
    keyboard.add_hotkey('f7', lambda: emitter.toggle_settings.emit())

    sys.exit(app.exec_())

if __name__ == '__main__':
    main()