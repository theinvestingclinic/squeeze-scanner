"""Ticker eligibility filters for the squeeze scanner."""

# ETFs, ETNs, leveraged funds, commodity funds, and broad index products are
# excluded because fund units do not have the same squeeze mechanics as shares.
EXCLUDED_ETF_TICKERS = frozenset(
    {
        "AGG", "ARKF", "ARKG", "ARKK", "ARKQ", "ARKW", "ASHR", "BIL",
        "BITB", "BITI", "BITO", "BITU", "BITX", "BND", "BNDX", "BOIL",
        "DIA", "DPST", "DUST", "EEM", "EFA", "ERX", "ERY", "ETHE", "FAZ",
        "FAS", "FBTC", "FUTG", "FXI", "GBTC", "GDX", "GDXJ", "GLD", "GOVT",
        "HYG", "IBIT", "ICLN", "IEF", "IEMG", "IJH", "IJR", "ITOT", "IVV",
        "IWB", "IWD", "IWF", "IWM", "IWN", "IWO", "JDST", "JEPI", "JEPQ",
        "JNK", "JNUG", "KOLD", "KRE", "KWEB", "LABD", "LABU", "LQD", "MBB",
        "MJ", "MSOS", "MTUM", "NUGT", "PSQ", "QLD", "QQQ", "QID", "QUAL",
        "RSP", "SCHA", "SCHB", "SCHD", "SCHF", "SCHG", "SCHH", "SCHX",
        "SCO", "SDOW", "SDS", "SFLR", "SGOV", "SH", "SHV", "SHY", "SHYG",
        "SLV", "SMH", "SOXL", "SOXS", "SOXX", "SPAB", "SPHQ", "SPMO",
        "SPTS", "SPXL", "SPXS", "SPYD", "SPYG", "SPY", "SPYV", "SPLV",
        "SQQQ", "SRTY", "SSO", "SVXY", "TAN", "TBT", "TECL", "TECS", "TIP",
        "TLT", "TMF", "TMV", "TNA", "TQQQ", "TZA", "UCO", "UNG", "UPRO",
        "URTY", "USHY", "USMV", "USO", "UVXY", "VEA", "VGK", "VIG", "VOO",
        "VT", "VTI", "VTV", "VUG", "VWO", "VXX", "VXUS", "VYM", "XBI",
        "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU",
        "XLV", "XLY", "XOP", "XOVR", "XRT", "YANG", "YINN",

        # Single-country and regional ETFs commonly surfaced by FINRA volume.
        "ECH", "EIDO", "EIRL", "EIS", "ENZL", "EPI", "EPHE", "EPOL", "EPU",
        "EWA", "EWC", "EWD", "EWG", "EWH", "EWI", "EWJ", "EWK", "EWL",
        "EWM", "EWN", "EWO", "EWP", "EWQ", "EWS", "EWT", "EWU", "EWW",
        "EWY", "EWZ", "EZA", "GREK", "INDA", "KSA", "NORW", "TUR", "UAE",
    }
)

FUND_QUOTE_TYPES = frozenset({"ETF", "MUTUALFUND", "INDEX"})


def normalize_ticker(ticker: str) -> str:
    return (ticker or "").strip().upper()


def is_excluded_ticker(ticker: str) -> bool:
    return normalize_ticker(ticker) in EXCLUDED_ETF_TICKERS


def filter_excluded_tickers(tickers: list[str]) -> list[str]:
    return [ticker for ticker in tickers if not is_excluded_ticker(ticker)]


def is_fund_quote(info: dict) -> bool:
    quote_type = (info.get("quoteType") or "").upper()
    return quote_type in FUND_QUOTE_TYPES or bool(info.get("fundFamily"))
