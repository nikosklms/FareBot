# FareBot Public Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sanitize Git history, update codebase default configuration, create an MIT LICENSE file, and draft a high-accuracy, developer-focused README document for public GitHub release.

**Architecture:** Perform git commit rebase/editing to sanitize past commits without losing history or timestamps; update config fallbacks; add an MIT License; draft a README adhering strictly to voice, formatting, structural, and accuracy constraints.

**Tech Stack:** Python 3.10+, Git, pytest, python-telegram-bot, fast-flights, SQLite.

## Global Constraints

- No emojis anywhere in documentation or code.
- No badges (no CI or coverage badges).
- No em dashes and no Oxford commas in documentation.
- Voice: Plain, direct, technical. Second person for instructions. Active voice, present tense. Maximum 3 sentences per paragraph.
- Banned adjectives: powerful, seamless, blazingly fast, robust, elegant, effortless.
- All commands in README runnable as written.
- Every documented parameter, default, and command derived strictly from the codebase.

---

### Task 1: Codebase & Git History Sanitization

**Files:**
- Modify: `config.py:16-22`
- Modify: `.env.example:1-3`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Existing `config.get_allowed_users()` function and git history.
- Produces: Sanitized git history with zero instances of Telegram User ID `<SENSITIVE_TELEGRAM_ID>`, and `config.py` defaulting to `""`.

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
Expected: FAIL with `assert [<SENSITIVE_TELEGRAM_ID>] == []`

- [ ] **Step 3: Modify `config.py` default fallback**

In `config.py`, line 19, change `"<SENSITIVE_TELEGRAM_ID>"` to `""`:

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

Run `git rebase -i --root` or `git filter-repo` to replace `<SENSITIVE_TELEGRAM_ID>` with `""` in past commits (`750c6be` and `c18205e`).

- [ ] **Step 6: Verify Git history sanitization**

Run: `git log -S "<SENSITIVE_TELEGRAM_ID>" --oneline`
Expected: Empty output (0 results found across all commits).

- [ ] **Step 7: Commit changes**

```bash
git add config.py tests/test_config.py .env.example
git commit -m "fix: sanitize default allowed users config fallback"
```

---

### Task 2: MIT License Creation

**Files:**
- Create: `LICENSE`

**Interfaces:**
- Consumes: Standard MIT License template.
- Produces: Root `LICENSE` file for open-source compliance.

- [ ] **Step 1: Create `LICENSE` file**

Create `/home/nkalamaris/Desktop/FareBot/LICENSE` with MIT License text:

```text
MIT License

Copyright (a) 2026 nikosklms

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction handling, including without limitation the rights
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

- [ ] **Step 2: Verify `LICENSE` file exists**

Run: `cat LICENSE`
Expected: MIT License text displayed.

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

- [ ] **Step 1: Codebase inspection for exact parameters & commands**

Verify all `os.getenv` environment variables (`TELEGRAM_BOT_TOKEN`, `ALLOWED_USERS`, `FAREST_DB_PATH`, `PORT`), default polling intervals (`DEFAULT_POLL_INTERVAL_HOURS = 6`), bot commands (`/start`, `/search`, `/track`, `/dashboard`, `/cancel`), and dependencies.

- [ ] **Step 2: Write `README.md`**

Draft `/home/nkalamaris/Desktop/FareBot/README.md` following all strict voice, structure, accuracy, and hard rules:
- Name and one-line description
- Problem and audience paragraph
- Features list
- Requirements (Python 3.10+)
- Installation steps
- Quick start (shortest path to a running bot)
- Configuration table
- Usage guide (Telegram bot commands)
- Project structure
- Development and testing instructions
- Limitations and known gaps
- Educational / non-commercial Google Flights disclaimer
- Contributing
- License (MIT)

- [ ] **Step 3: Verify formatting and rules compliance**

Check line count: `wc -l README.md` (must be between 150 and 400).
Check for prohibited items:
- Search for emojis: `grep -P '[\x{1F600}-\x{1F64F}]' README.md` (0 results)
- Search for em dashes: `grep '—' README.md` (0 results)
- Search for badges: `grep '\!\[.*\]\(.*\)' README.md` (0 results)
- Search for banned adjectives: `grep -iE 'powerful|seamless|blazingly fast|robust|elegant|effortless' README.md` (0 results)

- [ ] **Step 4: Execute Quick start commands in shell**

Run installation commands sequentially to verify clean execution.

- [ ] **Step 5: Commit `README.md`**

```bash
git add README.md
git commit -m "docs: add developer-focused README"
```
