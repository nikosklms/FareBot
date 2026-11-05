from datetime import timezone

import pytest

from bot.services import Services
from database.db import Database
from main import build_application
from services.resolver import LocationResolver
from tests.fakes import USER_ID, BotHarness, FakeProvider, FakeTelegram


# Every module that imports get_allowed_users, so no test reads the real .env.
ALLOWED_USERS_IMPORTERS = ["bot.auth", "bot.handlers.access", "bot.handlers.limits", "bot.handlers.stats"]


@pytest.fixture(autouse=True)
def allowed_users(monkeypatch):
    for module in ALLOWED_USERS_IMPORTERS:
        monkeypatch.setattr(f"{module}.get_allowed_users", lambda: [USER_ID])


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.migrate()
    return database


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def services(db, provider):
    return Services(db=db, provider=provider, resolver=LocationResolver(), timezone=timezone.utc)


@pytest.fixture
async def bot(services):
    telegram = FakeTelegram()
    app = build_application(services, token="123:TEST", request=telegram)
    await app.initialize()
    yield BotHarness(app, telegram, services)
    await app.shutdown()
