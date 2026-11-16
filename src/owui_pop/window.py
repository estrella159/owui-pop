"""The pop-up: one line to ask, the conversation below it, keys for everything."""
from __future__ import annotations

import shlex
import subprocess

import httpx
from PyQt6.QtCore import QEvent, QObject, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import client, config, position, render

HINT = "Enter send · Esc hide · Ctrl+N new · Ctrl+O open in Open WebUI · Ctrl+, settings"
EXPANDED_H = 560
#: how close to the end counts as "at the end": within this many pixels the view keeps following
FOLLOW_SLACK = 24


class TurnWorker(QThread):
    """One question and answer, off the UI thread: finds the model (and its tools) first if needed."""
    update = pyqtSignal(str)
    failed = pyqtSignal(str)
    done = pyqtSignal(str)
    model_found = pyqtSignal(str, list)

    def __init__(self, server: config.Server, key: str, model: str, tools: list[str], chat_id: str | None, messages: list[dict]):
        super().__init__()
        self.server, self.key, self.model, self.tools = server, key, model, tools
        self.chat_id, self.messages = chat_id, messages
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0)) as c:
                if not self.model:
                    try:
                        self.model = self.server.model or client.account_model(self.server.url, self.key, c)
                        self.tools = client.model_tools(self.server.url, self.key, self.model, c) if self.model else []
                    except (httpx.HTTPError, ValueError, KeyError, AttributeError) as e:
                        raise client.TurnError(client.describe(e)) from e
                    if not self.model:
                        raise client.TurnError("This account has no model to answer with.")
                    self.model_found.emit(self.model, self.tools)
                chat_id = client.run_turn(self.server.url, self.key, self.model, self.tools, self.chat_id, self.messages,
                                          self.update.emit, lambda: self._stop, c)
                if chat_id:
                    self.done.emit(chat_id)
        except client.TurnError as e:
            if not self._stop:
                self.failed.emit(str(e))


class Message(QLabel):
    """One message, Markdown, selectable, links open in the browser."""

    def __init__(self, role: str, text: str = ""):
        super().__init__()
        self.setObjectName("user" if role == "user" else "answer")
        self.setTextFormat(Qt.TextFormat.MarkdownText)
        self.setWordWrap(True)
        self.setOpenExternalLinks(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the input keeps the keyboard; selecting with the mouse still works
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.show_text(text)

    def show_text(self, text: str) -> None:
        # what the user typed is shown as typed; answers get Open WebUI's line breaks and readable maths
        self.setText((render.for_display(text) if self.objectName() == "answer" else text) or "…")


class Conversation(QScrollArea):
    """The messages, following the end while it grows only if the reader is already there."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("conversation")
        self.box = QVBoxLayout(inner)
        self.box.setContentsMargins(0, 4, 6, 4)
        self.box.setSpacing(12)
        self.box.addStretch(1)
        self.setWidget(inner)
        self.following = True
        bar = self.verticalScrollBar()
        bar.valueChanged.connect(self._moved)
        bar.rangeChanged.connect(self._grew)

    def at_end(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - FOLLOW_SLACK

    def _moved(self, _value: int) -> None:
        self.following = self.at_end()

    def _grew(self, _lo: int, hi: int) -> None:
        if self.following:
            self.verticalScrollBar().setValue(hi)

    def add(self, role: str, text: str = "") -> Message:
        m = Message(role, text)
        self.box.insertWidget(self.box.count() - 1, m)
        return m

    def clear(self) -> None:
        while self.box.count() > 1:
            w = self.box.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.following = True


class QuickWindow(QWidget):
    settings_requested = pyqtSignal()

    def __init__(self, cfg: config.Config):
        super().__init__()
        self.cfg = cfg
        self.messages: list[dict] = []
        self.chat_id: str | None = None
        self.worker: TurnWorker | None = None
        self.answer_view: Message | None = None
        self.models: dict[str, tuple[str, list[str]]] = {}  # server id -> (model, tools), found once per run
        self.setWindowTitle("owui-pop")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.apply_window_flags()

        frame = QWidget(self)
        frame.setObjectName("frame")
        frame.setToolTip("Drag an empty part to move the pop-up")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(8)

        top = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setObjectName("ask")
        self.input.setPlaceholderText("Ask anything…")
        self.input.returnPressed.connect(self.send)
        self.server_box = QComboBox()
        self.server_box.setMinimumWidth(150)
        self.server_box.currentIndexChanged.connect(self.server_changed)
        gear = QToolButton()
        gear.setText("⚙")
        gear.setToolTip("Settings (Ctrl+,)")
        gear.setAutoRaise(True)
        gear.clicked.connect(self.settings_requested.emit)
        top.addWidget(self.input, 1)
        top.addWidget(self.server_box)
        top.addWidget(gear)
        lay.addLayout(top)

        self.conversation = Conversation()
        self.conversation.hide()
        lay.addWidget(self.conversation, 1)

        bottom = QHBoxLayout()
        self.status = QLabel(HINT)
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.status.setCursor(Qt.CursorShape.SizeAllCursor)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop)
        self.copy_button = QPushButton("Copy")
        self.copy_button.setToolTip("Copy the last answer (Ctrl+Shift+C)")
        self.copy_button.clicked.connect(self.copy_answer)
        for b in (self.stop_button, self.copy_button):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.hide()
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.copy_button)
        bottom.addWidget(self.stop_button)
        lay.addLayout(bottom)

        C, S, N = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier, Qt.KeyboardModifier.NoModifier
        # keys are read on the input itself: window-level shortcuts don't fire reliably in a frameless tool window
        self.keymap = {
            (Qt.Key.Key_Escape, N): self.escape,
            (Qt.Key.Key_O, C): self.open_full,
            (Qt.Key.Key_N, C): self.reset,
            (Qt.Key.Key_C, C | S): self.copy_answer,
            (Qt.Key.Key_Comma, C): self.settings_requested.emit,
        }
        self.input.installEventFilter(self)
        self.reload_servers()
        self.restyle()
        self.compact()

    # --- settings and look
    def apply_window_flags(self) -> None:
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if self.cfg.prefs.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        visible = self.isVisible()
        self.setWindowFlags(flags)
        if visible:
            self.show()

    def restyle(self) -> None:
        """Called after a theme change too: the style sheet reads the palette when it is set."""
        f = self.input.font()
        f.setPointSizeF(QGuiApplication.font().pointSizeF() * 1.25)
        self.input.setFont(f)
        self.resize(self.cfg.prefs.width, self.height())
        self.setStyleSheet("""
            #frame { background: palette(window); border: 1px solid palette(mid); border-radius: 14px; }
            #ask { border: none; background: transparent; padding: 6px 2px; }
            #conversation { background: transparent; }
            QScrollArea { background: transparent; }
            #user { background: palette(button); border-radius: 8px; padding: 6px 10px; }
            #answer { padding: 0 2px; }
            #status { color: palette(placeholder-text); font-size: 9pt; }
        """)

    def reload_servers(self) -> None:
        self.server_box.blockSignals(True)
        self.server_box.clear()
        for s in self.cfg.servers:
            self.server_box.addItem(s.name, s.id)
        current = self.cfg.current()
        if current:
            self.server_box.setCurrentIndex(max(0, self.server_box.findData(current.id)))
        self.server_box.blockSignals(False)
        self.server_box.setVisible(len(self.cfg.servers) > 1)
        self.models.clear()  # a changed model or key is picked up on the next question
        if not self.cfg.servers:
            self.status.setText("No server yet. Press Ctrl+, to add your Open WebUI.")

    def server(self) -> config.Server | None:
        return self.cfg.server(self.server_box.currentData() or "")

    def server_changed(self, _idx: int) -> None:
        s = self.server()
        if s:
            self.cfg.prefs.last_server = s.id
            config.save(self.cfg)
        if self.messages and not self.worker:
            self.reset()

    # --- the conversation
    def send(self) -> None:
        text = self.input.text().strip()
        s = self.server()
        if not text or self.worker:
            return
        if not s:
            self.settings_requested.emit()
            return
        key = config.read_key(s.id)
        if not key:
            self.status.setText(f"No API key for {s.name}. Add one in Settings (Ctrl+,).")
            return
        self.messages += [client.new_message("user", text), client.new_message("assistant")]
        self.input.clear()
        self.input.setPlaceholderText("Follow-up…")
        self.expand()
        self.conversation.add("user", text)
        self.answer_view = self.conversation.add("assistant")
        self.conversation.following = True
        model, tools = self.models.get(s.id, ("", []))
        self.status.setText("Working… tools and lookups run on the server")
        self.stop_button.show()
        self.copy_button.hide()
        self.worker = TurnWorker(s, key, model, tools, self.chat_id, self.messages)
        self.worker.model_found.connect(lambda m, t, sid=s.id: self.models.__setitem__(sid, (m, t)))
        self.worker.update.connect(self.on_update)
        self.worker.failed.connect(self.on_fail)
        self.worker.done.connect(self.on_done)
        self.worker.finished.connect(self._worker_gone)
        self.worker.start()

    def on_update(self, text: str) -> None:
        self.messages[-1]["content"] = text
        if self.answer_view:
            self.answer_view.show_text(text)

    def on_fail(self, err: str) -> None:
        self.status.setText(err)
        if self.answer_view and not self.messages[-1]["content"]:
            self.answer_view.show_text("_No answer._")

    def on_done(self, chat_id: str) -> None:
        self.chat_id = chat_id
        model = self.models.get(self.server().id if self.server() else "", ("", []))[0]
        self.status.setText(f"{model} · Ctrl+O open in Open WebUI · Ctrl+Shift+C copy" if model else HINT)
        self.copy_button.show()

    def _worker_gone(self) -> None:
        self.worker = None
        self.stop_button.hide()

    def stop(self) -> None:
        if self.worker:
            self.worker.stop()
            self.status.setText("Stopped. The server may still finish the answer in Open WebUI.")

    def copy_answer(self) -> None:
        answers = [m["content"] for m in self.messages if m["role"] == "assistant" and m["content"]]
        if answers:
            QGuiApplication.clipboard().setText(answers[-1])
            self.status.setText("Copied the answer.")

    def reset(self) -> None:
        if self.worker:
            return
        self.messages, self.chat_id, self.answer_view = [], None, None
        self.conversation.clear()
        self.conversation.hide()
        self.copy_button.hide()
        self.status.setText(HINT if self.cfg.servers else "No server yet. Press Ctrl+, to add your Open WebUI.")
        self.input.setPlaceholderText("Ask anything…")
        self.compact()

    def escape(self) -> None:
        if self.worker:
            self.stop()
        else:
            self.hide()

    def open_full(self) -> None:
        s = self.server()
        if not s or not self.chat_id or self.worker:
            return
        url = f"{s.url}/c/{self.chat_id}"
        if s.open_command.strip():
            try:
                args = [a.replace("{url}", url) for a in shlex.split(s.open_command)]
                if not any(url in a for a in args):
                    args.append(url)
                subprocess.Popen(args, start_new_session=True)
            except (OSError, ValueError) as e:
                self.status.setText(f"Couldn't run the open command: {e}")
                return
        else:
            QDesktopServices.openUrl(QUrl(url))
        self.hide()
        self.reset()

    # --- keys
    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if ev.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            mods = ev.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            fn = self.keymap.get((Qt.Key(ev.key()), mods))
            if fn:
                if ev.type() == QEvent.Type.KeyPress:
                    fn()
                ev.accept()
                return True
        return super().eventFilter(obj, ev)

    # --- size. Wayland compositors (KWin 6.8, Qt 6.12) ignore resize() on a shown window but honour
    # minimum/maximum size hints, so the size is set through those and released afterwards.
    def expand(self) -> None:
        if self.conversation.isVisible():
            return
        self.conversation.show()
        self.setMinimumHeight(EXPANDED_H)
        self.resize(self.width(), EXPANDED_H)
        QTimer.singleShot(200, lambda: self.setMinimumHeight(0) if self.conversation.isVisible() else None)

    def compact(self) -> None:
        h = self.layout().sizeHint().height()
        self.setMinimumHeight(0)
        self.setMaximumHeight(h)
        self.resize(self.cfg.prefs.width, h)
        QTimer.singleShot(200, lambda: self.setMaximumHeight(16777215))

    def mousePressEvent(self, ev) -> None:
        """Drag by any empty part (the edges, the status line): the compositor moves it, Wayland included."""
        if ev.button() == Qt.MouseButton.LeftButton and self.windowHandle() and self.windowHandle().startSystemMove():
            ev.accept()
            return
        super().mousePressEvent(ev)

    def hideEvent(self, ev) -> None:  # X11: "remember" keeps where it was left
        if self.cfg.prefs.position == "remember" and not position.wayland():
            self.cfg.prefs.last_xy = [self.x(), self.y()]
            config.save(self.cfg)
        super().hideEvent(ev)

    def summon(self) -> None:
        if not self.isVisible():
            position.apply(self.cfg.prefs.position, self, tuple(self.cfg.prefs.last_xy) or None)
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(50, self.input.setFocus)
