import numpy as np
from scipy.stats import norm
from datetime import datetime
from yf_cache import get_history, get_options_list, get_option_chain


def _bs_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return norm.pdf(d1) / (S * sigma * np.sqrt(T))


def get_gamma_data(ticker: str) -> dict:
    try:
        hist = get_history(ticker, "60d")
        if hist.empty:
            return {}
        spot = float(hist["Close"].iloc[-1])

        expirations = get_options_list(ticker)
        if not expirations:
            return {}

        r = 0.045
        gex_by_strike: dict[float, float] = {}
        call_oi_by_strike: dict[float, float] = {}
        put_oi_by_strike: dict[float, float] = {}

        for exp in expirations[:4]:
            try:
                exp_date = datetime.strptime(exp, "%Y-%m-%d")
                T = max((exp_date - datetime.now()).days / 365.0, 1 / 365)
                chain = get_option_chain(ticker, exp)

                for row in chain.calls.itertuples():
                    K = float(row.strike)
                    if not (spot * 0.6 <= K <= spot * 1.6):
                        continue
                    sigma = float(row.impliedVolatility) if row.impliedVolatility > 0.01 else 0.35
                    oi = float(row.openInterest) if row.openInterest > 0 else 0
                    g = _bs_gamma(spot, K, T, r, sigma)
                    gex_by_strike[K] = gex_by_strike.get(K, 0) + g * oi * 100 * spot
                    call_oi_by_strike[K] = call_oi_by_strike.get(K, 0) + oi

                for row in chain.puts.itertuples():
                    K = float(row.strike)
                    if not (spot * 0.6 <= K <= spot * 1.6):
                        continue
                    sigma = float(row.impliedVolatility) if row.impliedVolatility > 0.01 else 0.35
                    oi = float(row.openInterest) if row.openInterest > 0 else 0
                    g = _bs_gamma(spot, K, T, r, sigma)
                    gex_by_strike[K] = gex_by_strike.get(K, 0) - g * oi * 100 * spot
                    put_oi_by_strike[K] = put_oi_by_strike.get(K, 0) + oi

            except Exception:
                continue

        if not gex_by_strike:
            return {}

        calls_above = {k: v for k, v in call_oi_by_strike.items() if k > spot}
        call_wall = max(calls_above, key=calls_above.get) if calls_above else None

        puts_below = {k: v for k, v in put_oi_by_strike.items() if k <= spot}
        put_wall = max(puts_below, key=puts_below.get) if puts_below else None

        strikes = sorted(gex_by_strike)
        zero_gamma = None
        for i in range(len(strikes) - 1):
            g1 = gex_by_strike[strikes[i]]
            g2 = gex_by_strike[strikes[i + 1]]
            if g1 * g2 < 0:
                zero_gamma = strikes[i] + (strikes[i + 1] - strikes[i]) * abs(g1) / (abs(g1) + abs(g2))
                break

        gex_above_spot = sum(v for k, v in gex_by_strike.items() if k > spot)
        net_gex = sum(gex_by_strike.values())

        return {
            "spot": spot,
            "call_wall": round(call_wall, 2) if call_wall else None,
            "put_wall": round(put_wall, 2) if put_wall else None,
            "zero_gamma": round(zero_gamma, 2) if zero_gamma else None,
            "net_gex": round(net_gex, 0),
            "gex_above_spot": round(gex_above_spot, 0),
            "is_negative_gamma": gex_above_spot < 0,
            "gex_by_strike": {round(k, 2): round(v, 0) for k, v in gex_by_strike.items()},
        }

    except Exception:
        return {}
