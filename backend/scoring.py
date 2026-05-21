import json


def calculate_score(data: dict) -> tuple[float, dict]:
    """
    Score a ticker 0-100 based on squeeze signal strength.

    Tier 1 — Foundation     (40 pts max): short interest, float, price trend
    Tier 2 — Options Fuel   (45 pts max): call volume, gamma, OI buildup, IV
    Tier 3 — Confirmation   (15 pts max): level break, relative volume
    Danger deductions       (up to -25):  social saturation, already squeezed
    Catalyst multiplier     (×1.15 max):  not automated in free version
    """
    breakdown = {}
    score = 0.0

    # ── Tier 1: Foundation ──────────────────────────────────────────────────

    si = data.get("short_interest_pct", 0) or 0
    if si >= 30:
        si_pts = 20
    elif si >= 20:
        si_pts = 13
    elif si >= 10:
        si_pts = 7
    else:
        si_pts = 0

    # FINRA daily short volume: if shorts are actively piling in today, boost up to +5
    finra_ratio = data.get("finra_short_vol_ratio") or 0
    if finra_ratio >= 0.70:
        si_pts = min(si_pts + 5, 25)
    elif finra_ratio >= 0.60:
        si_pts = min(si_pts + 3, 25)
    elif finra_ratio >= 0.50:
        si_pts = min(si_pts + 1, 25)

    breakdown["short_interest"] = si_pts
    score += si_pts

    float_m = data.get("float_shares_m", 0) or 0
    if float_m < 10:
        float_pts = 10
    elif float_m < 50:
        float_pts = 6
    elif float_m < 100:
        float_pts = 3
    else:
        float_pts = 0
    breakdown["float"] = float_pts
    score += float_pts

    trend = min(max(data.get("price_trend_score", 0) or 0, 0), 10)
    breakdown["price_trend"] = round(trend, 1)
    score += trend

    # ── Tier 2: Options Fuel ────────────────────────────────────────────────

    cvr = data.get("call_volume_ratio", 0) or 0
    if cvr >= 5:
        cv_pts = 15
    elif cvr >= 3:
        cv_pts = 10
    elif cvr >= 1.5:
        cv_pts = 6
    else:
        cv_pts = 0
    breakdown["call_volume"] = cv_pts
    score += cv_pts

    gamma_pts = 12 if data.get("is_negative_gamma", False) else 0
    breakdown["gamma"] = gamma_pts
    score += gamma_pts

    oi_change = data.get("call_oi_pct_change", 0) or 0
    if oi_change >= 20:
        oi_pts = 10
    elif oi_change >= 10:
        oi_pts = 6
    elif oi_change >= 5:
        oi_pts = 3
    else:
        oi_pts = 0
    breakdown["call_oi_buildup"] = oi_pts
    score += oi_pts

    iv_pct = data.get("iv_percentile", 0) or 0
    if iv_pct >= 80:
        iv_pts = 8
    elif iv_pct >= 60:
        iv_pts = 5
    elif iv_pct >= 40:
        iv_pts = 2
    else:
        iv_pts = 0
    breakdown["iv_expansion"] = iv_pts
    score += iv_pts

    # ── Tier 3: Confirmation ────────────────────────────────────────────────

    break_pts = 8 if data.get("breaking_key_level", False) else 0
    breakdown["level_break"] = break_pts
    score += break_pts

    rv = data.get("relative_volume", 0) or 0
    if rv >= 3:
        rv_pts = 7
    elif rv >= 2:
        rv_pts = 4
    elif rv >= 1.5:
        rv_pts = 2
    else:
        rv_pts = 0
    breakdown["relative_volume"] = rv_pts
    score += rv_pts

    # ── Danger deductions ───────────────────────────────────────────────────

    reddit_sat = data.get("reddit_saturation", 0) or 0
    danger_penalty = round(reddit_sat * 15, 1)
    breakdown["reddit_danger"] = -danger_penalty
    score -= danger_penalty

    already_squeezed_penalty = 0
    if (data.get("price_change_30d", 0) or 0) > 80:
        already_squeezed_penalty = 10
        breakdown["already_squeezed"] = -already_squeezed_penalty
        score -= already_squeezed_penalty

    score = round(max(0.0, min(100.0, score)), 1)
    breakdown["total"] = score

    return score, breakdown
