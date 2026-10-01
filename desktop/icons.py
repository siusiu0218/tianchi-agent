"""Local SVG assets; Lucide attribution is included beside the source files."""
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def svg_icon(name, color="#566177", brand=False):
    source = (Path(__file__).parent / "assets" / f"{name}.svg").read_text(encoding="utf-8")
    renderer = QSvgRenderer(QByteArray(source.replace("currentColor", color).encode()))
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if brand:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#5968d9"))
            painter.drawRoundedRect(QRectF(0, 0, size, size), size * .27, size * .27)
        inset = size * .22 if brand else 0
        renderer.render(painter, QRectF(inset, inset, size - 2 * inset, size - 2 * inset))
        painter.end()
        icon.addPixmap(pixmap)
    return icon
