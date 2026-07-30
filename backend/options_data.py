import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
from yf_cache import get_history, get_options_list, get_option_chain


EASTERN = ZoneInfo("America/New_York")


def _session_progress(last_bar_date) -> float:
    """Estimated fraction of a regular session elapsed for today's daily bar."""
    now = datetime.now(EASTERN)
    try:
        if last_bar_date.date() != now.date():
            return 1.0
    except AttributeError:
        return 1.0
    open_minutes = 9 * 60 + 30
    now_minutes = now.hour * 60 + now.minute
    elapsed = now_minutes - open_minutes
    if elapsed <= 0:
        return 0.1
    return min(1.0, max(0.1, elapsed / 390))


def get_options_metrics(ticker: str) -> dict:
    result = {
        "call_volume_ratio": 0.0,
        "call_oi_pct_change": 0.0,
        "iv_percentile": 0.0,
        "breaking_key_level": False,
        "relative_volume": 0.0,
        "avg_volume_20d": 0.0,
        "dollar_volume_20d": 0.0,
        "has_options_data": False,
        "price_trend_score": 0.0,
        "price_change_30d": 0.0,
        "price": 0.0,
    }

    try:
        hist = get_history(ticker, "60d")
        if hist.empty or len(hist) < 10:
            return result

        closes = hist["Close"]
        volumes = hist["Volume"]
        spot = float(closes.iloc[-1])
        result["price"] = round(spot, 2)

        avg_vol_20d = float(volumes.iloc[-21:-1].mean()) if len(volumes) > 21 else float(volumes.mean())
        today_vol = float(volumes.iloc[-1])
        progress = _session_progress(hist.index[-1])
        raw_relative_volume = today_vol / avg_vol_20d if avg_vol_20d > 0 else 0
        result["avg_volume_20d"] = round(avg_vol_20d, 0)
        result["dollar_volume_20d"] = round(avg_vol_20d * spot, 0)
        result["relative_volume_raw"] = round(raw_relative_volume, 2)
        result["session_progress"] = round(progress, 3)
        result["relative_volume"] = round(raw_relative_volume / progress, 2)

        if len(closes) >= 22:
            price_30d_ago = float(closes.iloc[-22])
            result["price_change_30d"] = round((spot - price_30d_ago) / price_30d_ago * 100, 1)

        trend_score = 0.0
        if len(closes) >= 20:
            ma20 = closes.rolling(20).mean().iloc[-1]
            if spot > ma20:
                trend_score += 4
        if len(closes) >= 50:
            ma50 = closes.rolling(50).mean().iloc[-1]
            if spot > ma50:
                trend_score += 3
        lows = hist["Low"].iloc[-10:]
        if lows.is_monotonic_increasing or (lows.diff().dropna() > 0).sum() >= 7:
            trend_score += 3
        result["price_trend_score"] = round(trend_score, 1)

        if len(hist) >= 22:
            prior_high_20d = float(hist["High"].iloc[-22:-2].max())
            result["breaking_key_level"] = spot > prior_high_20d

        expirations = get_options_list(ticker)
        if not expirations:
            return result

        near_exp = expirations[0]
        chain = get_option_chain(ticker, near_exp)
        calls = chain.calls

        if calls.empty:
            return result
        result["has_options_data"] = True

        today_call_vol = float(calls["volume"].fillna(0).sum())
        avg_call_oi = float(calls["openInterest"].fillna(0).sum())
        avg_daily_call_vol_est = avg_call_oi / 20 if avg_call_oi > 0 else 1
        result["call_volume_ratio"] = round(today_call_vol / avg_daily_call_vol_est if avg_daily_call_vol_est > 0 else 0, 2)

        calls_above = calls[calls["strike"] > spot]
        if not calls_above.empty:
            total_oi_above = float(calls_above["openInterest"].fillna(0).sum())
            total_oi = float(calls["openInterest"].fillna(0).sum())
            concentration = (total_oi_above / total_oi * 100) if total_oi > 0 else 0
            result["call_oi_pct_change"] = round(max(0, concentration - 40), 1)

        all_ivs = []
        for exp in expirations[:3]:
            try:
                c = get_option_chain(ticker, exp).calls
                ivs = c["impliedVolatility"].replace(0, np.nan).dropna()
                if not ivs.empty:
                    all_ivs.append(float(ivs.median()))
            except Exception:
                continue

        if len(all_ivs) >= 2:
            current_iv = all_ivs[0]
            iv_min = min(all_ivs)
            iv_max = max(all_ivs)
            if iv_max > iv_min:
                result["iv_percentile"] = round((current_iv - iv_min) / (iv_max - iv_min) * 100, 1)
            else:
                result["iv_percentile"] = 50.0

    except Exception:
        pass

    return result
