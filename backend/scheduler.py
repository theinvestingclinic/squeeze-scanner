import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import settings

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="America/New_York")


async def _scheduled_scan():
    log.info("Running daily scan")
    from scanner import run_full_scan
    await run_full_scan(alert_threshold=settings.alert_threshold)


async def _scheduled_discovery():
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
    # Full scan every morning at 6:00 AM ET, 7 days a week
    scheduler.add_job(
        _scheduled_scan,
        trigger=CronTrigger(hour=6, minute=0),
        id="full_scan",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # FINRA discovery weekdays at 8:30 AM ET (after prior day's data is posted)
    scheduler.add_job(
        _scheduled_discovery,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=30),
        id="ticker_discovery",
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    log.info("Scheduler started — scan daily at 6:00 AM ET, discovery weekdays at 8:30 AM ET")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
