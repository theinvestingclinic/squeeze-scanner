"""
Thin cache layer over yfinance to prevent duplicate network calls
within a single scan run. TTL is 15 min for history, 10 min for
option chains — short enough to stay fresh intraday, long enough
to deduplicate the options_data / gamma / volume_profile triple-fetch.
"""
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd

_history_cache: dict[tuple, tuple] = {}   # (ticker, period) -> (ts, DataFrame)
_options_cache: dict[str, tuple] = {}     # ticker -> (ts, tuple[str, ...])
_chain_cache: dict[tuple, tuple] = {}     # (ticker, exp) -> (ts, OptionChain)

_HISTORY_TTL = timedelta(minutes=15)
_CHAIN_TTL = timedelta(minutes=10)


def get_history(ticker: str, period: str = "60d") -> pd.DataFrame:
    key = (ticker, period)
    entry = _history_cache.get(key)
    if entry and datetime.utcnow() - entry[0] < _HISTORY_TTL:
        return entry[1]
    df = yf.Ticker(ticker).history(period=period)
    _history_cache[key] = (datetime.utcnow(), df)
    return df


def get_options_list(ticker: str) -> tuple[str, ...]:
    entry = _options_cache.get(ticker)
    if entry and datetime.utcnow() - entry[0] < _CHAIN_TTL:
        return entry[1]
    exps = yf.Ticker(ticker).options  # returns tuple[str]
    _options_cache[ticker] = (datetime.utcnow(), exps)
    return exps


def get_option_chain(ticker: str, exp: str):
    key = (ticker, exp)
    entry = _chain_cache.get(key)
    if entry and datetime.utcnow() - entry[0] < _CHAIN_TTL:
        return entry[1]
    chain = yf.Ticker(ticker).option_chain(exp)
    _chain_cache[key] = (datetime.utcnow(), chain)
    return chain
