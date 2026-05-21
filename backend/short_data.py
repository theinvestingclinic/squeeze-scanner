import yfinance as yf
from datetime import datetime, date
from ticker_discovery import get_finra_short_ratio

# { ticker: (fetch_date, result_dict) }
_cache: dict[str, tuple[date, dict]] = {}


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
    }

    try:
        info = yf.Ticker(ticker).info

        float_shares = info.get("floatShares") or 0
        shares_short = info.get("sharesShort") or 0

        if float_shares > 0 and shares_short > 0:
            result["short_interest_pct"] = round(shares_short / float_shares * 100, 2)
            result["shares_short"] = shares_short
            result["float_shares_m"] = round(float_shares / 1_000_000, 2)

        short_date = info.get("dateShortInterest")
        if short_date:
            result["short_data_date"] = datetime.fromtimestamp(short_date).strftime("%Y-%m-%d")

    except Exception:
        pass

    _cache[ticker] = (today, result)
    return result
