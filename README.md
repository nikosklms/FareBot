# FareBot

A Telegram bot that watches Google Flights for you. Search a route, track it until it drops under your budget, or scan a whole region for the best deals from your airport.

<p align="center">
  <img src="assets/demo.gif" width="320" alt="Running /explore from Budapest to Europe: the wizard, a live progress bar, the biggest discounts (€17 to Venice, 83% off), then that flight opened on Google Flights at the same price">
</p>

## What it does

- **`/search`** finds the cheapest flights for a date or a date range and flags fares well below their usual price.
- **`/track`** checks a route every 6, 12 or 24 hours and messages you when it drops under your budget.
- **`/explore`** searches every destination in a region (Europe, Asia, the Greek islands and more) and ranks them by price or by discount.
- **`/digest`** runs an explore search every week and sends you the results at a time you pick.
- **`/mytracks`** lists your trackers and digests. You can edit, pause, share or delete them.

FareBot is meant to be self-hosted for yourself and a few friends. Anyone else who messages it sends you an access request, which you approve or deny with one tap. It doesn't need an API key: it reads the same data the Google Flights website shows, using [fast-flights](https://github.com/AWeirdDev/flights).

## Setup

You need Python 3.10 or newer and a bot token from [@BotFather](https://t.me/BotFather).

```bash
git clone https://github.com/nikosklms/FareBot.git
cd FareBot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put your token and your Telegram user ID in `.env` ([@userinfobot](https://t.me/userinfobot) tells you your ID), then start the bot:

```bash
python main.py
```

| Variable | Meaning |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather. |
| `ALLOWED_USERS` | Comma-separated Telegram user IDs that always have access. The first one is the admin: it gets access requests with Approve and Deny buttons, and `/users` lists everyone and lets you remove people. Changes apply without a restart. |
| `TIMEZONE` | Timezone for digest delivery times, e.g. `Europe/Athens`. Defaults to the server's. |
| `FAREBOT_DB_PATH` | SQLite file. Defaults to `farebot.db` in the project folder. |

## Shortcuts

Every command walks you through its options with buttons, or takes them in one line:

```text
/search ATH LON 2026-09-01..2026-09-15 direct
/track ATH LON 2026-09-01 150 direct
/explore ATH europe 30 100 10        # origin, region, days ahead, budget (0 = any), results
/digest ATH europe 30 80 Sunday@15:00 10
```

## How it works

Each search is one request to Google Flights for one route and one day, so a single `/explore` can send hundreds. The bot runs 5 at a time, which comes to about 430 searches a minute without being rate-limited (measured with `tools/benchmark.py`). Long searches run in the background with a progress bar and a Stop button, so the bot keeps answering meanwhile. Results are cached for 30 minutes and shared between users, and identical searches running at the same time share one request, so repeated or overlapping searches don't go to Google again. If Google rate-limits the bot, every request pauses for a minute instead of retrying straight away, and the pause doubles (up to 15 minutes) while the blocks continue.

Trackers and digests are scheduled jobs that are reloaded from SQLite on startup.

| Path | Contents |
| --- | --- |
| `bot/handlers/` | One module per command. The wizards share steps from `bot/wizard.py`. |
| `bot/formatting.py` | Message text. |
| `daemon/scheduler.py` | Tracker checks, weekly digests and nightly cleanup. |
| `database/` | SQLite access, models and migrations. |
| `providers/fast_flights.py` | Google Flights requests and parsing. |
| `services/` | Deal ranking, airport data and airport name search. |

## Development

```bash
pip install -r requirements-dev.txt
pytest                      # drives the real bot through a fake Telegram API, no token or network needed
pytest -m live              # also runs real Google Flights searches
ruff check .
python -m tools.benchmark   # searches per minute, request times and memory against Google Flights
```

## Limitations

- Google Flights has no public API. If Google changes its page format, searches fail until the parser is updated.
- Google limits how fast you can search, so trackers check every 6 hours at most.
- One-way flights only.
- FareBot isn't affiliated with Google. Use it for personal projects.

## License

[MIT](LICENSE)
