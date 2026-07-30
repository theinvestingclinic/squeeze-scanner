"""
Historical stats for a ticker drawn from our own accumulated scan_results.
Used to z-score call volume, compute true OI delta, and build a real
30-day IV range — all without any paid data source.

Stats are unavailable until the scanner has accumulated enough scans
for a given ticker (minimum 5 data points). Scoring falls back to
proxy calculations until then.
"""
from datetime import datetime, timedelta
from database import SessionLocal, ScanResult
from sqlalchemy import desc


def get_historical_stats(ticker: str) -> dict:
    """
    Query last 30 days of scan results for a ticker.

    Returns a dict with calibration values used by scoring.py:
        history_points      int   — how many scans we have
        call_vol_mean       float — mean call_volume_ratio over history
        call_vol_std        float — std dev of call_volume_ratio
        call_oi_prev        float — most recent prior call_oi_pct_change
        iv_30d_min          float — min iv_percentile over 30 days
        iv_30d_max          float — max iv_percentile over 30 days

    Returns {"history_points": N} with no calibration keys when N < 5.
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

        stats = {"history_points": len(rows)}
        if len(rows) < 5:
            return stats

        call_vols = [r.call_volume_ratio for r in rows if r.call_volume_ratio]
        oi_vals   = [r.call_oi_pct_change for r in rows if r.call_oi_pct_change is not None]
        iv_vals   = [r.iv_percentile for r in rows if r.iv_percentile]

        if len(call_vols) >= 5:
            mean = sum(call_vols) / len(call_vols)
            std  = (sum((x - mean) ** 2 for x in call_vols) / len(call_vols)) ** 0.5
            stats["call_vol_mean"] = round(mean, 3)
            stats["call_vol_std"]  = round(max(std, 0.01), 3)  # avoid div/0

        if len(oi_vals) >= 2:
            # rows[0] is today's most recent prior scan
            stats["call_oi_prev"] = oi_vals[0]

        if len(iv_vals) >= 5:
            stats["iv_30d_min"] = round(min(iv_vals), 1)
            stats["iv_30d_max"] = round(max(iv_vals), 1)

        return stats

    finally:
        db.close()
