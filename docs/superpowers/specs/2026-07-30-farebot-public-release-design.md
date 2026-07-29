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
   - Ensure design and plan documents in `docs/superpowers/` use `<SENSITIVE_TELEGRAM_ID>` instead of the literal ID to prevent re-introducing it to Git history.

2. **Codebase & Privacy Sanitization**:
   - Update default fallback of `ALLOWED_USERS` in `config.py` from `"<SENSITIVE_TELEGRAM_ID>"` to `""`.
   - Verify `.env.example` lists all required environment variables with dummy values.
   - Ensure `.env`, SQLite databases (`*.db`), log files (`*.log`), and virtual environments are excluded via `.gitignore`.

3. **Licensing & Legal**:
   - Include a root `LICENSE` file containing canonical MIT License text.
   - Include a clear educational/non-commercial disclaimer regarding Google Flights data scraping in the README.

4. **README Specification**:

**Purpose**: The README decides whether a developer uses FareBot or closes the tab. It answers three questions in order: what this does, whether it fits my problem, how do I run it. Everything else sits lower down or gets cut.

**Opening**: The first three lines carry the most weight. Project name, one line on what the bot does, then a short paragraph on the problem it solves and who it is for. Concrete and specific: name the manual workflow it replaces. No mission statement, no project history, no "in today's fast-paced world".

**Structure** (in this order, omitting any section that does not apply):
- Name and one-line description
- Problem and audience paragraph
- Features
- Requirements
- Installation
- Quick start: shortest path to a running bot that sends one notification, in one copy-pasteable block
- Configuration
- Usage
- Project structure (only if the layout is non-obvious)
- Development and testing
- Limitations and known gaps
- Disclaimer (educational/non-commercial use, Google Flights scraping)
- Contributing
- License

**Voice**: Plain, direct, technical. Second person for instructions. Active voice, present tense. Maximum 3 sentences per paragraph. Professional without being stiff, confident without overselling.

**Hard formatting rules**:
- No emojis anywhere
- No badges (no CI or coverage badges)
- No em dashes, no Oxford commas
- Tables over prose for environment variables and CLI parameters
- Headings scannable enough that a reader finds what they need in under ten seconds

**Banned language**: Cut every sentence that carries no information. Cut every adjective that is not measurable. The words powerful, seamless, blazingly fast, robust, elegant and effortless are prohibited unless followed by a number that proves them.

**Accuracy**: Document only what is verified in the codebase. Never document a flag, function, default or behavior inferred from convention or from a similar project. State broken or half-finished behavior in the Limitations section rather than papering over it. Accuracy beats completeness.

**Length**: 150 to 400 lines. Fully copy-pasteable runnable commands using exact codebase values. Placeholders only where the value is genuinely user-specific, such as the bot token. If the draft runs long, cut content rather than relocating it to another file.

**Done means**: A developer who has never seen FareBot gets it running from this document alone, every command and documented variable matches the code, and nothing can be deleted without losing information.

---

## Design Components

### Component 1: Git History Sanitization
- Identify target commits containing the sensitive Telegram User ID.
- Perform git rebase to update `config.py` and plan documents in those commits.
- Verify `git log -S "<SENSITIVE_TELEGRAM_ID_NUMERIC>"` returns 0 results across all branches.

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
- Add root `LICENSE` containing canonical MIT license text assigned to copyright holder `nikosklms`.

### Component 4: README (`README.md`)
- Read the codebase before drafting: entry point, command handlers, `config.py`, all `os.getenv` calls, CLI argument parsing, `requirements.txt` or `pyproject.toml`, and the test suite. Derive the feature list, requirements, environment variable table and CLI parameter table from these sources only.
- Draft `README.md` following every voice, formatting, structural and accuracy constraint in Requirement 4.
- Place the Google Flights educational/non-commercial disclaimer immediately after Limitations, as specified in Requirement 3.

---

## Verification Plan

### Manual & Automated Verification
1. Run `git log -S "<SENSITIVE_TELEGRAM_ID_NUMERIC>"` to confirm zero occurrences exist across all historical commits.
2. Run `pytest` to confirm all existing unit and integration tests pass cleanly after configuration changes.
3. Validate `README.md`:
   - Clone the repository into a clean directory and run every command in Installation and Quick start in order. The bot must reach a running state with no undocumented step.
   - Diff the environment variable table against every `os.getenv` call in the codebase (`grep -rn "os.getenv" .`). Names and defaults must match exactly, in both directions.
   - Diff the CLI parameter table against actual argument parser definitions.
   - Confirm no documented command, flag or default is absent from the code.
   - Confirm line count falls between 150 and 400.
   - Confirm absence of emojis using unicode range check `python3 -c "import re, sys; text = sys.stdin.read(); sys.exit(0 if not re.search(r'[\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf]', text) else 1)" < README.md`.
   - Confirm absence of badges, em dashes, Oxford commas, and banned adjectives.
   - Confirm the Disclaimer and License sections are present.