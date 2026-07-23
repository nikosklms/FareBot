import pytest
from unittest.mock import MagicMock

@pytest.fixture(autouse=True)
def setup_test_allowed_users(monkeypatch):
    """Ensure mock user IDs in unit tests pass authorization, except explicit unauthorized test IDs."""
    class TestAllowedUsers(list):
        def __contains__(self, item):
            if item == 99999999:  # Explicitly unauthorized test ID for test_auth.py
                return False
            if isinstance(item, MagicMock) or item is None:
                return True
            if item in (42, 55, 100, 999, 123456789):
                return True
            return super().__contains__(item)

    monkeypatch.setattr("bot.handlers.auth.ALLOWED_USERS", TestAllowedUsers([123456789]))
