import os
import pytest
import config

def test_get_allowed_users_dynamic_reload(tmp_path, monkeypatch):
    """get_allowed_users should re-read .env dynamically when edited."""
    env_file = tmp_path / ".env"
    env_file.write_text("ALLOWED_USERS=111,222")
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)

    users = config._real_get_allowed_users()
    assert users == [111, 222]

    # Dynamically edit .env file
    env_file.write_text("ALLOWED_USERS=111,222,333")
    users_updated = config._real_get_allowed_users()
    assert users_updated == [111, 222, 333]

def test_get_allowed_users_default_empty(tmp_path, monkeypatch):
    """get_allowed_users should default to an empty list when ALLOWED_USERS is unset."""
    monkeypatch.delenv("ALLOWED_USERS", raising=False)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    assert config._real_get_allowed_users() == []

