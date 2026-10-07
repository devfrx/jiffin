"""The tray icon: Jiffin's glyph, with a dot for an alert not seen yet, and "!" while a browser's
address cannot be read or a pause badge while Jiffin is paused (#12, ADR-0010, ADR-0024). A
click opens the tray list; the right-click menu has the pause, Impostazioni and Esci (#43).

The icon follows the taskbar's theme, which can differ from the apps' one: a dark glyph on a
light taskbar, a white one on a dark taskbar. It is drawn here at the exact size Windows shows
it, with the Segoe Fluent Icons glyph the alerts show, and reaches the tray through an image
provider: each look and state has its own address, so a change loads a new picture.
"""

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import Property, QObject, QRect, QRectF, QSize, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
from PySide6.QtQml import QmlElement, QmlUncreatable, QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickImageProvider

from jiffin.core.alerts import AlertsView
from jiffin.core.reminders import Pause, RemindersView
from jiffin.ui import (
    catalog,  # noqa: F401  # Catalog, which Texts.qml reads
    win32,
)
from jiffin.ui.look import Look

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1

QML = Path(__file__).with_name("qml")
PROVIDER = "tray"
GLYPH = ""
"""Document, as on the alerts."""
ICON_FONT = "Segoe Fluent Icons"
INK = {False: "#1a1a1a", True: "#ffffff"}
"""The glyph, on a light and on a dark taskbar."""
CAUTION = {False: ("#9d5d00", "#ffffff"), True: ("#fce100", "#000000")}
"""The "!" badge and its mark, on a light and on a dark taskbar: WinUI's caution colour."""


class Corner(StrEnum):
    """What the bottom right of the icon shows. The pause wins over "!": while paused nothing
    is judged, and the list still says which browser it is."""

    NONE = "fine"
    WARNING = "warning"
    PAUSED = "paused"


def address(size: int, dark: bool, dot: str | None, corner: Corner) -> str:
    """Where the image provider draws the icon: "image://tray/20/dark/d8d8d8/warning"."""
    return "/".join(
        (
            f"image://{PROVIDER}",
            str(size),
            "dark" if dark else "light",
            dot.lstrip("#") if dot else "none",
            corner.value,
        )
    )


def draw(size: int, dark: bool, dot: str | None, corner: Corner) -> QImage:
    """The icon, `size` pixels square: the glyph, the dot at the top right in `dot`'s colour,
    and "!" or the pause at the bottom right. Each badge is cut out of the glyph with a clear
    ring, since the taskbar under it may be glass. Badges sit on whole pixels, which keeps them
    sharp at 16."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    glyph = QFont(ICON_FONT)
    glyph.setPixelSize(size)
    painter.setFont(glyph)
    painter.setPen(QColor(INK[dark]))
    painter.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, GLYPH)
    ring = max(1, round(size / 16))
    if dot:
        side = round(size * 0.4)
        _badge(painter, QRect(size - side, 0, side, side), ring, QColor(dot))
    side = round(size * 0.5)
    badge = QRect(size - side, size - side, side, side)
    if corner is Corner.WARNING:
        colour, mark = CAUTION[dark]
        _badge(painter, badge, ring, QColor(colour))
        # The "!": a bar and a dot, drawn, since a font is mush at this size.
        stroke = max(1, round(side / 8))
        left = badge.left() + (side - stroke) // 2
        bar = round(side * 0.4)
        top = badge.top() + round(side * 0.2)
        painter.fillRect(QRect(left, top, stroke, bar), QColor(mark))
        painter.fillRect(QRect(left, top + bar + stroke, stroke, stroke), QColor(mark))
    elif corner is Corner.PAUSED:
        # Two bars on a disc in the glyph's ink, as OneDrive shows its pause: the owner chose it
        # on live variants (#105).
        _badge(painter, badge, ring, QColor(INK[dark]))
        stroke = max(1, round(side / 5))
        bar = round(side * 0.5)
        left = badge.left() + (side - 3 * stroke) // 2
        top = badge.top() + (side - bar) // 2
        painter.fillRect(QRect(left, top, stroke, bar), QColor(INK[not dark]))
        painter.fillRect(QRect(left + 2 * stroke, top, stroke, bar), QColor(INK[not dark]))
    painter.end()
    return image


def _badge(painter: QPainter, rect: QRect, ring: int, colour: QColor) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    # The clear ring needs a brush too: with none, as before the first badge, nothing is cut.
    painter.setBrush(colour)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    painter.drawEllipse(rect.adjusted(-ring, -ring, ring, ring))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.drawEllipse(rect)


class Icons(QQuickImageProvider):
    """Draws the icon an address names; the address holds all it needs."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, id: str, size: QSize, requestedSize: QSize) -> QImage:
        side, theme, dot, corner = id.split("/")
        image = draw(
            int(side), theme == "dark", None if dot == "none" else f"#{dot}", Corner(corner)
        )
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image


@QmlElement
@QmlUncreatable("The interface makes it.")
class Tray(QObject):  # type: ignore[operator]  # QmlUncreatable's stub has no __call__
    """Lives on the interface thread; the `show_` methods take what `core` and the context
    capture say."""

    changed = Signal()

    def __init__(
        self,
        engine: QQmlEngine,
        look: Look,
        on_click: Callable[[], None],
        on_settings: Callable[[], None],
        on_pause: Callable[[Pause], None],
        on_resume: Callable[[], None],
    ) -> None:
        # The engine owns this object, as the creation window's: the icon's bindings never
        # read it gone.
        super().__init__(engine)
        engine.addImageProvider(PROVIDER, Icons())
        self._engine = engine
        self._look = look
        self._on_click = on_click
        self._on_settings = on_settings
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._dot = False
        self._warning = False
        self._paused = False
        self._icon: QObject | None = None
        look.changed.connect(self.changed)

    def install(self) -> None:
        """Put the icon in the tray. Only Windows has a tray among Qt's platforms here: the
        offscreen one of the tests has none, and says so loudly."""
        # The menu is Windows' own, light unless asked for dark.
        win32.follow_dark_menus()
        self._look.changed.connect(win32.follow_dark_menus)
        component = QQmlComponent(self._engine, QUrl.fromLocalFile(QML / "TrayIcon.qml"))
        if component.isError():
            raise RuntimeError(component.errorString())
        icon = component.createWithInitialProperties({"tray": self})
        if icon is None:
            raise TypeError(f"no tray icon: {component.errorString()}")
        icon.setParent(self)
        self._icon = icon

    @Slot(object)
    def show_alerts(self, view: AlertsView) -> None:
        if view.dot != self._dot:
            self._dot = view.dot
            self.changed.emit()

    @Slot(object)
    def show_unreadable(self, apps: frozenset[str]) -> None:
        if bool(apps) != self._warning:
            self._warning = bool(apps)
            self.changed.emit()

    @Slot(object)
    def show_reminders(self, view: RemindersView) -> None:
        """Whether Jiffin is paused: the menu offers Riprendi instead, and the icon shows it."""
        if (view.paused_until is not None) != self._paused:
            self._paused = view.paused_until is not None
            self.changed.emit()

    @Property(str, notify=changed)
    def icon(self) -> str:
        settings = self._look.settings
        dot = settings.taskbar_accent if self._dot else None
        corner = Corner.PAUSED if self._paused else Corner.WARNING if self._warning else Corner.NONE
        return address(win32.small_icon_size(), settings.taskbar_dark, dot, corner)

    @Property(bool, notify=changed)
    def paused(self) -> bool:
        return self._paused

    @Slot()
    def click(self) -> None:
        self._on_click()

    @Slot()
    def settings(self) -> None:
        self._on_settings()

    @Slot()
    def pauseHour(self) -> None:
        self._on_pause(Pause.HOUR)

    @Slot()
    def pauseTomorrow(self) -> None:
        self._on_pause(Pause.TOMORROW)

    @Slot()
    def resume(self) -> None:
        self._on_resume()

    @Slot()
    def quit(self) -> None:
        QGuiApplication.quit()
