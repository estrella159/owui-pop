"""Settings on disk: servers and preferences in config.json, each API key in its own file.

Layout (``$XDG_CONFIG_HOME/owui-pop``, usually ``~/.config/owui-pop``)::

    config.json        servers (without keys) and preferences
    keys/<server id>   one API key per server, mode 600

Keys never go into config.json, so the file can be shared or backed up without leaking them.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

THEMES = ("system", "light", "dark")
POSITIONS = ("desktop", "center", "top", "mouse", "remember")
OPEN_DEFAULT = ""  # empty: the default browser


@dataclass
class Server:
    name: str
    url: str
    id: str = field(default_factory=lambda: secrets.token_hex(4))
    #: empty: the account's default model in Open WebUI
    model: str = ""
    #: how to open a chat in the full app: empty for the default browser, else a command with {url}
    open_command: str = OPEN_DEFAULT


@dataclass
class Prefs:
    theme: str = "system"
    font_scale: float = 1.0
    width: int = 760
    always_on_top: bool = True
    last_server: str = ""
    #: see position.POSITIONS
    position: str = "desktop"
    #: X11 only: where it was last left, for "remember"
    last_xy: list[int] = field(default_factory=list)


@dataclass
class Config:
    servers: list[Server] = field(default_factory=list)
    prefs: Prefs = field(default_factory=Prefs)

    def server(self, server_id: str) -> Server | None:
        return next((s for s in self.servers if s.id == server_id), None)

    def current(self) -> Server | None:
        return self.server(self.prefs.last_server) or (self.servers[0] if self.servers else None)


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "owui-pop"


def clean_url(url: str) -> str | None:
    """An http(s) address without a trailing slash, or None."""
    url = url.strip().rstrip("/")
    return url if re.match(r"^https?://[^\s/]+", url) else None


def _server(d: dict) -> Server | None:
    if not isinstance(d, dict) or not isinstance(d.get("url"), str):
        return None
    url = clean_url(d["url"])
    if not url:
        return None
    s = Server(name=str(d.get("name") or url), url=url)
    if isinstance(d.get("id"), str) and re.fullmatch(r"[0-9a-zA-Z_-]{1,40}", d["id"]):
        s.id = d["id"]
    s.model = str(d.get("model") or "")
    s.open_command = str(d.get("open_command") or "")
    return s


def _prefs(d: dict) -> Prefs:
    p = Prefs()
    if not isinstance(d, dict):
        return p
    if d.get("theme") in THEMES:
        p.theme = d["theme"]
    try:
        p.font_scale = min(2.0, max(0.75, float(d.get("font_scale", p.font_scale))))
        p.width = min(2000, max(420, int(d.get("width", p.width))))
    except (TypeError, ValueError):
        pass
    if isinstance(d.get("always_on_top"), bool):
        p.always_on_top = d["always_on_top"]
    if isinstance(d.get("last_server"), str):
        p.last_server = d["last_server"]
    if d.get("position") in POSITIONS:
        p.position = d["position"]
    xy = d.get("last_xy")
    if isinstance(xy, list) and len(xy) == 2 and all(isinstance(v, int) for v in xy):
        p.last_xy = xy
    return p


def load(directory: Path | None = None) -> Config:
    directory = directory or config_dir()
    try:
        raw = json.loads((directory / "config.json").read_text())
    except (OSError, ValueError):
        return migrate_owui_ask(directory) or Config()
    servers = [s for s in (_server(x) for x in raw.get("servers", [])) if s]
    return Config(servers=servers, prefs=_prefs(raw.get("prefs", {})))


def save(cfg: Config, directory: Path | None = None) -> None:
    directory = directory or config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / "config.json.part"
    tmp.write_text(json.dumps({"servers": [asdict(s) for s in cfg.servers], "prefs": asdict(cfg.prefs)}, indent=2) + "\n")
    tmp.replace(directory / "config.json")


def _key_path(server_id: str, directory: Path | None) -> Path:
    return (directory or config_dir()) / "keys" / server_id


def read_key(server_id: str, directory: Path | None = None) -> str:
    try:
        return _key_path(server_id, directory).read_text().strip()
    except OSError:
        return ""


def write_key(server_id: str, key: str, directory: Path | None = None) -> None:
    """Saves the key readable only by this user; an empty key removes it."""
    path = _key_path(server_id, directory)
    key = key.strip()
    if not key:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    os.chmod(path, 0o600)


def migrate_owui_ask(directory: Path) -> Config | None:
    """One-time import from the earlier private version (~/.config/owui-ask), keys included."""
    old = directory.parent / "owui-ask"
    try:
        raw = json.loads((old / "config.json").read_text())
    except (OSError, ValueError):
        return None
    cfg = Config()
    brave = raw.get("brave") if isinstance(raw.get("brave"), str) else ""
    for inst in raw.get("instances", []):
        s = _server(inst)
        if not s:
            continue
        s.name = re.sub(r"\s+", " ", s.name).strip()
        if brave and isinstance(inst.get("app_id"), str) and inst["app_id"]:
            s.open_command = (f"{brave} --profile-directory=Default --app-id={inst['app_id']} "
                              "--app-launch-url-for-shortcuts-menu-item={url}")
        key = ""
        if isinstance(inst.get("key_file"), str):
            try:
                key = (old / os.path.basename(inst["key_file"])).read_text().strip()
            except OSError:
                pass
        cfg.servers.append(s)
        if key:
            write_key(s.id, key, directory)
    if not cfg.servers:
        return None
    last = raw.get("last", 0)
    if isinstance(last, int) and 0 <= last < len(cfg.servers):
        cfg.prefs.last_server = cfg.servers[last].id
    save(cfg, directory)
    return cfg
