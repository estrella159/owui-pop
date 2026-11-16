"""Where the pop-up appears.

On X11 the app moves its own window. On Wayland an app may not place its windows; the compositor
does. On KDE Plasma the pop-up therefore writes one KWin window rule for its own window class
(``owui-pop``) and asks KWin to reload; it never touches any other rule. Other Wayland desktops place
it themselves, and Settings says so.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import QWidget

POSITIONS = {
    "desktop": "Let the desktop decide",
    "center": "Centre of the screen",
    "top": "Top centre",
    "mouse": "Under the mouse pointer",
    "remember": "Where I last left it",
}
RULE = "owui-pop-position"
APP_ID = "owui-pop"
#: KWin rule values: placement policies and how a rule applies
_CENTERED, _UNDER_MOUSE = 5, 7
_FORCE, _APPLY_INITIALLY, _REMEMBER = 2, 3, 4


def wayland() -> bool:
    return QGuiApplication.platformName().startswith("wayland")


def kde() -> bool:
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":") and bool(shutil.which("kwriteconfig6"))


def can_place() -> bool:
    return not wayland() or kde()


def top_centre(width: int) -> QPoint:
    g = QGuiApplication.primaryScreen().availableGeometry()
    return QPoint(g.x() + (g.width() - width) // 2, g.y() + g.height() // 8)


def kwin_rule(position: str, width: int) -> dict[str, str] | None:
    """The rule's keys for a position, or None for no rule."""
    base = {"Description": "owui-pop position (managed by owui-pop)", "wmclass": APP_ID, "wmclassmatch": "1"}
    if position == "center":
        return base | {"placement": str(_CENTERED), "placementrule": str(_FORCE)}
    if position == "mouse":
        return base | {"placement": str(_UNDER_MOUSE), "placementrule": str(_FORCE)}
    if position == "top":
        p = top_centre(width)
        return base | {"position": f"{p.x()},{p.y()}", "positionrule": str(_APPLY_INITIALLY)}
    if position == "remember":
        return base | {"positionrule": str(_REMEMBER)}
    return None


def _kread(group: str, key: str) -> str:
    r = subprocess.run(["kreadconfig6", "--file", "kwinrulesrc", "--group", group, "--key", key],
                       capture_output=True, text=True, check=False)
    return r.stdout.strip()


def _kwrite(group: str, key: str, value: str | None) -> None:
    # the full file name matters: --file kwinrules would write a different file
    args = ["kwriteconfig6", "--file", "kwinrulesrc", "--group", group, "--key", key]
    subprocess.run(args + (["--delete"] if value is None else [value]), check=False)


def write_kwin_rule(position: str, width: int) -> None:
    rule = kwin_rule(position, width)
    keys = ("Description", "wmclass", "wmclassmatch", "placement", "placementrule", "position", "positionrule")
    for k in keys:  # clear this rule's old keys first, so switching kinds leaves nothing behind
        _kwrite(RULE, k, None)
    rules = [r for r in _kread("General", "rules").split(",") if r and r != RULE]
    if rule:
        for k, v in rule.items():
            _kwrite(RULE, k, v)
        rules.append(RULE)
    _kwrite("General", "rules", ",".join(rules))
    _kwrite("General", "count", str(len(rules)))
    subprocess.run(["dbus-send", "--session", "--type=method_call", "--dest=org.kde.KWin", "/KWin",
                    "org.kde.KWin.reconfigure"], check=False)


def apply(position: str, window: QWidget, remembered: tuple[int, int] | None = None) -> None:
    """X11: move the window now, before it shows. Wayland: nothing to do here (the rule places it)."""
    if wayland():
        return
    if position == "center":
        g = QGuiApplication.primaryScreen().availableGeometry()
        window.move(g.center() - window.rect().center())
    elif position == "top":
        window.move(top_centre(window.width()))
    elif position == "mouse":
        window.move(QCursor.pos() - QPoint(window.width() // 2, 30))
    elif position == "remember" and remembered:
        window.move(*remembered)
