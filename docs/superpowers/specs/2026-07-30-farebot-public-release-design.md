# FareBot Public Release Design Specification

Date: 2026-07-30
Topic: Polishing and Sanitizing FareBot for Public GitHub Release

## Overview

FareBot is an open-source Telegram bot for monitoring flight prices via Google Flights and sending automated price drop notifications. This specification outlines the changes required to sanitize sensitive historical data from Git commits, update default configurations, add an open-source MIT license, and write a high-quality, developer-focused README document.

---

## Requirements & Constraints

1. **Git History Sanitization**:
   - Strip out hardcoded personal Telegram User ID (`<SENSITIVE_TELEGRAM_ID>`) from historical commits using `git rebase` / commit editing.
   - Preserve 100% of existing commit history, commit messages, author metadata, and timestamps.

2. **Codebase & Privacy Sanitization**:
   - Update default fallback of `ALLOWED_USERS` in `config.py` from `"<SENSITIVE_TELEGRAM_ID>"` to `""`.
   - Verify `.env.example` lists all required environment variables with dummy values.
   - Ensure `.env`, SQLite databases (`*.db`), log files (`*.log`), and virtual environments are excluded via `.gitignore`.

3. **Licensing & Legal**:
   - Include a root `LICENSE` file containing the standard MIT License.
   - Include a clear educational/non-commercial disclaimer regarding Google Flights data scraping in the README.

4. **README Specification**:
   - **No emojis anywhere**.
   - **No badges** (no CI/coverage badges).
   - **No em dashes** and **no Oxford commas**.
   - Voice: Plain, direct, technical. Second person for instructions. Active voice, present tense. Maximum 3 sentences per paragraph.
   - Structure: Description, features, requirements, installation, quick start, configuration, usage, project structure, limitations, license.
   - Tables over prose for environment variables and CLI parameters.
   - Length: 150 to 400 lines. Fully copy-pasteable runnable commands using exact codebase values.

---

## Design Components

### Component 1: Git History Sanitization
- Identify target commits containing `<SENSITIVE_TELEGRAM_ID>` (`c18205e` and `750c6be`).
- Perform git rebase to update `config.py` and plan documents in those commits.
- Verify `git log -S "<SENSITIVE_TELEGRAM_ID>"` returns 0 results across all branches.

### Component 2: Codebase Configuration Updates
- Modify `config.py`:
  ```python
  def get_allowed_users() -> list[int]:
      load_dotenv(BASE_DIR / ".env", override=True)
      raw_users = os.getenv("ALLOWED_USERS", "")
      return [int(uid.strip()) for uid in raw_users.split(",") if uid.strip().isdigit()]
  ```
- Check `.env.example` content:
  ```env
  TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
  ALLOWED_USERS=123456789,987654321
  FAREST_DB_PATH=farebot.db
  ```

### Component 3: Licensing (`LICENSE`)
- Add root `LICENSE` containing the MIT license text assigned to the repository owner.

### Component 4: README (`README.md`)
- Draft `README.md` following all strict voice, formatting, and structural constraints outlined in the requirements.

---

## Verification Plan

### Manual & Automated Verification
1. Run `git log -S "<SENSITIVE_TELEGRAM_ID>"` to confirm no occurrences exist in any commit.
2. Run `pytest` to confirm all existing unit and integration tests pass cleanly after configuration changes.
3. Validate `README.md` line count (between 150 and 400 lines) and verify absence of emojis, em dashes, or Oxford commas.
