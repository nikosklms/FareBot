from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo

from telegram.ext import ContextTypes

from database.db import Database
from providers.base import AbstractFlightProvider
from services.resolver import LocationResolver

SERVICES_KEY = "services"


@dataclass
class Services:
    """Long-lived dependencies shared by handlers and jobs, created once in main."""
    db: Database
    provider: AbstractFlightProvider
    resolver: LocationResolver
    timezone: tzinfo
    shutting_down: bool = False  # set on Ctrl+C so cancelled searches can say why they stopped
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    digest_runs: dict = field(default_factory=dict)  # digest id -> local date it last ran


def get_services(context: ContextTypes.DEFAULT_TYPE) -> Services:
    return context.bot_data[SERVICES_KEY]
