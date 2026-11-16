import json
import stat

from owui_pop import config


def test_nothing_saved_is_empty(tmp_path):
    cfg = config.load(tmp_path / "owui-pop")
    assert cfg.servers == [] and cfg.current() is None


def test_round_trip_keeps_servers_and_prefs(tmp_path):
    d = tmp_path / "owui-pop"
    cfg = config.Config(servers=[config.Server(name="Home", url="https://chat.example/", model="m")])
    cfg.prefs.theme, cfg.prefs.font_scale, cfg.prefs.last_server = "dark", 1.2, cfg.servers[0].id
    config.save(cfg, d)
    back = config.load(d)
    assert back.servers[0].url == "https://chat.example"
    assert back.servers[0].model == "m"
    assert back.prefs.theme == "dark" and back.prefs.font_scale == 1.2
    assert back.current().name == "Home"


def test_bad_values_fall_back(tmp_path):
    d = tmp_path / "owui-pop"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({
        "servers": [{"name": "x", "url": "file:///etc"}, {"url": "http://ok:8080"}, "junk"],
        "prefs": {"theme": "neon", "font_scale": 9, "width": "wide"},
    }))
    cfg = config.load(d)
    assert [s.url for s in cfg.servers] == ["http://ok:8080"]
    assert cfg.prefs.theme == "system" and cfg.prefs.font_scale == 2.0 and cfg.prefs.width == 760


def test_keys_live_apart_and_only_the_user_can_read_them(tmp_path):
    d = tmp_path / "owui-pop"
    config.write_key("abc", " sk-1 ", d)
    p = d / "keys" / "abc"
    assert p.read_text() == "sk-1\n"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    assert config.read_key("abc", d) == "sk-1"
    config.save(config.Config(servers=[config.Server(name="a", url="http://a", id="abc")]), d)
    assert "sk-1" not in (d / "config.json").read_text()
    config.write_key("abc", "", d)
    assert not p.exists() and config.read_key("abc", d) == ""


def test_migrates_the_earlier_owui_ask_config_with_keys(tmp_path):
    old = tmp_path / "owui-ask"
    old.mkdir()
    (old / "config.json").write_text(json.dumps({
        "brave": "/opt/brave/brave", "last": 1,
        "instances": [
            {"name": ":3000  Home", "url": "https://a.example", "app_id": "aaa", "key_file": "api-key"},
            {"name": "Work", "url": "https://b.example/", "app_id": "", "key_file": "../../etc/passwd"},
        ]}))
    (old / "api-key").write_text("sk-home\n")
    cfg = config.load(tmp_path / "owui-pop")
    a, b = cfg.servers
    assert a.name == ":3000 Home"
    assert a.open_command == "/opt/brave/brave --profile-directory=Default --app-id=aaa --app-launch-url-for-shortcuts-menu-item={url}"
    assert b.url == "https://b.example" and b.open_command == ""
    assert config.read_key(a.id, tmp_path / "owui-pop") == "sk-home"
    assert config.read_key(b.id, tmp_path / "owui-pop") == ""  # a key_file outside the folder is not followed
    assert cfg.prefs.last_server == b.id
    assert (tmp_path / "owui-pop" / "config.json").exists()  # imported once


def test_position_is_kept_and_checked(tmp_path):
    d = tmp_path / "owui-pop"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"servers": [], "prefs": {"position": "mouse", "last_xy": [10, 20]}}))
    assert config.load(d).prefs.position == "mouse" and config.load(d).prefs.last_xy == [10, 20]
    (d / "config.json").write_text(json.dumps({"servers": [], "prefs": {"position": "left", "last_xy": ["a", 1]}}))
    assert config.load(d).prefs.position == "desktop" and config.load(d).prefs.last_xy == []
