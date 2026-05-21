import math


def calculate_score(data: dict) -> tuple[float, dict]:
    """
    Score a ticker 0-100. Returns (total_score, breakdown).

    SETUP SCORE  (max 47): structural, pre-existing conditions.
        short_interest (20), float (10), call_oi_concentration (10),
        short_sale_flow from FINRA daily data (7)

    TRIGGER SCORE (max 60): active momentum signals.
        call_volume (15), gamma magnitude (12), price_trend (10),
        near_term_iv_rank (8), level_break (8), relative_volume (7)

    DANGER deductions (up to -25): social crowding, already squeezed.

    Total = setup + trigger - danger, capped 0-100.
    Setup and trigger are tracked separately so a pre-trigger setup
    (high SI, small float) does not look the same as an active breakout.
    """
    breakdown = {}

    # ── SETUP SIGNALS ─────────────────────────────────────────────────────────

    # Short interest (0-20) — bi-weekly FINRA/Yahoo data
    si = data.get("short_interest_pct", 0) or 0
    if si >= 30:    si_pts = 20
    elif si >= 20:  si_pts = 13
    elif si >= 10:  si_pts = 7
    else:           si_pts = 0
    breakdown["short_interest"] = si_pts

    # Float (0-10)
    float_m = data.get("float_shares_m", 0) or 0
    if float_m < 10:    float_pts = 10
    elif float_m < 50:  float_pts = 6
    elif float_m < 100: float_pts = 3
    else:               float_pts = 0
    breakdown["float"] = float_pts

    # Call OI concentration / delta (0-10)
    # When history exists: score the CHANGE in concentration vs prior scan (true buildup).
    # Fallback: raw concentration above spot.
    oi_conc = data.get("call_oi_pct_change", 0) or 0
    oi_prev = hist.get("call_oi_prev")
    if oi_prev is not None:
        oi_delta = oi_conc - oi_prev
        if oi_delta >= 10:   oi_pts = 10
        elif oi_delta >= 5:  oi_pts = 6
        elif oi_delta >= 2:  oi_pts = 3
        else:                oi_pts = 0
        breakdown["call_oi_delta"] = round(oi_delta, 1)
        breakdown["call_oi_concentration"] = oi_pts
    else:
        if oi_conc >= 20:   oi_pts = 10
        elif oi_conc >= 10: oi_pts = 6
        elif oi_conc >= 5:  oi_pts = 3
        else:               oi_pts = 0
        breakdown["call_oi_concentration"] = oi_pts

    # FINRA daily short sale flow (0-7)
    # Kept separate from bi-weekly short interest. FINRA explicitly distinguishes
    # daily short sale volume from outstanding short positions — do not conflate.
    finra_ratio = data.get("finra_short_vol_ratio") or 0
    if finra_ratio >= 0.70:   flow_pts = 7
    elif finra_ratio >= 0.60: flow_pts = 5
    elif finra_ratio >= 0.50: flow_pts = 3
    elif finra_ratio >= 0.40: flow_pts = 1
    else:                     flow_pts = 0
    breakdown["short_sale_flow"] = flow_pts

    setup_score = si_pts + float_pts + oi_pts + flow_pts

    # ── TRIGGER SIGNALS ───────────────────────────────────────────────────────

    # Call volume (0-15)
    # When history exists: z-score vs ticker's own baseline (more accurate).
    # Fallback: ratio vs OI/20 proxy.
    hist = data.get("_hist", {})
    cvr  = data.get("call_volume_ratio", 0) or 0
    if hist.get("call_vol_std", 0) > 0:
        zscore = (cvr - hist["call_vol_mean"]) / hist["call_vol_std"]
        if zscore >= 3:    cv_pts = 15
        elif zscore >= 2:  cv_pts = 10
        elif zscore >= 1:  cv_pts = 6
        elif zscore >= 0:  cv_pts = 2
        else:              cv_pts = 0
        breakdown["call_vol_zscore"] = round(zscore, 2)
    else:
        if cvr >= 5:     cv_pts = 15
        elif cvr >= 3:   cv_pts = 10
        elif cvr >= 1.5: cv_pts = 6
        else:            cv_pts = 0
    breakdown["call_volume"] = cv_pts

    # Gamma — continuous log-scaled score (0-12)
    # Negative net_gex = dealers short gamma = amplifies upside moves.
    # Magnitude matters: a small negative reading is not the same as a large one.
    net_gex = data.get("net_gex", 0) or 0
    if net_gex >= 0:
        gamma_pts = 0.0
    else:
        # log10 of absolute GEX, capped at 8 decades → mapped to 0-12 pts
        magnitude = min(math.log10(max(abs(net_gex), 1)), 8)
        gamma_pts = round(min(magnitude / 8 * 12, 12), 1)
    breakdown["gamma"] = gamma_pts

    # Price trend (0-10)
    trend = round(min(max(data.get("price_trend_score", 0) or 0, 0), 10), 1)
    breakdown["price_trend"] = trend

    # IV rank (0-8)
    # When 30-day history exists: true rank within our own accumulated IV range.
    # Fallback: cross-expiration proxy.
    iv_raw = data.get("iv_percentile", 0) or 0
    iv_min = hist.get("iv_30d_min", 0)
    iv_max = hist.get("iv_30d_max", 0)
    if iv_max > iv_min:
        iv_rank = round((iv_raw - iv_min) / (iv_max - iv_min) * 100, 1)
        breakdown["iv_source"] = "30d_history"
    else:
        iv_rank = iv_raw
        breakdown["iv_source"] = "expiry_proxy"
    if iv_rank >= 80:   iv_pts = 8
    elif iv_rank >= 60: iv_pts = 5
    elif iv_rank >= 40: iv_pts = 2
    else:               iv_pts = 0
    breakdown["near_term_iv_rank"] = iv_pts

    # Level break (0-8)
    break_pts = 8 if data.get("breaking_key_level", False) else 0
    breakdown["level_break"] = break_pts

    # Relative volume (0-7)
    rv = data.get("relative_volume", 0) or 0
    if rv >= 3:     rv_pts = 7
    elif rv >= 2:   rv_pts = 4
    elif rv >= 1.5: rv_pts = 2
    else:           rv_pts = 0
    breakdown["relative_volume"] = rv_pts

    trigger_score = round(cv_pts + gamma_pts + trend + iv_pts + break_pts + rv_pts, 1)

    # ── DANGER DEDUCTIONS ─────────────────────────────────────────────────────

    reddit_sat = data.get("reddit_saturation", 0) or 0
    danger_penalty = round(reddit_sat * 15, 1)
    breakdown["reddit_danger"] = -danger_penalty

    already_squeezed_penalty = 0
    if (data.get("price_change_30d", 0) or 0) > 80:
        already_squeezed_penalty = 10
        breakdown["already_squeezed"] = -already_squeezed_penalty

    # ── DATA QUALITY FLAGS ────────────────────────────────────────────────────
    # Missing data should read as "unknown", not "clear" or neutral.

    history_pts = hist.get("history_points", 0)
    breakdown["_data_quality"] = {
        "has_short_data":   si > 0,
        "has_options_data": data.get("call_volume_ratio", 0) > 0,
        "has_finra_data":   data.get("finra_short_vol_ratio") is not None,
        "has_reddit_data":  data.get("reddit_data_available", False),
        "short_data_note":  "bi-weekly" if si > 0 else "unavailable",
        "history_points":   history_pts,
        "signals_calibrated": history_pts >= 5,
    }

    # ── TOTALS ────────────────────────────────────────────────────────────────

    raw = setup_score + trigger_score - danger_penalty - already_squeezed_penalty
    total = round(max(0.0, min(100.0, raw)), 1)
    setup_score = round(max(0.0, min(47.0, setup_score)), 1)
    trigger_score = round(max(0.0, min(60.0, trigger_score)), 1)

    breakdown["setup_score"] = setup_score
    breakdown["trigger_score"] = trigger_score
    breakdown["total"] = total

    return total, breakdown
