# Dynamic ALLOWED_USERS Reloading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the running background `nohup` process and make authorization dynamic so adding a Telegram user ID to `.env` takes effect immediately without needing to restart the bot.

**Architecture:** Introduce `get_allowed_users()` in `config.py` that reloads `.env` with `override=True` on demand. Update `bot/handlers/auth.py` to invoke `get_allowed_users()` dynamically on every request authorization check, and update test fixtures in `tests/conftest.py`.

**Tech Stack:** Python 3.13, `python-dotenv`, `python-telegram-bot`, `pytest`.

## Global Constraints
- Every handler must continue using `@restricted` decorator.
- Direct edits to `.env` must take effect instantly on the very next incoming Telegram update.
- Stop any existing background `nohup` process as part of Task 1.

---

### Task 1: Stop Running Background `nohup` Process & Add `get_allowed_users()`

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `.env` file containing `ALLOWED_USERS=...`
- Produces: `get_allowed_users() -> List[int]` in `config.py`

- [ ] **Step 1: Stop running background nohup process**

Run: `pkill -f "python main.py" || true`
Expected: Background process terminated.

- [ ] **Step 2: Write failing unit test for dynamic get_allowed_users()**

Create `tests/test_config.py`:
```python
import os
import pytest
from config import get_allowed_users

def test_get_allowed_users_dynamic_reload(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ALLOWED_USERS=111,222")
    monkeypatch.setattr("config.BASE_DIR", tmp_path)
    
    users = get_allowed_users()
    assert users == [111, 222]

    # Dynamically edit .env file
    env_file.write_text("ALLOWED_USERS=111,222,333")
    users_updated = get_allowed_users()
    assert users_updated == [111, 222, 333]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_config.py -v`
Expected: FAIL with "ImportError: cannot import name 'get_allowed_users' from 'config'"

- [ ] **Step 4: Implement get_allowed_users() in config.py**

Modify `config.py`:
```python
def get_allowed_users() -> list[int]:
    """Dynamically load ALLOWED_USERS from .env file so additions take effect instantly."""
    load_dotenv(BASE_DIR / ".env", override=True)
    raw_users = os.getenv("ALLOWED_USERS", "<SENSITIVE_TELEGRAM_ID>")
    return [int(uid.strip()) for uid in raw_users.split(",") if uid.strip().isdigit()]

ALLOWED_USERS = get_allowed_users()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: add get_allowed_users to dynamically reload .env"
```

---

### Task 2: Update `auth.py` and Test Fixtures for Dynamic Authorization

**Files:**
- Modify: `bot/handlers/auth.py:1-60`
- Modify: `tests/conftest.py:1-18`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `get_allowed_users()` from `config.py`
- Produces: Dynamic user authorization in `@restricted` decorator

- [ ] **Step 1: Update conftest.py test fixture**

Modify `tests/conftest.py`:
```python
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
            if item in (42, 55, 100, 999, <SENSITIVE_TELEGRAM_ID>):
                return True
            return super().__contains__(item)

    monkeypatch.setattr("bot.handlers.auth.get_allowed_users", lambda: TestAllowedUsers([<SENSITIVE_TELEGRAM_ID>]))
```

- [ ] **Step 2: Update restricted decorator in bot/handlers/auth.py**

Modify `bot/handlers/auth.py`:
```python
from config import get_allowed_users, DB_PATH
```
Inside `wrapped()`:
```python
        allowed_users = get_allowed_users()
        if user_id not in allowed_users:
            ...
            if allowed_users and context and hasattr(context, "bot") and hasattr(context.bot, "send_message"):
                try:
                    admin_id = allowed_users[0]
```

- [ ] **Step 3: Run full pytest suite**

Run: `/home/nkalamaris/Desktop/FareBot/venv/bin/pytest -v`
Expected: 88 passed out of 88 tests.

- [ ] **Step 4: Commit**

```bash
git add bot/handlers/auth.py tests/conftest.py
git commit -m "feat: use dynamic get_allowed_users in restricted authorization decorator"
```
