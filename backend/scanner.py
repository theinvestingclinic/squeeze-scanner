import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import numpy as np

from config import settings
from database import ScanResult, ScanRun, SessionLocal
from eligibility import ELIGIBLE_COMMON_STOCK, evaluate_eligibility
from options_data import get_options_metrics
from short_data import get_short_data
from gamma import get_gamma_data
from volume_profile import get_volume_zones
from social_data import get_reddit_saturation
from historical import get_historical_stats
from scoring import calculate_score
from ticker_universe import get_ticker_universe
from ticker_filters import is_excluded_ticker

_executor = ThreadPoolExecutor(max_workers=4)
_scan_running = False


def is_scan_running() -> bool:
    return _scan_running

log = logging.getLogger(__name__)


def _to_python(v):
    """Convert numpy scalars to plain Python types so SQLAlchemy and json.dumps don't choke."""
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v) if not np.isnan(v) else 0.0
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v


def _normalize(data: dict) -> dict:
    return {k: _to_python(v) for k, v in data.items()}


def scan_ticker(ticker: str) -> dict | None:
    """Fetch all signals for one ticker and return a scored data dict."""
    try:
        if is_excluded_ticker(ticker):
            log.info(f"Skipping excluded fund ticker {ticker}")
            return None

        log.info(f"Scanning {ticker}")

        short = get_short_data(ticker)
        if short.get("is_fund"):
            log.info(f"Skipping fund/ETF ticker {ticker}")
            return None

        options = get_options_metrics(ticker)
        eligibility = evaluate_eligibility(ticker, short, options)
        if eligibility["status"] != ELIGIBLE_COMMON_STOCK:
            log.info(f"Skipping {ticker}: {eligibility['status']} ({eligibility['reason']})")
            return None

        gamma = get_gamma_data(ticker)
        zones = get_volume_zones(ticker)
        reddit_enabled = bool(
            settings.enable_reddit_signal
            and settings.reddit_client_id
            and settings.reddit_client_secret
        )
        reddit_sat = get_reddit_saturation(ticker) if reddit_enabled else 0.0

        data = {
            "ticker": ticker,
            **options,
            **short,
            "is_negative_gamma": gamma.get("is_negative_gamma", False),
            "call_wall": gamma.get("call_wall"),
            "put_wall": gamma.get("put_wall"),
            "zero_gamma": gamma.get("zero_gamma"),
            "net_gex": gamma.get("net_gex", 0),
            "volume_zones": zones,
            "reddit_saturation": reddit_sat,
            "reddit_data_available": reddit_enabled,
            "eligibility_status": eligibility["status"],
            "eligibility": eligibility,
        }

        data = _normalize(data)
        data["_hist"] = get_historical_stats(ticker)
        score, breakdown = calculate_score(data)
        breakdown["_eligibility"] = eligibility
        data["score"] = score
        data["setup_score"] = breakdown.get("setup_score", 0)
        data["trigger_score"] = breakdown.get("trigger_score", 0)
        data["score_breakdown"] = breakdown

        return data

    except Exception as e:
        log.warning(f"Failed to scan {ticker}: {e}")
        return None


def save_result(db: Session, data: dict, scan_run_id: int | None = None) -> ScanResult:
    result = ScanResult(
        scan_run_id=scan_run_id,
        ticker=data["ticker"],
        score=data.get("score", 0),
        setup_score=data.get("setup_score"),
        trigger_score=data.get("trigger_score"),
        price=data.get("price", 0),
        short_interest_pct=data.get("short_interest_pct", 0),
        float_shares_m=data.get("float_shares_m", 0),
        price_trend_score=data.get("price_trend_score", 0),
        call_volume_ratio=data.get("call_volume_ratio", 0),
        is_negative_gamma=data.get("is_negative_gamma", False),
        call_oi_pct_change=data.get("call_oi_pct_change", 0),
        iv_percentile=data.get("iv_percentile", 0),
        breaking_key_level=data.get("breaking_key_level", False),
        relative_volume=data.get("relative_volume", 0),
        call_wall=data.get("call_wall"),
        put_wall=data.get("put_wall"),
        zero_gamma=data.get("zero_gamma"),
        net_gex=data.get("net_gex", 0),
        volume_zones=json.dumps(data.get("volume_zones", [])),
        finra_short_vol_ratio=data.get("finra_short_vol_ratio"),
        reddit_saturation=data.get("reddit_saturation", 0),
        price_change_30d=data.get("price_change_30d", 0),
        score_breakdown=json.dumps(data.get("score_breakdown", {})),
        scanned_at=datetime.utcnow(),
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def should_send_alert(data: dict, alert_threshold: int) -> bool:
    """Return true only for reliable, calibrated setup/trigger alignment."""
    if data.get("score", 0) < alert_threshold and not is_potential_squeeze(data):
        return False
    if data.get("eligibility_status") != ELIGIBLE_COMMON_STOCK:
        return False
    if data.get("setup_score", 0) < settings.alert_min_setup_score:
        return False
    if data.get("trigger_score", 0) < settings.alert_min_trigger_score:
        return False
    if data.get("short_interest_pct", 0) <= 0:
        return False

    breakdown = data.get("score_breakdown") or {}
    if breakdown.get("already_squeezed", 0) < 0:
        return False

    quality = breakdown.get("_data_quality") or {}
    if not quality.get("has_short_data", False):
        return False
    if settings.alert_require_calibration and not quality.get("signals_calibrated", False):
        return False
    return True


def is_potential_squeeze(data: dict) -> bool:
    """Secondary alert gate for top scanner candidates before the 75+ hot tier."""
    return (
        data.get("score", 0) >= settings.alert_potential_threshold
        and data.get("setup_score", 0) >= settings.alert_min_setup_score
        and data.get("trigger_score", 0) >= settings.alert_min_trigger_score
        and data.get("short_interest_pct", 0) >= settings.alert_min_short_interest_pct
        and data.get("relative_volume", 0) >= settings.alert_min_relative_volume
    )


def signal_tier(data: dict, alert_threshold: int | None = None) -> int:
    """0=monitor, 1=setup watch, 2=active trigger."""
    threshold = alert_threshold or settings.alert_threshold
    if not should_send_alert(data, threshold):
        return 0
    return 2 if data.get("score", 0) >= threshold else 1


def _row_as_signal(row: ScanResult) -> dict:
    try:
        breakdown = json.loads(row.score_breakdown or "{}")
    except (TypeError, ValueError):
        breakdown = {}
    eligibility = breakdown.get("_eligibility") or {}
    return {
        "ticker": row.ticker,
        "score": row.score or 0,
        "setup_score": row.setup_score or 0,
        "trigger_score": row.trigger_score or 0,
        "short_interest_pct": row.short_interest_pct or 0,
        "relative_volume": row.relative_volume or 0,
        "eligibility_status": eligibility.get("status"),
        "score_breakdown": breakdown,
    }


def is_material_transition(current: dict, previous: dict | None, alert_threshold: int) -> bool:
    """Alert on a calibrated tier entry or a material improvement within a tier."""
    return material_transition_type(current, previous, alert_threshold) is not None


def material_transition_type(
    current: dict,
    previous: dict | None,
    alert_threshold: int,
) -> str | None:
    """Classify a material transition for durable signal/outbox records."""
    if previous is None:
        return None

    current_tier = signal_tier(current, alert_threshold)
    previous_tier = signal_tier(previous, alert_threshold)
    if current_tier == 0:
        return None
    if current_tier > previous_tier:
        return "tier_upgrade"
    if current_tier != previous_tier:
        return None
    if (
        current.get("score", 0) - previous.get("score", 0)
        >= settings.alert_material_score_change
    ):
        return "score_improvement"
    if (
        current.get("trigger_score", 0) - previous.get("trigger_score", 0)
        >= settings.alert_material_trigger_change
    ):
        return "trigger_improvement"
    return None


async def run_full_scan(alert_threshold: int = 75) -> list[dict]:
    """
    Scan the full ticker universe, save results, fire Discord alerts.
    Returns top results sorted by score.
    """
    global _scan_running
    if _scan_running:
        log.info("Scan already running — skipping")
        return []
    _scan_running = True

    from alert_delivery import (
        deliver_pending_alerts,
        enqueue_signal_event,
        is_recent_signal_duplicate,
    )

    tickers = get_ticker_universe(include_sp500=False)
    log.info(f"Starting scan of {len(tickers)} tickers")

    results = []
    db = SessionLocal()
    loop = asyncio.get_event_loop()

    try:
        # Open a scan run record
        run = ScanRun(started_at=datetime.utcnow())
        db.add(run)
        db.commit()
        db.refresh(run)

        # Run a bounded batch at a time.  The previous implementation created a
        # four-worker pool but awaited each ticker serially.
        worker_count = max(1, getattr(_executor, "_max_workers", 4))
        for offset in range(0, len(tickers), worker_count):
            batch = tickers[offset : offset + worker_count]
            scanned = await asyncio.gather(
                *(loop.run_in_executor(_executor, scan_ticker, ticker) for ticker in batch)
            )
            for data in scanned:
                if data is None or data.get("price", 0) <= 0:
                    continue
                save_result(db, data, scan_run_id=run.id)
                results.append(data)
            await asyncio.sleep(0.15)

        results.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Mark run complete
        run.completed_at = datetime.utcnow()
        run.ticker_count = len(results)
        db.commit()

        # Retain enough observations for the advertised 30-day calibration.
        cutoff = datetime.utcnow() - timedelta(days=settings.scan_history_days)
        old_runs = db.query(ScanRun).filter(ScanRun.started_at < cutoff).all()
        for old_run in old_runs:
            db.query(ScanResult).filter(ScanResult.scan_run_id == old_run.id).delete()
            db.delete(old_run)
        db.commit()

        # Record every material transition before attempting Discord. Delivery
        # is a durable, capped outbox; missing credentials, network failures,
        # and names beyond one digest remain queued for a later scan.
        for r in results:
            if not should_send_alert(r, alert_threshold):
                continue
            previous_row = (
                db.query(ScanResult)
                .filter(
                    ScanResult.ticker == r["ticker"],
                    ScanResult.scan_run_id != run.id,
                )
                .order_by(ScanResult.scanned_at.desc())
                .first()
            )
            previous = _row_as_signal(previous_row) if previous_row else None
            event_type = material_transition_type(r, previous, alert_threshold)
            if event_type is None:
                continue
            tier = signal_tier(r, alert_threshold)
            if is_recent_signal_duplicate(db, r, tier=tier):
                continue
            enqueue_signal_event(
                db,
                r,
                scan_run_id=run.id,
                tier=tier,
                event_type=event_type,
            )
        db.commit()

        try:
            await deliver_pending_alerts(db, alert_threshold)
        except Exception as exc:
            # Signal/outbox rows are already committed. A later scan can retry.
            log.warning(
                "Discord outbox processing deferred after %s",
                type(exc).__name__,
            )

        from outcomes import update_alert_outcomes
        update_alert_outcomes(db)

        log.info(f"Scan complete. {len(results)} tickers scored. Top score: {results[0]['score'] if results else 0}")

    finally:
        db.close()
        _scan_running = False

    return results[:50]
