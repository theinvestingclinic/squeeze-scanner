import yfinance as yf
from datetime import datetime


def get_short_data(ticker: str) -> dict:
    """
    Fetch short interest and float from Yahoo Finance.
    Yahoo aggregates NASDAQ/NYSE exchange data — refreshes bi-weekly.
    """
    result = {
        "short_interest_pct": 0.0,
        "shares_short": 0,
        "float_shares_m": 0.0,
        "short_data_date": None,
    }

    try:
        info = yf.Ticker(ticker).info

        float_shares = info.get("floatShares") or 0
        shares_short = info.get("sharesShort") or 0

        if float_shares > 0 and shares_short > 0:
            result["short_interest_pct"] = round(shares_short / float_shares * 100, 2)
            result["shares_short"] = shares_short
            result["float_shares_m"] = round(float_shares / 1_000_000, 2)

        # Yahoo reports the date the data is current through
        short_date = info.get("dateShortInterest")
        if short_date:
            result["short_data_date"] = datetime.fromtimestamp(short_date).strftime("%Y-%m-%d")

    except Exception:
        pass

    return result
