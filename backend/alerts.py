import httpx
from config import settings


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

    trigger_price = round(price * 1.03, 2) if price else "N/A"
    risk_price = round(price * 0.95, 2) if price else "N/A"

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
🚀 **Trigger:** Break above {trigger_price} with volume
❌ **Risk:** Failed break under {risk_price}{danger_label}

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
