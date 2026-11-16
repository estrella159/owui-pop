"""Start-up: one instance per user; running the command again shows the pop-up that is already there."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from . import __version__, config, theme
from .settings import SettingsDialog
from .window import QuickWindow

SOCKET = f"owui-pop-{os.getuid()}"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if "--version" in argv:
        print(f"owui-pop {__version__}")
        return 0
    app = QApplication(argv)
    app.setApplicationName("owui-pop")
    app.setDesktopFileName("owui-pop")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon.fromTheme("owui-pop", QIcon(str(Path(__file__).parent / "data" / "owui-pop.svg"))))

    sock = QLocalSocket()
    sock.connectToServer(SOCKET)
    if sock.waitForConnected(300):
        sock.write(b"settings" if "--settings" in argv else b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(SOCKET)
    server = QLocalServer()
    server.listen(SOCKET)

    cfg = config.load()
    theme.apply(app, cfg.prefs.theme, cfg.prefs.font_scale)
    win = QuickWindow(cfg)
    dialog: list[SettingsDialog] = []

    def applied() -> None:
        theme.apply(app, cfg.prefs.theme, cfg.prefs.font_scale)
        win.apply_window_flags()
        win.reload_servers()
        win.restyle()
        win.summon()

    def open_settings() -> None:
        if dialog and dialog[0].isVisible():
            dialog[0].raise_()
            dialog[0].activateWindow()
            return
        d = SettingsDialog(cfg)
        d.saved.connect(applied)
        dialog[:] = [d]
        win.hide()  # a frameless always-on-top pop-up would cover the dialog
        d.finished.connect(lambda _r: win.summon())
        d.show()

    def message() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return
        conn.waitForReadyRead(300)
        (open_settings if bytes(conn.readAll()).strip() == b"settings" else win.summon)()

    win.settings_requested.connect(open_settings)
    server.newConnection.connect(message)
    if not cfg.servers or "--settings" in argv:
        open_settings()
    else:
        win.summon()
    return app.exec()
