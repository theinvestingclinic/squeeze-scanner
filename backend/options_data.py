import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def get_options_metrics(ticker: str) -> dict:
    """
    Returns call_volume_ratio, call_oi_pct_change, iv_percentile,
    breaking_key_level, relative_volume.
    """
    result = {
        "call_volume_ratio": 0.0,
        "call_oi_pct_change": 0.0,
        "iv_percentile": 0.0,
        "breaking_key_level": False,
        "relative_volume": 0.0,
        "price_trend_score": 0.0,
        "price_change_30d": 0.0,
        "price": 0.0,
    }

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="60d")
        if hist.empty or len(hist) < 10:
            return result

        closes = hist["Close"]
        volumes = hist["Volume"]
        spot = float(closes.iloc[-1])
        result["price"] = round(spot, 2)

        # Relative volume (today vs 20-day average)
        avg_vol_20d = float(volumes.iloc[-21:-1].mean()) if len(volumes) > 21 else float(volumes.mean())
        today_vol = float(volumes.iloc[-1])
        result["relative_volume"] = round(today_vol / avg_vol_20d if avg_vol_20d > 0 else 0, 2)

        # Price change 30d
        if len(closes) >= 22:
            price_30d_ago = float(closes.iloc[-22])
            result["price_change_30d"] = round((spot - price_30d_ago) / price_30d_ago * 100, 1)

        # Price trend score (0–10): higher lows + above key MAs
        trend_score = 0.0
        if len(closes) >= 20:
            ma20 = closes.rolling(20).mean().iloc[-1]
            if spot > ma20:
                trend_score += 4
        if len(closes) >= 50:
            ma50 = closes.rolling(50).mean().iloc[-1]
            if spot > ma50:
                trend_score += 3
        # Higher lows over past 10 sessions
        lows = hist["Low"].iloc[-10:]
        if lows.is_monotonic_increasing or (lows.diff().dropna() > 0).sum() >= 7:
            trend_score += 3
        result["price_trend_score"] = round(trend_score, 1)

        # Breaking key level: price above 20-day high set before today
        if len(hist) >= 22:
            prior_high_20d = float(hist["High"].iloc[-22:-2].max())
            result["breaking_key_level"] = spot > prior_high_20d

        # Options data
        expirations = stock.options
        if not expirations:
            return result

        near_exp = expirations[0]
        chain = stock.option_chain(near_exp)
        calls = chain.calls

        if calls.empty:
            return result

        # Call volume ratio vs 20-day average call volume
        today_call_vol = float(calls["volume"].fillna(0).sum())

        # Estimate 20d avg call volume using open interest as proxy
        # (yfinance doesn't give historical volume; OI / 20 is a rough proxy)
        avg_call_oi = float(calls["openInterest"].fillna(0).sum())
        avg_daily_call_vol_est = avg_call_oi / 20 if avg_call_oi > 0 else 1
        result["call_volume_ratio"] = round(today_call_vol / avg_daily_call_vol_est if avg_daily_call_vol_est > 0 else 0, 2)

        # Call OI change: compare OI on strikes above spot to a baseline
        # Use 5-day OI trend heuristic: high OI concentration near ATM strikes above spot
        calls_above = calls[calls["strike"] > spot]
        if not calls_above.empty:
            total_oi_above = float(calls_above["openInterest"].fillna(0).sum())
            # Compare to total OI across all strikes as a concentration ratio
            total_oi = float(calls["openInterest"].fillna(0).sum())
            concentration = (total_oi_above / total_oi * 100) if total_oi > 0 else 0
            # Map concentration above spot (0–100%) to an OI change proxy (0–30%)
            # High concentration above spot suggests recent accumulation
            result["call_oi_pct_change"] = round(max(0, concentration - 40), 1)

        # IV percentile: compare current avg IV to IV range over available exps
        all_ivs = []
        for exp in expirations[:3]:
            try:
                c = stock.option_chain(exp).calls
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
