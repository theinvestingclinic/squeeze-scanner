import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from config import settings
from market_calendar import is_scan_window

log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="America/New_York")


async def _scheduled_scan():
    if not is_scan_window():
        log.info("Skipping scheduled scan: U.S. equity market is closed")
        return
    log.info("Running scheduled scan")
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
    # First scan begins after the opening auction.  Subsequent jobs remain on a
    # 30-minute cadence and the runtime calendar skips holidays/early closes.
    scheduler.add_job(
        _scheduled_scan,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=40),
        id="opening_scan",
        replace_existing=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        _scheduled_scan,
        trigger=CronTrigger(day_of_week="mon-fri", hour="10-15", minute="10,40"),
        id="intraday_scan",
        replace_existing=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        _scheduled_scan,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=0),
        id="closing_scan",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # FINRA discovery weekdays at 8:30 AM ET
    scheduler.add_job(
        _scheduled_discovery,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=30),
        id="ticker_discovery",
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    log.info(
        "Scheduler started — scans 9:40 AM-4:00 PM ET on open market days; "
        "discovery at 8:30 AM ET"
    )


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
