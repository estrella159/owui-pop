"""Light, dark, or whatever the desktop uses, and a font size, applied to the whole app."""
from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import QApplication, QStyleFactory

_system: dict = {}

_COLORS = {
    "light": {"window": "#f7f7f8", "base": "#ffffff", "text": "#1d1d1f", "muted": "#6e6e73", "line": "#d9d9de",
              "button": "#ececef", "highlight": "#6d28d9", "highlight_text": "#ffffff", "link": "#5b21b6"},
    "dark": {"window": "#1f1f22", "base": "#18181b", "text": "#ececf1", "muted": "#9a9aa3", "line": "#36363c",
             "button": "#2b2b30", "highlight": "#8b5cf6", "highlight_text": "#ffffff", "link": "#c4b5fd"},
}


def _palette(c: dict) -> QPalette:
    p = QPalette()
    R = QPalette.ColorRole
    for role, key in ((R.Window, "window"), (R.Base, "base"), (R.AlternateBase, "window"), (R.Text, "text"),
                      (R.WindowText, "text"), (R.Button, "button"), (R.ButtonText, "text"), (R.ToolTipBase, "base"),
                      (R.ToolTipText, "text"), (R.Highlight, "highlight"), (R.HighlightedText, "highlight_text"),
                      (R.Link, "link"), (R.PlaceholderText, "muted"), (R.Mid, "line"), (R.Midlight, "line"),
                      (R.Dark, "line")):
        p.setColor(role, QColor(c[key]))
    for role in (R.Text, R.WindowText, R.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["muted"]))
    return p


def apply(app: QApplication, theme: str, font_scale: float) -> None:
    if not _system:  # what the desktop gave us, to go back to
        _system.update(style=app.style().name(), palette=QPalette(app.palette()), font=QFont(app.font()))
    if theme in _COLORS:
        app.setStyle(QStyleFactory.create("Fusion"))
        app.setPalette(_palette(_COLORS[theme]))
    else:
        app.setStyle(QStyleFactory.create(_system["style"]) or app.style())
        app.setPalette(_system["palette"])
    f = QFont(_system["font"])
    if f.pointSizeF() > 0:
        f.setPointSizeF(f.pointSizeF() * font_scale)
    app.setFont(f)
