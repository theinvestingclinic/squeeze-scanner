import yfinance as yf
import numpy as np


def get_volume_zones(ticker: str, lookback_days: int = 30, n_zones: int = 3) -> list[dict]:
    """
    Identify significant volume-weighted price zones over the past N days.

    These are NOT dark pool prints — we label them honestly as high-volume
    accumulation zones. They're useful as support/resistance context and
    serve as a free proxy until Unusual Whales API is added.

    Returns a list of zone dicts: {low, high, midpoint, volume_pct}
    sorted by significance descending.
    """
    try:
        hist = yf.Ticker(ticker).history(period=f"{lookback_days}d")
        if hist.empty or len(hist) < 5:
            return []

        prices = hist["Close"].values
        volumes = hist["Volume"].values

        price_min = prices.min()
        price_max = prices.max()
        if price_max <= price_min:
            return []

        # Build 20-bucket volume profile
        n_buckets = 20
        bucket_edges = np.linspace(price_min, price_max, n_buckets + 1)
        bucket_volumes = np.zeros(n_buckets)

        for price, vol in zip(prices, volumes):
            idx = min(int((price - price_min) / (price_max - price_min) * n_buckets), n_buckets - 1)
            bucket_volumes[idx] += vol

        total_vol = bucket_volumes.sum()
        if total_vol == 0:
            return []

        # Find buckets with > 1.5x average volume
        avg_bucket_vol = total_vol / n_buckets
        significant = [
            i for i, v in enumerate(bucket_volumes)
            if v >= avg_bucket_vol * 1.5
        ]

        # Merge adjacent buckets into zones
        zones = []
        if significant:
            groups: list[list[int]] = [[significant[0]]]
            for idx in significant[1:]:
                if idx == groups[-1][-1] + 1:
                    groups[-1].append(idx)
                else:
                    groups.append([idx])

            for group in groups:
                low = round(bucket_edges[group[0]], 2)
                high = round(bucket_edges[group[-1] + 1], 2)
                mid = round((low + high) / 2, 2)
                zone_vol = bucket_volumes[group].sum()
                zones.append({
                    "low": low,
                    "high": high,
                    "midpoint": mid,
                    "volume_pct": round(zone_vol / total_vol * 100, 1),
                })

        # Return top N zones sorted by volume significance
        zones.sort(key=lambda z: z["volume_pct"], reverse=True)
        return zones[:n_zones]

    except Exception:
        return []
