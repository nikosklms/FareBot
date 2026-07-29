# FareBot Public Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sanitize Git history, update codebase default configuration, create canonical MIT LICENSE file, and draft a high-accuracy, developer-focused README document for public GitHub release.

**Architecture:** Perform git commit rebase/editing to sanitize past commits without losing history or timestamps; update config fallbacks; add canonical MIT License; draft a README adhering strictly to voice, formatting, structural, and accuracy constraints.

**Tech Stack:** Python 3.10+, Git, pytest, python-telegram-bot, fast-flights, SQLite.

## Global Constraints

- No emojis anywhere in documentation or code.
- No badges (no CI or coverage badges).
- No em dashes and no Oxford commas in documentation.
- Voice: Plain, direct, technical. Second person for instructions. Active voice, present tense. Maximum 3 sentences per paragraph.
- Banned adjectives: powerful, seamless, blazingly fast, robust, elegant, effortless.
- All commands in README runnable as written.
- Every documented parameter, default, and command derived strictly from the codebase.
- No literal personal Telegram User IDs in repository documentation or plan files.

---

### Task 1: Codebase & Git History Sanitization

**Files:**
- Modify: `config.py:16-22`
- Modify: `.env.example:1-3`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Existing `config.get_allowed_users()` function and git history.
- Produces: Sanitized git history with zero instances of sensitive Telegram User ID, and `config.py` defaulting to `""`.

- [ ] **Step 1: Write failing test in `tests/test_config.py`**

Add test to `tests/test_config.py` verifying fallback `ALLOWED_USERS` default is empty when `.env` is absent:

```python
def test_get_allowed_users_default_empty(monkeypatch):
    monkeypatch.delenv("ALLOWED_USERS", raising=False)
    from config import get_allowed_users
    assert get_allowed_users() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_get_allowed_users_default_empty -v`
Expected: FAIL with `assert [...] == []`

- [ ] **Step 3: Modify `config.py` default fallback**

In `config.py`, line 19, change sensitive user ID string to `""`:

```python
def get_allowed_users() -> list[int]:
    """Dynamically load ALLOWED_USERS from .env file so additions take effect instantly."""
    load_dotenv(BASE_DIR / ".env", override=True)
    raw_users = os.getenv("ALLOWED_USERS", "")
    return [int(uid.strip()) for uid in raw_users.split(",") if uid.strip().isdigit()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Sanitize historical Git commits**

Run `git rebase -i --root` to edit past commits containing the sensitive Telegram User ID. In `config.py` and documentation plan commits, replace the sensitive Telegram User ID with `""` or `<SENSITIVE_TELEGRAM_ID>`.

- [ ] **Step 6: Verify Git history sanitization**

Run: `git log -S "<SENSITIVE_TELEGRAM_ID_NUMERIC>" --oneline`
Expected: Empty output (0 results found across all commits).

- [ ] **Step 7: Commit changes**

```bash
git add config.py tests/test_config.py .env.example
git commit -m "fix: sanitize default allowed users config fallback"
```

---

### Task 2: Canonical MIT License Creation

**Files:**
- Create: `LICENSE`

**Interfaces:**
- Consumes: Canonical MIT License template.
- Produces: Root `LICENSE` file for open-source compliance.

- [ ] **Step 1: Create `LICENSE` file**

Create `/home/nkalamaris/Desktop/FareBot/LICENSE` with exact canonical MIT License text:

```text
MIT License

Copyright (c) 2026 nikosklms

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Verify `LICENSE` file canonical text**

Run: `cat LICENSE`
Expected: Canonical MIT License text matching standard OSI definition.

- [ ] **Step 3: Commit `LICENSE` file**

```bash
git add LICENSE
git commit -m "docs: add MIT license"
```

---

### Task 3: Developer-Focused & Portfolio README Document

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: Codebase inspection results (`main.py`, `config.py`, `bot/handlers/*.py`, `daemon/scheduler.py`, `services/resolver.py`, `requirements.txt`).
- Produces: Complete, runnable, highly accurate `README.md` document (150-400 lines).

- [ ] **Step 1: Codebase inspection & environment variable diffing**

Extract every `os.getenv` call across the codebase:
Run: `grep -rn "os.getenv" .`
Map out `TELEGRAM_BOT_TOKEN`, `ALLOWED_USERS`, `FAREST_DB_PATH`, `PORT`, and default polling intervals (`DEFAULT_POLL_INTERVAL_HOURS = 6`). Verify 100% two-way match between code definitions and the configuration table.

- [ ] **Step 2: Draft `README.md`**

Draft `/home/nkalamaris/Desktop/FareBot/README.md` following all strict voice, structure, accuracy, and hard rules:
- Name and one-line description
- Problem and audience paragraph
- Features list
- Requirements (Python 3.10+)
- Installation steps
- Quick start (shortest path to a running bot in one copy-pasteable block)
- Configuration table (derived strictly from `os.getenv` diffing)
- Usage guide (Telegram bot commands)
- Project structure
- Development and testing instructions
- Limitations and known gaps
- Educational / non-commercial Google Flights disclaimer
- Contributing
- License (MIT)

- [ ] **Step 3: Verify formatting and rules compliance**

Check line count: `wc -l README.md` (must be between 150 and 400).
Run rule verification commands:
- Unicode emoji check: `python3 -c "import re, sys; text = open('README.md').read(); sys.exit(0 if not re.search(r'[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]', text) else 1)"`
- Em dash check: `grep '—' README.md` (0 results)
- Badge check: `grep '\!\[.*\]\(.*\)' README.md` (0 results)
- Banned adjective check: `grep -iE 'powerful|seamless|blazingly fast|robust|elegant|effortless' README.md` (0 results)

- [ ] **Step 4: Execute Quick start commands in a clean test execution**

Run installation and setup commands sequentially to verify complete execution without undocumented steps.

- [ ] **Step 5: Commit `README.md`**

```bash
git add README.md
git commit -m "docs: add developer-focused README"
```
