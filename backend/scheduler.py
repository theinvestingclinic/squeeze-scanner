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


async def _scheduled_discovery():
    """Run FINRA ticker discovery every morning at 8:30 AM ET before market open."""
    log.info("Running daily ticker discovery")
    from ticker_discovery import run_discovery
    from database import SessionLocal
    db = SessionLocal()
    try:
        new_tickers = await run_discovery(db)
        if new_tickers:
            log.info(f"Discovery added {len(new_tickers)} new tickers: {new_tickers[:10]}")
    finally:
        db.close()


def start_scheduler():
    interval = settings.scan_interval_minutes

    scheduler.add_job(
        _scheduled_scan,
        trigger=CronTrigger(minute=f"*/{interval}"),
        id="full_scan",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # Run discovery every weekday at 8:30 AM ET (before market open)
    scheduler.add_job(
        _scheduled_discovery,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=30),
        id="ticker_discovery",
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    log.info(f"Scheduler started — scan every {interval} min, discovery daily at 8:30 AM ET")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
