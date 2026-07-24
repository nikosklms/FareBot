import os
import pytest
from config import get_allowed_users

def test_get_allowed_users_dynamic_reload(tmp_path, monkeypatch):
    """get_allowed_users should re-read .env dynamically when edited."""
    env_file = tmp_path / ".env"
    env_file.write_text("ALLOWED_USERS=111,222")
    monkeypatch.setattr("config.BASE_DIR", tmp_path)

    users = get_allowed_users()
    assert users == [111, 222]

    # Dynamically edit .env file
    env_file.write_text("ALLOWED_USERS=111,222,333")
    users_updated = get_allowed_users()
    assert users_updated == [111, 222, 333]
