"""Settings: servers (address, API key, model, how chats open) and appearance."""
from __future__ import annotations

import copy

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import client, config, position

ACCOUNT_DEFAULT = "Account default"


class CheckWorker(QThread):
    result = pyqtSignal(object)

    def __init__(self, url: str, key: str):
        super().__init__()
        self.url, self.key = url, key

    def run(self) -> None:
        self.result.emit(client.check(self.url, self.key))


class SettingsDialog(QDialog):
    """Edits a copy of the config; nothing is saved until Save."""
    saved = pyqtSignal()

    def __init__(self, cfg: config.Config, parent: QWidget | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.servers = [copy.copy(s) for s in cfg.servers]
        self.new_keys: dict[str, str] = {}  # server id -> key typed here ('' removes)
        self.checker: CheckWorker | None = None
        self.setWindowTitle("owui-pop settings")
        self.setMinimumWidth(620)
        tabs = QTabWidget()
        tabs.addTab(self._servers_tab(), "Servers")
        tabs.addTab(self._appearance_tab(), "Appearance")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.error = QLabel()
        self.error.setObjectName("error")
        self.error.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(self.error)
        lay.addWidget(buttons)
        self._fill_list()

    # --- servers
    def _servers_tab(self) -> QWidget:
        w = QWidget()
        self.list = QListWidget()
        self.list.setMaximumWidth(190)
        self.list.currentRowChanged.connect(self._show_server)
        add, remove = QPushButton("Add"), QPushButton("Remove")
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)
        left = QVBoxLayout()
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        left.addLayout(row)

        self.form = QWidget()
        f = QFormLayout(self.form)
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://openwebui.example.com")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.forget_key = QPushButton("Remove saved key")
        self.forget_key.setFlat(True)
        self.forget_key.clicked.connect(self._forget_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        key_row.addWidget(self.forget_key)
        self.model = QComboBox()
        self.model.setEditable(True)
        test_row = QHBoxLayout()
        self.test = QPushButton("Test connection")
        self.test.clicked.connect(self._test)
        self.test_result = QLabel()
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test)
        test_row.addWidget(self.test_result, 1)
        self.open_with = QComboBox()
        self.open_with.addItems(["Default browser", "Command"])
        self.open_command = QLineEdit()
        self.open_command.setPlaceholderText("e.g. firefox --new-window {url}")
        self.open_with.currentIndexChanged.connect(lambda i: self.open_command.setEnabled(i == 1))
        help_key = QLabel("Create a key in Open WebUI under Settings → Account → API keys. It is saved in its own "
                          "file that only you can read, and never shown here again.")
        help_key.setWordWrap(True)
        help_key.setObjectName("help")
        f.addRow("Name", self.name)
        f.addRow("Address", self.url)
        f.addRow("API key", key_row)
        f.addRow("", help_key)
        f.addRow("", test_row)
        f.addRow("Model", self.model)
        f.addRow("Open chats in", self.open_with)
        f.addRow("", self.open_command)
        for field in (self.name, self.url, self.open_command):
            field.editingFinished.connect(self._store)
        self.key.textEdited.connect(self._key_typed)
        self.model.currentTextChanged.connect(lambda _t: self._store())
        self.open_with.currentIndexChanged.connect(lambda _i: self._store())

        lay = QHBoxLayout(w)
        lay.addLayout(left)
        lay.addWidget(self.form, 1)
        return w

    def _fill_list(self) -> None:
        self.list.clear()
        for s in self.servers:
            self.list.addItem(QListWidgetItem(s.name))
        current = self.cfg.current()
        idx = next((i for i, s in enumerate(self.servers) if current and s.id == current.id), 0)
        self.list.setCurrentRow(idx if self.servers else -1)
        self.form.setEnabled(bool(self.servers))

    def _sel(self) -> config.Server | None:
        i = self.list.currentRow()
        return self.servers[i] if 0 <= i < len(self.servers) else None

    def _show_server(self, _row: int) -> None:
        s = self._sel()
        self.form.setEnabled(bool(s))
        if not s:
            return
        self._loading = True
        self.name.setText(s.name)
        self.url.setText(s.url)
        self.key.clear()
        has = bool(self.new_keys.get(s.id) if s.id in self.new_keys else config.read_key(s.id))
        self.key.setPlaceholderText("Saved. Type a new one to replace it." if has else "Paste the API key")
        self.forget_key.setVisible(has)
        self.model.clear()
        self.model.addItem(ACCOUNT_DEFAULT)
        if s.model:
            self.model.addItem(s.model)
            self.model.setCurrentText(s.model)
        self.open_with.setCurrentIndex(1 if s.open_command else 0)
        self.open_command.setText(s.open_command)
        self.open_command.setEnabled(bool(s.open_command))
        self.test_result.clear()
        self._loading = False

    def _store(self) -> None:
        s = self._sel()
        if not s or getattr(self, "_loading", False):
            return
        s.name = self.name.text().strip() or s.url or "Open WebUI"
        s.url = self.url.text().strip()
        model = self.model.currentText().strip()
        s.model = "" if model in ("", ACCOUNT_DEFAULT) else model
        s.open_command = self.open_command.text().strip() if self.open_with.currentIndex() == 1 else ""
        item = self.list.currentItem()
        if item:
            item.setText(s.name)

    def _key_typed(self, text: str) -> None:
        s = self._sel()
        if s:
            self.new_keys[s.id] = text.strip()

    def _forget_key(self) -> None:
        s = self._sel()
        if s:
            self.new_keys[s.id] = ""
            self.key.clear()
            self.key.setPlaceholderText("Paste the API key")
            self.forget_key.hide()

    def _add(self) -> None:
        self._store()
        self.servers.append(config.Server(name="Open WebUI", url=""))
        self.list.addItem(QListWidgetItem("Open WebUI"))
        self.list.setCurrentRow(len(self.servers) - 1)
        self.form.setEnabled(True)
        self.url.setFocus()

    def _remove(self) -> None:
        i = self.list.currentRow()
        if 0 <= i < len(self.servers):
            gone = self.servers.pop(i)
            self.new_keys[gone.id] = ""
            self.list.takeItem(i)
            self._show_server(self.list.currentRow())

    def _test(self) -> None:
        self._store()
        s = self._sel()
        url = config.clean_url(self.url.text())
        if not s or not url:
            self.test_result.setText("That isn't an http or https address.")
            return
        key = self.new_keys.get(s.id) if s.id in self.new_keys else config.read_key(s.id)
        self.test.setEnabled(False)
        self.test_result.setText("Testing…")
        self.checker = CheckWorker(url, key or "")
        self.checker.result.connect(self._tested)
        self.checker.start()

    def _tested(self, r: client.Check) -> None:
        self.test.setEnabled(True)
        if not r.ok:
            self.test_result.setText(r.error)
            return
        keep = self.model.currentText()
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItem(ACCOUNT_DEFAULT)
        self.model.addItems(r.models)
        self.model.setCurrentText(keep or ACCOUNT_DEFAULT)
        self.model.blockSignals(False)
        self.test_result.setText(f"Connected. {len(r.models)} models available." if r.models else "Connected, but no models are available to this key.")

    # --- appearance
    def _appearance_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        p = self.cfg.prefs
        self.theme = QComboBox()
        for value, label in (("system", "Follow the system"), ("light", "Light"), ("dark", "Dark")):
            self.theme.addItem(label, value)
        self.theme.setCurrentIndex(max(0, self.theme.findData(p.theme)))
        self.font_scale = QSpinBox()
        self.font_scale.setRange(75, 200)
        self.font_scale.setSingleStep(5)
        self.font_scale.setSuffix(" %")
        self.font_scale.setValue(round(p.font_scale * 100))
        self.width_box = QSpinBox()
        self.width_box.setRange(420, 2000)
        self.width_box.setSingleStep(20)
        self.width_box.setSuffix(" px")
        self.width_box.setValue(p.width)
        self.position = QComboBox()
        for value, label in position.POSITIONS.items():
            self.position.addItem(label, value)
        self.position.setCurrentIndex(max(0, self.position.findData(p.position)))
        place_note = QLabel()
        place_note.setWordWrap(True)
        place_note.setObjectName("help")
        if not position.can_place():
            self.position.setEnabled(False)
            place_note.setText("On this desktop the compositor places windows, and apps can't choose.")
        elif position.wayland():
            place_note.setText("On KDE Plasma this is a KWin window rule for the pop-up only, removed again by "
                               "“Let the desktop decide”.")
        self.on_top = QCheckBox("Keep the pop-up above other windows")
        self.on_top.setChecked(p.always_on_top)
        shortcut = QLabel("To open the pop-up with a key, bind the command <code>owui-pop</code> in your desktop's "
                          "keyboard shortcuts (KDE: System Settings → Shortcuts → Add New → Command).")
        shortcut.setWordWrap(True)
        shortcut.setTextFormat(Qt.TextFormat.RichText)
        shortcut.setObjectName("help")
        f.addRow("Theme", self.theme)
        f.addRow("Text size", self.font_scale)
        f.addRow("Width", self.width_box)
        f.addRow("Position", self.position)
        f.addRow("", place_note)
        f.addRow("", self.on_top)
        f.addRow("Shortcut", shortcut)
        return w

    # --- save
    def save(self) -> None:
        self._store()
        for s in self.servers:
            url = config.clean_url(s.url)
            if not url:
                self.list.setCurrentRow(self.servers.index(s))
                self.error.setText(f"“{s.name}” needs an http or https address.")
                return
            s.url = url
        gone = {s.id for s in self.cfg.servers} - {s.id for s in self.servers}
        for sid in gone:
            config.write_key(sid, "")
        for sid, key in self.new_keys.items():
            if sid not in gone:
                config.write_key(sid, key)
        self.cfg.servers = self.servers
        p = self.cfg.prefs
        p.theme = self.theme.currentData()
        p.font_scale = self.font_scale.value() / 100
        p.width = self.width_box.value()
        p.always_on_top = self.on_top.isChecked()
        new_position = self.position.currentData()
        if new_position != p.position or new_position == "top":
            p.position = new_position
            if position.wayland() and position.kde():
                position.write_kwin_rule(p.position, p.width)
        if not self.cfg.server(p.last_server) and self.servers:
            p.last_server = self.servers[0].id
        config.save(self.cfg)
        self.saved.emit()
        self.accept()
