import config


def test_allowed_users_reloads_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ALLOWED_USERS", raising=False)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("ALLOWED_USERS=111, 222")
    assert config.get_allowed_users() == [111, 222]

    env_file.write_text("ALLOWED_USERS=111,222,333,not-a-number")
    assert config.get_allowed_users() == [111, 222, 333]


def test_allowed_users_falls_back_to_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setenv("ALLOWED_USERS", "42")
    assert config.get_allowed_users() == [42]

    monkeypatch.delenv("ALLOWED_USERS")
    assert config.get_allowed_users() == []


def test_timezone_from_environment(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Europe/Athens")
    assert str(config.get_timezone()) == "Europe/Athens"
