"""Pre-score eligibility checks for short-squeeze candidates."""

from ticker_filters import is_excluded_ticker

ELIGIBLE_COMMON_STOCK = "eligible_common_stock"
EXCLUDED_FUND = "excluded_fund"
MISSING_CLASSIFICATION = "missing_classification"
NOT_COMMON_STOCK = "not_common_stock"
MISSING_FLOAT = "missing_float"
MISSING_SHORT_DATA = "missing_short_data"
NO_OPTIONS = "no_options"
ILLIQUID = "illiquid"

MIN_DOLLAR_VOLUME_20D = 1_000_000


def evaluate_eligibility(ticker: str, short: dict, options: dict) -> dict:
    """Return status/reason before a ticker is allowed into scoring."""
    quote_type = (short.get("quote_type") or "").upper()
    float_m = short.get("float_shares_m", 0) or 0
    short_interest_pct = short.get("short_interest_pct", 0) or 0
    dollar_volume_20d = options.get("dollar_volume_20d", 0) or 0

    if is_excluded_ticker(ticker) or short.get("is_fund"):
        status = EXCLUDED_FUND
        reason = "ETF, fund, index, trust, or broad basket product"
    elif not quote_type:
        status = MISSING_CLASSIFICATION
        reason = "Could not confirm common-stock quote type"
    elif quote_type != "EQUITY":
        status = NOT_COMMON_STOCK
        reason = f"Yahoo quoteType is {quote_type}"
    elif float_m <= 0:
        status = MISSING_FLOAT
        reason = "Float data unavailable"
    elif short_interest_pct <= 0:
        status = MISSING_SHORT_DATA
        reason = "Short-interest data unavailable"
    elif not options.get("has_options_data"):
        status = NO_OPTIONS
        reason = "No usable options chain"
    elif dollar_volume_20d < MIN_DOLLAR_VOLUME_20D:
        status = ILLIQUID
        reason = f"20-day dollar volume below ${MIN_DOLLAR_VOLUME_20D:,}"
    else:
        status = ELIGIBLE_COMMON_STOCK
        reason = "Confirmed common stock with float, short interest, options, and liquidity"

    return {
        "status": status,
        "reason": reason,
        "quote_type": quote_type or None,
        "float_shares_m": float_m,
        "short_interest_pct": short_interest_pct,
        "has_options_data": bool(options.get("has_options_data")),
        "dollar_volume_20d": dollar_volume_20d,
    }
