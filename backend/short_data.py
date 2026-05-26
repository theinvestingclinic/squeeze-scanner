import logging

import yfinance as yf
from datetime import datetime, date
from ticker_discovery import get_finra_short_ratio
from ticker_filters import is_excluded_ticker, is_fund_quote

# { ticker: (fetch_date, result_dict) }
_cache: dict[str, tuple[date, dict]] = {}
log = logging.getLogger(__name__)


def get_short_data(ticker: str) -> dict:
    """
    Fetch short interest and float from Yahoo Finance.
    Data is cached for the calendar day — short interest is bi-weekly so
    re-fetching intraday adds latency with no new information.
    """
    today = date.today()
    if ticker in _cache:
        cached_date, cached_result = _cache[ticker]
        if cached_date == today:
            return cached_result

    result = {
        "short_interest_pct": 0.0,
        "shares_short": 0,
        "float_shares_m": 0.0,
        "short_data_date": None,
        "finra_short_vol_ratio": get_finra_short_ratio(ticker),
        "quote_type": None,
        "is_fund": is_excluded_ticker(ticker),
    }

    info = {}
    for attempt in range(2):
        try:
            info = yf.Ticker(ticker).info
            break
        except Exception as e:
            if attempt == 0:
                log.info(f"Retrying Yahoo metadata for {ticker}: {e}")
            else:
                log.warning(f"Failed to fetch Yahoo metadata for {ticker}: {e}")

    if info:
        quote_type = (info.get("quoteType") or "").upper()
        result["quote_type"] = quote_type or None
        result["is_fund"] = result["is_fund"] or is_fund_quote(info)

        float_shares = info.get("floatShares") or 0
        shares_short = info.get("sharesShort") or 0

        if float_shares > 0:
            result["float_shares_m"] = round(float_shares / 1_000_000, 2)

        if float_shares > 0 and shares_short > 0:
            result["short_interest_pct"] = round(shares_short / float_shares * 100, 2)
            result["shares_short"] = shares_short

        short_date = info.get("dateShortInterest")
        if short_date:
            result["short_data_date"] = datetime.fromtimestamp(short_date).strftime("%Y-%m-%d")

    _cache[ticker] = (today, result)
    return result
