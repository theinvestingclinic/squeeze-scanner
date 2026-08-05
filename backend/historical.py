"""
Historical stats for a ticker drawn from our own accumulated scan_results.
Used to z-score call volume, compute true OI delta, and build a real
30-day IV range — all without any paid data source.

Stats are unavailable until the scanner has accumulated enough distinct,
completed trading sessions for a ticker. Repeated intraday scans never count
as independent calibration samples. Scoring falls back to proxy calculations
until then.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import settings
from database import SessionLocal, ScanResult
from market_calendar import is_market_day
from sqlalchemy import desc


EASTERN = ZoneInfo("America/New_York")


def _session_date(scanned_at: datetime):
    timestamp = scanned_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(EASTERN).date()


def get_historical_stats(ticker: str) -> dict:
    """
    Query last 30 days of scan results for a ticker.

    Returns a dict with calibration values used by scoring.py:
        history_points      int   — observations from completed sessions
        history_sessions    int   — distinct completed trading sessions
        call_vol_mean       float — mean call_volume_ratio over history
        call_vol_std        float — std dev of call_volume_ratio
        call_oi_prev        float — most recent prior call_oi_pct_change
        iv_30d_min          float — min iv_percentile over 30 days
        iv_30d_max          float — max iv_percentile over 30 days

    Returns counts without calibration keys until CALIBRATION_MIN_SESSIONS
    distinct completed sessions exist.
    """
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=30)
        rows = (
            db.query(ScanResult)
            .filter(ScanResult.ticker == ticker, ScanResult.scanned_at >= cutoff)
            .order_by(desc(ScanResult.scanned_at))
            .limit(500)
            .all()
        )

        current_session = datetime.now(EASTERN).date()
        completed_rows = []
        rows_by_session = {}
        for row in rows:
            session_day = _session_date(row.scanned_at)
            if session_day >= current_session or not is_market_day(session_day):
                continue
            completed_rows.append(row)
            # Rows are newest first, so this retains the closing/latest sample
            # from each completed session and avoids intraday over-weighting.
            rows_by_session.setdefault(session_day, row)

        session_rows = list(rows_by_session.values())
        stats = {
            "history_points": len(completed_rows),
            "history_sessions": len(session_rows),
            "calibration_min_sessions": settings.calibration_min_sessions,
        }
        if len(session_rows) < settings.calibration_min_sessions:
            return stats

        call_vols = [r.call_volume_ratio for r in session_rows if r.call_volume_ratio]
        oi_vals = [
            r.call_oi_pct_change
            for r in session_rows
            if r.call_oi_pct_change is not None
        ]
        iv_vals = [r.iv_percentile for r in session_rows if r.iv_percentile]

        if len(call_vols) >= settings.calibration_min_sessions:
            mean = sum(call_vols) / len(call_vols)
            std  = (sum((x - mean) ** 2 for x in call_vols) / len(call_vols)) ** 0.5
            stats["call_vol_mean"] = round(mean, 3)
            stats["call_vol_std"]  = round(max(std, 0.01), 3)  # avoid div/0

        if len(oi_vals) >= 2:
            # The first value is the latest completed session's closing sample.
            stats["call_oi_prev"] = oi_vals[0]

        if len(iv_vals) >= settings.calibration_min_sessions:
            stats["iv_30d_min"] = round(min(iv_vals), 1)
            stats["iv_30d_max"] = round(max(iv_vals), 1)

        return stats

    finally:
        db.close()
