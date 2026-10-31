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


def allowed(tmp_path, monkeypatch, value):
    monkeypatch.delenv("ALLOWED_USERS", raising=False)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    (tmp_path / ".env").write_text(f"ALLOWED_USERS={value}")
    return config.get_allowed_users()


def test_allowed_users_accept_spaces_and_semicolons(tmp_path, monkeypatch):
    assert allowed(tmp_path, monkeypatch, "111 222") == [111, 222]
    assert allowed(tmp_path, monkeypatch, "111;222, 333") == [111, 222, 333]


def test_a_typo_in_the_first_id_never_makes_someone_else_admin(tmp_path, monkeypatch, caplog):
    assert allowed(tmp_path, monkeypatch, "x111, 222") == []
    assert "isn't a Telegram user ID" in caplog.text


def test_odd_digits_are_ignored_instead_of_crashing(tmp_path, monkeypatch):
    assert allowed(tmp_path, monkeypatch, "111,²") == [111]


def test_problems_are_logged_once(tmp_path, monkeypatch, caplog):
    for _ in range(3):
        allowed(tmp_path, monkeypatch, "111, 22x")
    assert caplog.text.count("aren't Telegram user IDs") == 1
