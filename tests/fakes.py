"""Test doubles: a fake Telegram API, a fake flight provider and a harness that drives the real bot."""
import asyncio
import itertools
import json
import time
from datetime import date, timedelta
from typing import Any, Callable, Optional

from telegram import Update
from telegram.request import BaseRequest, RequestData

from bot.services import Services
from providers.base import AbstractFlightProvider, FlightOffer
from utils.date_parser import today_local

USER_ID = 123
BOT_USER = {"id": 999, "is_bot": True, "first_name": "FareBot", "username": "farebot"}


def future(days: int) -> str:
    """An ISO date `days` from today in the bot's timezone, so tests never go stale or disagree
    with the bot around midnight when TIMEZONE differs from the machine's."""
    return (today_local() + timedelta(days=days)).isoformat()


class FakeTelegram(BaseRequest):
    """Answers Bot API calls locally and records them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.blocked_chats: set[int] = set()
        self.sending_fails = False  # simulate Telegram being unreachable for sendMessage
        self.failing: set[str] = set()  # endpoints that answer 400, e.g. {"setMyCommands"}
        self.last_message_id: Optional[int] = None
        self._message_ids = itertools.count(1000)

    @property
    def read_timeout(self) -> float:
        return 1.0

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def do_request(self, url: str, method: str, request_data: Optional[RequestData] = None,
                         *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        endpoint = url.rsplit("/", 1)[1]
        params = request_data.parameters if request_data else {}
        self.calls.append((endpoint, params))
        if endpoint in self.failing:
            return 400, json.dumps({"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}).encode()
        if self.sending_fails and endpoint == "sendMessage":
            return 502, json.dumps({"ok": False, "error_code": 502, "description": "Bad Gateway"}).encode()
        if params.get("chat_id") in self.blocked_chats:
            error = {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
            return 403, json.dumps(error).encode()
        result: Any = True
        if endpoint == "getUpdates":
            await asyncio.sleep(0.2)  # a real server holds the request open; avoid a busy loop
            result = []
        elif endpoint == "getMe":
            result = BOT_USER
        elif endpoint in ("sendMessage", "editMessageText", "editMessageReplyMarkup"):
            result = {
                "message_id": params.get("message_id") or next(self._message_ids),
                "date": int(time.time()),
                "chat": {"id": params.get("chat_id", USER_ID), "type": "private"},
                "from": BOT_USER,
                "text": params.get("text", ""),
            }
        if isinstance(result, dict) and "message_id" in result:
            self.last_message_id = result["message_id"]
        return 200, json.dumps({"ok": True, "result": result}).encode()

    def calls_to(self, *endpoints: str) -> list[dict[str, Any]]:
        return [params for endpoint, params in self.calls if endpoint in endpoints]

    @property
    def texts(self) -> list[str]:
        """Text of every message sent or edited, oldest first."""
        return [p["text"] for p in self.calls_to("sendMessage", "editMessageText")]

    @property
    def last_text(self) -> str:
        return self.texts[-1]

    def last_buttons(self) -> list[tuple[str, str]]:
        """(label, callback_data or url) of the most recent inline keyboard."""
        for endpoint, params in reversed(self.calls):
            markup = params.get("reply_markup")
            if markup and endpoint in ("sendMessage", "editMessageText", "editMessageReplyMarkup"):
                if isinstance(markup, str):
                    markup = json.loads(markup)
                return [(b["text"], b.get("callback_data") or b.get("url"))
                        for row in markup["inline_keyboard"] for b in row]
        return []

    def button_data(self, label_part: str) -> str:
        matches = [data for label, data in self.last_buttons() if label_part in label]
        assert matches, f"No button containing {label_part!r} in {self.last_buttons()}"
        return matches[0]

    @property
    def alerts(self) -> list[str]:
        return [p.get("text", "") for p in self.calls_to("answerCallbackQuery")]


class FakeProvider(AbstractFlightProvider):
    """Returns offers from a function of (origin, destination, date); records each query."""

    concurrency = 3

    def __init__(self, offers: Optional[Callable[[str, str, str], list[FlightOffer]]] = None) -> None:
        self.offers = offers or (lambda origin, destination, day: [])
        self.queries: list[tuple[str, str, str, bool]] = []

    def average_latency(self) -> float:
        return 0.01

    async def search_flights(self, origin, destination, departure_date, return_date=None, currency="EUR",
                             direct_only=False) -> list[FlightOffer]:
        self.queries.append((origin, destination, departure_date, direct_only))
        offers = self.offers(origin, destination, departure_date)
        return sorted((o for o in offers if o.is_direct or not direct_only), key=lambda o: o.price)

    async def search_flights_range(self, origin, destination, start_date, end_date, currency="EUR",
                                   direct_only=False) -> list[FlightOffer]:
        current, last, offers = date.fromisoformat(start_date), date.fromisoformat(end_date), []
        while current <= last:
            offers += await self.search_flights(origin, destination, current.isoformat(), direct_only=direct_only)
            current += timedelta(days=1)
        return sorted(offers, key=lambda o: o.price)


class BotHarness:
    """Feeds updates through the real Application, as if a user were chatting with the bot."""

    def __init__(self, app, telegram: FakeTelegram, services: Services) -> None:
        self.app = app
        self.telegram = telegram
        self.services = services
        self._ids = itertools.count(1)

    @property
    def user_data(self) -> dict:
        return self.app.user_data[USER_ID]

    def jobs(self, prefix: str = "") -> list[str]:
        return [job.name for job in self.app.job_queue.jobs() if job.name.startswith(prefix)]

    async def send(self, text: str, user_id: int = USER_ID, edited: bool = False) -> None:
        """A new message, or with edited=True the update Telegram sends when a message is edited."""
        message = {
            "message_id": next(self._ids),
            "date": int(time.time()),
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Test", "username": "tester"},
            "text": text,
        }
        if text.startswith("/"):
            command = text.split()[0]
            message["entities"] = [{"type": "bot_command", "offset": 0, "length": len(command)}]
        if edited:
            message["edit_date"] = int(time.time())
        kind = "edited_message" if edited else "message"
        await self.app.process_update(Update.de_json({"update_id": next(self._ids), kind: message}, self.app.bot))

    async def press(self, data: str, user_id: int = USER_ID, message_id: Optional[int] = None) -> None:
        """Press a button; by default on the bot's latest message, as a user would."""
        message_id = message_id or self.telegram.last_message_id or 1
        query = {
            "id": str(next(self._ids)),
            "chat_instance": "chat",
            "data": data,
            "from": {"id": user_id, "is_bot": False, "first_name": "Test", "username": "tester"},
            "message": {
                "message_id": message_id,
                "date": int(time.time()),
                "chat": {"id": user_id, "type": "private"},
                "from": BOT_USER,
                "text": "previous bot message",
            },
        }
        await self.app.process_update(Update.de_json({"update_id": next(self._ids), "callback_query": query}, self.app.bot))

    async def finish_background_task(self) -> None:
        task = self.user_data.get("running_task")
        if task:
            await task
