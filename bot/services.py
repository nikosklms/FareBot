from dataclasses import dataclass
from datetime import tzinfo

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


def get_services(context: ContextTypes.DEFAULT_TYPE) -> Services:
    return context.bot_data[SERVICES_KEY]
