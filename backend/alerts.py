import httpx
from config import settings


def _fmt_price(value) -> str:
    if value is None:
        return "N/A"
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _trade_levels(price, call_wall, put_wall, zero_gamma, zones) -> tuple[str, str]:
    if not price:
        return "N/A", "N/A"

    upside_levels = []
    for label, level in (("zero gamma", zero_gamma), ("call wall", call_wall)):
        if level and level > price:
            upside_levels.append((level, label))

    if upside_levels:
        level, label = min(upside_levels, key=lambda item: item[0])
        trigger = f"Break above {label} {_fmt_price(level)} with volume"
    elif call_wall and price >= call_wall:
        trigger = f"Hold above call wall {_fmt_price(call_wall)} with expanding volume"
    elif zero_gamma and price >= zero_gamma:
        trigger = f"Hold above zero gamma {_fmt_price(zero_gamma)} with expanding volume"
    else:
        trigger = f"Break above {_fmt_price(price * 1.03)} with volume"

    risk_levels = []
    for label, level in (("put wall", put_wall), ("zero gamma", zero_gamma)):
        if level and level < price:
            risk_levels.append((level, label))

    for zone in zones or []:
        low = zone.get("low")
        high = zone.get("high")
        if low and high and low <= price:
            risk_levels.append((low, "volume zone support"))
            break

    if risk_levels:
        level, label = max(risk_levels, key=lambda item: item[0])
        risk = f"Failed hold above {label} {_fmt_price(level)}"
    else:
        risk = f"Failed breakout under {_fmt_price(price * 0.95)}"

    return trigger, risk


def format_alert(data: dict) -> str:
    ticker = data.get("ticker", "???")
    score = data.get("score", 0)
    si = data.get("short_interest_pct", 0)
    float_m = data.get("float_shares_m", 0)
    cvr = data.get("call_volume_ratio", 0)
    is_neg_gamma = data.get("is_negative_gamma", False)
    call_wall = data.get("call_wall")
    put_wall = data.get("put_wall")
    zero_gamma = data.get("zero_gamma")
    zones = data.get("volume_zones", [])
    rv = data.get("relative_volume", 0)
    price = data.get("price", 0)
    reddit_sat = data.get("reddit_saturation", 0)

    # Danger label
    danger_label = ""
    if reddit_sat >= 0.8:
        danger_label = "\n⚠️ **Danger:** High social media saturation — crowded trade"
    elif reddit_sat >= 0.6:
        danger_label = "\n⚠️ **Caution:** Elevated social media mentions"

    gamma_line = "Negative (squeeze fuel ✅)" if is_neg_gamma else "Positive (stabilising)"

    zone_text = ""
    if zones:
        top_zone = zones[0]
        zone_text = f"\n📦 **Volume zone:** ${top_zone['low']} – ${top_zone['high']}"

    call_wall_text = f"${call_wall}" if call_wall else "N/A"
    put_wall_text = f"${put_wall}" if put_wall else "N/A"
    zero_gamma_text = f"${zero_gamma}" if zero_gamma else "N/A"

    trigger_text, risk_text = _trade_levels(price, call_wall, put_wall, zero_gamma, zones)

    message = f"""🔥 **Squeeze Radar Alert**

**${ticker}** — Score: **{score}/100**

📊 **Short interest:** {si}% of float
📉 **Float:** {float_m}M shares
📈 **Call volume:** {cvr}x normal
⚡ **Gamma:** {gamma_line}
🎯 **Call wall:** {call_wall_text}
🛡️ **Put wall:** {put_wall_text}
🔀 **Zero gamma:** {zero_gamma_text}{zone_text}

📌 **Relative volume:** {rv}x
🚀 **Trigger:** {trigger_text}
❌ **Risk:** {risk_text}{danger_label}

*Short data refreshes bi-weekly. Verify before trading.*"""

    return message


async def send_discord_alert(data: dict) -> bool:
    if not settings.discord_webhook_url:
        return False

    message = format_alert(data)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                settings.discord_webhook_url,
                json={"content": message},
                timeout=10,
            )
            return resp.status_code in (200, 204)
    except Exception:
        return False
