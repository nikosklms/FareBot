# FareBot

FareBot is an asynchronous Telegram bot that tracks Google Flights prices and notifies you when fares drop below your budget.

Searching flight prices manually across multiple dates requires checking Google Flights repeatedly and recording price changes by hand. FareBot replaces this workflow by automating recurring price searches in the background, storing historical offers in a local SQLite database and sending instant Telegram alerts when a matching fare is found. It is built for developers and self-hosters who want automated flight price monitoring without third-party subscriptions.

## Features

- Single-date and date-range flight search using Google Flights data parsed via fast-flights
- Automated background fare monitoring with configurable polling intervals
- Price drop notification alerts delivered directly via Telegram messages
- Whitelisted user authentication based on Telegram user IDs
- Embedded HTTP health check server for cloud deployments on Render or Railway
- SQLite persistent storage for active trackers and price history

## Requirements

- Python 3.10 or higher
- A Telegram bot token created via BotFather
- Your numeric Telegram User ID

## Installation

Clone the repository and install dependencies in a virtual environment:

```bash
git clone https://github.com/nikosklms/FareBot.git
cd FareBot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Quick Start

Copy `.env.example` to `.env` and set your credentials:

```bash
cp .env.example .env
```

Edit `.env` to supply your bot token and numeric Telegram user ID:

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
ALLOWED_USERS=123456789
FAREST_DB_PATH=farebot.db
PORT=10000
```

Start the bot:

```bash
python main.py
```

Send `/start` to your bot on Telegram to verify access.

## Configuration

FareBot reads configuration from environment variables loaded via `.env` at startup.

| Variable | Description | Default |
| --- | --- | --- |
| TELEGRAM_BOT_TOKEN | Telegram bot token obtained from BotFather | Empty string |
| ALLOWED_USERS | Comma-separated list of numeric Telegram User IDs allowed to use the bot | Empty string |
| FAREST_DB_PATH | File path for SQLite database storage | `farebot.db` inside root directory |
| PORT | Port number for the HTTP health check web server | `10000` |

Internal operational limits configured in `config.py`:

| Parameter | Value | Description |
| --- | --- | --- |
| MIN_POLL_INTERVAL_HOURS | 6 | Minimum allowed background polling interval in hours |
| DEFAULT_POLL_INTERVAL_HOURS | 6 | Default polling frequency for new price trackers |
| MAX_TRACKERS_PER_USER | 5 | Maximum active trackers permitted per user |
| MAX_CONSECUTIVE_FAILURES | 3 | Failed search attempts before a tracker is paused |

## Usage

Interact with FareBot using standard Telegram chat commands and interactive inline keyboards.

### Commands

| Command | Description |
| --- | --- |
| `/start` | Verify authorization and view bot status |
| `/help` | View command syntax and usage instructions |
| `/search` | Start flight search wizard for single dates or date ranges |
| `/track` | Create a recurring background price tracker |
| `/dashboard` | View active trackers, delete trackers or trigger manual price checks |
| `/cancel` | Cancel an ongoing wizard session |

### Flight Search Wizard

1. Send `/search ATH LON 2026-09-15` for a direct search, or send `/search` to open the interactive wizard.
2. Select origin airport, destination airport and departure date or date range.
3. Filter results by direct flights only or any number of stops.
4. Review the top flight offers formatted with price, airline, flight duration and booking links.

### Price Tracker Setup

1. Send `/track` to launch the tracking wizard.
2. Specify origin, destination, target departure date or date range, target price budget and polling interval.
3. FareBot saves the tracker to SQLite and registers a recurring background job.
4. When a search finds a flight price below your target budget, FareBot sends a Telegram alert with offer details.

## Project Structure

```text
FareBot/
├── main.py              # Application entry point and HTTP health server
├── config.py            # Configuration loader and environment variables
├── bot/
│   ├── handlers/        # Telegram command and callback handlers
│   │   ├── auth.py      # User authorization decorator and security logger
│   │   ├── search.py    # Flight search wizard and inline handlers
│   │   ├── track.py     # Price tracker creation wizard
│   │   └── dashboard.py # Active tracker management dashboard
├── daemon/
│   └── scheduler.py     # Background job scheduler and price alert dispatcher
├── database/
│   └── db.py            # SQLite database schema, queries and migrations
├── providers/
│   ├── base.py          # Abstract flight provider interface
│   └── fast_flights.py  # Google Flights fetcher integration
├── services/
│   ├── airports_data.py # Airport code dictionary and IATA lookups
│   └── resolver.py      # Airport and city query resolver
├── tests/               # Pytest unit and integration test suite
└── logs/                # Persistent security access logs
```

## Development and Testing

Run the test suite using pytest inside your virtual environment:

```bash
pytest -v
```

Run specific test files:

```bash
pytest tests/test_fast_flights.py -v
pytest tests/test_scheduler.py -v
pytest tests/test_auth.py -v
```

Test coverage includes unit tests for airport resolution, date parsing, database queries, authorization rules, search handlers and scheduler polling workflows.

## Limitations and Known Gaps

- Google Flights scraping depends on fast-flights and raw HTML JSON parsing. If Google updates internal payload structures, flight queries may fail until parser definitions are updated.
- Automated requests sent too frequently may trigger HTTP 429 rate limiting from Google Flights. The minimum poll interval is restricted to 6 hours to reduce block risks.
- Round-trip flight tracking is not currently supported; trackers monitor one-way travel segments.
- Payment processing or ticket booking is not handled directly by the bot. Users must click generated Google Flights links to complete purchases on external airline sites.

## Disclaimer

This project is an independent open-source tool created strictly for personal and educational use. It is not affiliated with, authorized by, endorsed by or sponsored by Google LLC or Google Flights. Users are responsible for complying with applicable terms of service when running personal automated queries.

## Contributing

Contributions are welcome. Submit pull requests or open GitHub issues for bug reports and feature requests. Ensure all pytest tests pass before submitting changes.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
