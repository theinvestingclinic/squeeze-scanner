import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import settings

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="America/New_York")


def _is_market_hours() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    # Monday–Friday, 9:30 AM–4:30 PM ET
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


async def _scheduled_scan():
    if not _is_market_hours():
        log.info("Outside market hours — skipping scheduled scan")
        return
    log.info("Running scheduled scan")
    from scanner import run_full_scan
    await run_full_scan(alert_threshold=settings.alert_threshold)


def start_scheduler():
    interval = settings.scan_interval_minutes
    scheduler.add_job(
        _scheduled_scan,
        trigger=CronTrigger(minute=f"*/{interval}"),
        id="full_scan",
        replace_existing=True,
        misfire_grace_time=120,
    )
    scheduler.start()
    log.info(f"Scheduler started — scan every {interval} minutes during market hours")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
