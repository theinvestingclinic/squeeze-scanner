import pandas as pd


# S&P 500 pulled from Wikipedia at startup; falls back to BASE_LIST if unavailable
def get_sp500_tickers() -> list[str]:
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        return tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
    except Exception:
        return []


# High short interest / squeeze-prone small and mid caps — seed list
SQUEEZE_WATCHLIST = [
    # Perennial squeeze candidates
    "GME", "AMC", "BBBY", "CLOV", "WISH", "WKHS", "RKT", "SPCE", "NKLA", "RIDE",
    "CRIS", "SNDL", "EXPR", "KOSS", "BB", "NOK", "TLRY", "AGTC", "PXMD", "FFIE",
    # Biotech / small cap with high short interest potential
    "NVAX", "SRPT", "MARA", "RIOT", "HUT", "BTBT", "ARBK", "CIFR", "CLSK",
    # Recent meme / options-heavy
    "SOFI", "LCID", "RIVN", "AFRM", "HOOD", "DKNG", "UWMC", "RDW", "OPAD",
    "PRPL", "BARK", "GREE", "HYZN", "XELA", "HLBZ", "BIOR", "ATER", "SDC",
    "BGFV", "ICAD", "EEENF", "GFAI", "VERB", "CXAI", "ILUS", "GROM", "GXII",
    # Mid cap / macro-sensitive
    "PLTR", "OPEN", "CHPT", "BLNK", "FCEL", "PLUG", "BE", "HYLN", "GOEV",
    "ARVL", "NURO", "IDEX", "HPNN", "AIXI", "AITX",
]

# Optionally scan broader market; toggled by SCAN_BROAD env var
def get_ticker_universe(include_sp500: bool = False) -> list[str]:
    universe = list(dict.fromkeys(SQUEEZE_WATCHLIST))  # deduplicate, preserve order

    if include_sp500:
        sp500 = get_sp500_tickers()
        universe = list(dict.fromkeys(universe + sp500))

    return universe
