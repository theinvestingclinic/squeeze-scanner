import json
import time
import logging
from datetime import datetime
from sqlalchemy.orm import Session
import numpy as np

from database import ScanResult, Alert, SessionLocal
from options_data import get_options_metrics
from short_data import get_short_data
from gamma import get_gamma_data
from volume_profile import get_volume_zones
from social_data import get_reddit_saturation
from scoring import calculate_score
from ticker_universe import get_ticker_universe

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
        log.info(f"Scanning {ticker}")

        options = get_options_metrics(ticker)
        short = get_short_data(ticker)
        gamma = get_gamma_data(ticker)
        zones = get_volume_zones(ticker)
        reddit_sat = get_reddit_saturation(ticker)

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
        }

        data = _normalize(data)
        score, breakdown = calculate_score(data)
        data["score"] = score
        data["score_breakdown"] = breakdown

        return data

    except Exception as e:
        log.warning(f"Failed to scan {ticker}: {e}")
        return None


def save_result(db: Session, data: dict) -> ScanResult:
    result = ScanResult(
        ticker=data["ticker"],
        score=data.get("score", 0),
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
        reddit_saturation=data.get("reddit_saturation", 0),
        price_change_30d=data.get("price_change_30d", 0),
        score_breakdown=json.dumps(data.get("score_breakdown", {})),
        scanned_at=datetime.utcnow(),
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


async def run_full_scan(alert_threshold: int = 75) -> list[dict]:
    """
    Scan the full ticker universe, save results, fire Discord alerts.
    Returns top results sorted by score.
    """
    from alerts import send_discord_alert

    tickers = get_ticker_universe(include_sp500=False)
    log.info(f"Starting scan of {len(tickers)} tickers")

    results = []
    db = SessionLocal()

    try:
        for ticker in tickers:
            data = scan_ticker(ticker)
            if data is None:
                continue

            # Filter out tickers with no meaningful signal (no options or no price)
            if data.get("price", 0) <= 0:
                continue

            save_result(db, data)
            results.append(data)

            # Throttle to avoid yfinance rate limits
            time.sleep(0.5)

        results.sort(key=lambda x: x.get("score", 0), reverse=True)

        # Fire Discord alerts for high-conviction setups
        for r in results:
            if r.get("score", 0) >= alert_threshold:
                sent = await send_discord_alert(r)
                if sent:
                    alert = Alert(
                        ticker=r["ticker"],
                        score=r["score"],
                        message=f"Score {r['score']}/100 alert sent",
                    )
                    db.add(alert)
                    db.commit()

        log.info(f"Scan complete. {len(results)} tickers scored. Top score: {results[0]['score'] if results else 0}")

    finally:
        db.close()

    return results[:50]  # Return top 50
