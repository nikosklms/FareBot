import pytest
from unittest.mock import MagicMock

@pytest.fixture(autouse=True)
def setup_test_allowed_users(monkeypatch):
    """Ensure mock user IDs in unit tests pass authorization, except explicit unauthorized test IDs."""
    class TestAllowedUsers(list):
        def __contains__(self, item):
            if item in (99999999, 77777):  # Explicitly unauthorized test IDs for test_auth.py
                return False
            if isinstance(item, MagicMock) or item is None:
                return True
            if item in (42, 55, 100, 999, 123456789, 987654321):
                return True
            return super().__contains__(item)

    test_users = TestAllowedUsers([123456789, 987654321])
    monkeypatch.setattr("config.get_allowed_users", lambda: test_users)
    monkeypatch.setattr("config.ALLOWED_USERS", test_users)
    monkeypatch.setattr("bot.handlers.auth.get_allowed_users", lambda: test_users)
    monkeypatch.setattr("bot.handlers.auth.ALLOWED_USERS", test_users)
