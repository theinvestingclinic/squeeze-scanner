import logging
from datetime import datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from sqlalchemy.orm import Session

from database import DiscoveredTicker

log = logging.getLogger(__name__)

# FINRA publishes daily short volume for all exchange-listed securities
FINRA_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"

# { ticker: short_vol_ratio } — populated each morning by run_discovery()
_finra_ratios: dict[str, float] = {}


def get_finra_short_ratio(ticker: str) -> float | None:
    """Return today's FINRA short volume ratio for a ticker, or None if not available."""
    return _finra_ratios.get(ticker)


def _last_trading_day() -> str:
    et = ZoneInfo("America/New_York")
    today = datetime.now(et)
    for i in range(1, 6):
        candidate = today - timedelta(days=i)
        if candidate.weekday() < 5:
            return candidate.strftime("%Y%m%d")
    return (today - timedelta(days=1)).strftime("%Y%m%d")


async def _fetch_finra_short_volume() -> pd.DataFrame:
    date = _last_trading_day()
    url = FINRA_URL.format(date=date)
    log.info(f"Fetching FINRA short volume: {url}")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text), sep="|")
    df.columns = [c.strip() for c in df.columns]
    return df


def _filter_candidates(df: pd.DataFrame) -> list[str]:
    """
    Keep tickers where short selling is > 50% of total volume
    and total volume is large enough to be liquid.
    """
    df = df.copy()
    df["ShortVolume"] = pd.to_numeric(df["ShortVolume"], errors="coerce").fillna(0)
    df["TotalVolume"] = pd.to_numeric(df["TotalVolume"], errors="coerce").fillna(0)
    df["short_ratio"] = df["ShortVolume"] / df["TotalVolume"].replace(0, 1)

    candidates = df[
        (df["short_ratio"] >= 0.40) &
        (df["TotalVolume"] >= 500_000) &
        (df["Symbol"].str.match(r'^[A-Z]{1,5}$', na=False))  # plain ticker symbols only
    ]

    return candidates.sort_values("TotalVolume", ascending=False)["Symbol"].tolist()


async def run_discovery(db: Session) -> list[str]:
    """
    Download FINRA short volume, filter for high short-ratio tickers,
    upsert into discovered_tickers table.
    Returns list of newly added tickers.
    """
    try:
        df = await _fetch_finra_short_volume()

        # Cache ratios for all tickers so short_data.py can look them up
        global _finra_ratios
        df2 = df.copy()
        df2["ShortVolume"] = pd.to_numeric(df2["ShortVolume"], errors="coerce").fillna(0)
        df2["TotalVolume"] = pd.to_numeric(df2["TotalVolume"], errors="coerce").fillna(0)
        df2["short_ratio"] = df2["ShortVolume"] / df2["TotalVolume"].replace(0, 1)
        _finra_ratios = dict(zip(df2["Symbol"], df2["short_ratio"].round(4)))
        log.info(f"FINRA ratios cached for {len(_finra_ratios)} tickers")

        candidates = _filter_candidates(df)
        log.info(f"FINRA discovery: {len(candidates)} candidates after filtering")
    except Exception as e:
        log.warning(f"FINRA discovery failed: {e}")
        return []

    now = datetime.utcnow()
    new_tickers = []

    for ticker in candidates[:200]:  # cap to control scan time
        existing = db.query(DiscoveredTicker).filter_by(ticker=ticker).first()
        if existing:
            existing.last_seen_at = now
            existing.is_active = True
        else:
            db.add(DiscoveredTicker(
                ticker=ticker,
                source="finra_short_volume",
                discovered_at=now,
                last_seen_at=now,
                is_active=True,
            ))
            new_tickers.append(ticker)

    # Expire tickers not seen in 30 days
    cutoff = now - timedelta(days=30)
    db.query(DiscoveredTicker).filter(
        DiscoveredTicker.last_seen_at < cutoff
    ).update({"is_active": False})

    db.commit()
    log.info(f"Discovery complete: {len(new_tickers)} new tickers added")
    return new_tickers
