import pandas as pd

from ticker_filters import filter_excluded_tickers


# S&P 500 pulled from Wikipedia at startup; falls back to BASE_LIST if unavailable
def get_sp500_tickers() -> list[str]:
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        return tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
    except Exception:
        return []


# High short interest / squeeze-prone small and mid caps — seed list
# Dead/delisted tickers removed: BBBY, WISH, RIDE, AGTC, FFIE, GREE, HYZN, HLBZ, EEENF, GXII, HYLN, GOEV, ARVL
SQUEEZE_WATCHLIST = [
    # Perennial squeeze candidates
    "GME", "AMC", "CLOV", "WKHS", "RKT", "SPCE",
    "CRIS", "SNDL", "KOSS", "BB", "NOK", "TLRY", "PXMD",
    # Biotech / small cap with high short interest potential
    "NVAX", "SRPT", "MARA", "RIOT", "HUT", "BTBT", "ARBK", "CIFR", "CLSK",
    # Meme / options-heavy
    "SOFI", "LCID", "RIVN", "AFRM", "HOOD", "DKNG", "UWMC", "OPAD",
    "PRPL", "BARK", "XELA", "ATER",
    "GFAI", "CXAI", "ILUS", "GROM",
    # Mid cap / macro-sensitive
    "PLTR", "OPEN", "CHPT", "BLNK", "FCEL", "PLUG", "BE",
    "HPNN", "AIXI", "AITX",
]

def get_discovered_tickers() -> list[str]:
    """Pull active tickers from the FINRA discovery table."""
    try:
        from database import SessionLocal, DiscoveredTicker
        db = SessionLocal()
        try:
            rows = db.query(DiscoveredTicker).filter_by(is_active=True).all()
            return filter_excluded_tickers([r.ticker for r in rows])
        finally:
            db.close()
    except Exception:
        return []


def get_ticker_universe(include_sp500: bool = False) -> list[str]:
    # Start with permanent seed list
    universe = filter_excluded_tickers(list(dict.fromkeys(SQUEEZE_WATCHLIST)))

    # Merge in dynamically discovered tickers from FINRA sweep
    discovered = get_discovered_tickers()
    universe = filter_excluded_tickers(list(dict.fromkeys(universe + discovered)))

    if include_sp500:
        sp500 = get_sp500_tickers()
        universe = filter_excluded_tickers(list(dict.fromkeys(universe + sp500)))

    return universe
