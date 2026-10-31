"""Admin /stats: how much the bot searched since it started and how much the cache saved."""
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from bot.auth import admin_id
from bot.handlers.access import ADMIN_ONLY
from bot.services import Services, get_services
from config import get_allowed_users
from database.models import APPROVED, PENDING


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _share(part: int, whole: int) -> str:
    return f" ({part / whole:.0%})" if whole else ""


async def stats_text(services: Services, now: datetime) -> str:
    s = services.provider.stats()
    users = await services.db.list_users()
    trackers = await services.db.active_trackers()
    digests = await services.db.active_digests()
    started = services.started_at.astimezone(services.timezone)

    saved = s.from_cache + s.shared
    pause = (f"paused now, {_duration(s.paused_for)} left" if s.paused_for >= 60
             else f"paused now, {s.paused_for:.0f}s left" if s.paused_for > 0 else "not paused")
    speed = f", {s.average_latency:.2f}s each" if s.google_requests else ""
    return "\n".join([
        f"📈 <b>Stats</b> since {started:%d %b %H:%M} ({_duration((now - services.started_at).total_seconds())})",
        "",
        f"🔍 <b>Searches</b>: {s.searches}",
        f"• ♻️ Answered from the cache: {s.from_cache}{_share(s.from_cache, s.searches)}",
        f"• 🤝 Joined a search already running: {s.shared}{_share(s.shared, s.searches)}",
        f"• 💾 Saved in total: {saved}{_share(saved, s.searches)}",
        f"🌐 <b>Google requests</b>: {s.google_requests}{speed}",
        f"⏸️ <b>Rate-limit pauses</b>: {s.rate_limit_pauses} · {pause}",
        "",
        f"👥 <b>Users</b>: {len(get_allowed_users())} always allowed · "
        f"{sum(u.status == APPROVED for u in users)} approved · {sum(u.status == PENDING for u in users)} waiting",
        f"🔔 <b>Active</b>: {_count(len(trackers), 'tracker')} · {_count(len(digests), 'digest')}",
    ])


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != admin_id():
        await update.message.reply_text(ADMIN_ONLY)
        return
    await update.message.reply_text(await stats_text(get_services(context), datetime.now(timezone.utc)))


stats_handler = CommandHandler("stats", stats_command)
