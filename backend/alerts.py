import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass

import httpx
from config import settings

DISCORD_API_BASE = "https://discord.com/api/v10"
# Discord accepts at most 2,000 content characters. Keeping a small safety
# margin also covers any ambiguity around multi-code-point display characters.
DISCORD_DIGEST_MAX_CHARS = 1900
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscordSendResult:
    success: bool
    attempted: bool
    attempts: int = 0
    error_code: str | None = None
    retryable: bool = False
    retry_after_seconds: float | None = None


class DigestTooLongError(ValueError):
    """Raised when a complete digest cannot fit without dropping a candidate."""


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

    gamma_line = "Negative OI proxy (amplification risk)" if is_neg_gamma else "Positive OI proxy"

    zone_text = ""
    if zones:
        top_zone = zones[0]
        zone_text = f"\n📦 **Volume zone:** ${top_zone['low']} – ${top_zone['high']}"

    call_wall_text = f"${call_wall}" if call_wall else "N/A"
    put_wall_text = f"${put_wall}" if put_wall else "N/A"
    zero_gamma_text = f"${zero_gamma}" if zero_gamma else "N/A"

    trigger_text, risk_text = _trade_levels(price, call_wall, put_wall, zero_gamma, zones)

    message = f"""**Squeeze signal alignment**

**${ticker}** — Score: **{score}/100**

📊 **Short interest:** {si}% of float
📉 **Float:** {float_m}M shares
📈 **Call-volume/OI proxy:** {cvr}x
⚡ **Options-OI gamma proxy:** {gamma_line}
🎯 **Call wall:** {call_wall_text}
🛡️ **Put wall:** {put_wall_text}
🔀 **Zero gamma:** {zero_gamma_text}{zone_text}

📌 **Relative volume:** {rv}x
🚀 **Trigger:** {trigger_text}
❌ **Risk:** {risk_text}{danger_label}

*Research candidate, not a trade recommendation. Short interest refreshes bi-weekly and options/gamma fields are modelled proxies.*"""

    return message


def _digest_batch_marker(items: list[dict], alert_threshold: int) -> str:
    """Return a stable marker for recognizing an at-least-once replay."""
    canonical_payload = json.dumps(
        {"alert_threshold": alert_threshold, "items": items},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    digest = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()[:12]
    return f"sqz-{digest}"


def format_digest(items: list[dict], alert_threshold: int) -> str:
    lines = [
        "**Squeeze Scanner — material state changes**",
        "*Calibrated candidates only; research signals, not trade recommendations.*",
        "",
    ]
    for data in items:
        state = "Active trigger" if data.get("score", 0) >= alert_threshold else "Setup watch"
        lines.append(
            f"**${data.get('ticker', '???')} — {state}** · "
            f"{data.get('score', 0)}/100 · "
            f"setup {data.get('setup_score', 0)} · trigger {data.get('trigger_score', 0)}"
        )
        lines.append(
            f"SI {data.get('short_interest_pct', 0)}% · "
            f"time-adjusted rel vol {data.get('relative_volume', 0)}x · "
            f"call-vol/OI proxy {data.get('call_volume_ratio', 0)}x"
        )
    lines.extend(
        [
            "",
            "*Short interest is bi-weekly. Options-OI gamma and volume-zone fields are proxies. Verify source freshness before acting.*",
            "",
            f"Batch ID: `{_digest_batch_marker(items, alert_threshold)}`",
        ]
    )
    message = "\n".join(lines)
    if len(message) > DISCORD_DIGEST_MAX_CHARS:
        # Never slice a completed message: doing so could omit a selected name
        # while its durable outbox row is still marked sent.
        raise DigestTooLongError("complete digest exceeds the Discord content limit")
    return message


def _retry_delay(attempt: int, retry_after: float | None = None) -> float:
    exponential = settings.discord_retry_base_seconds * (2 ** max(0, attempt - 1))
    requested = retry_after if retry_after is not None else exponential
    return max(0.0, min(float(requested), settings.discord_retry_max_seconds))


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        try:
            payload = response.json()
            value = payload.get("retry_after") if isinstance(payload, dict) else None
        except (TypeError, ValueError):
            value = None
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


async def _send_message_result(message: str) -> DiscordSendResult:
    url, headers = discord_destination()
    if not url:
        return DiscordSendResult(
            success=False,
            attempted=False,
            error_code="not_configured",
            retryable=True,
        )

    max_attempts = max(1, settings.discord_max_attempts)
    error_code = "unknown_error"
    retryable = False
    last_delay = None
    attempt = 0

    try:
        async with httpx.AsyncClient() as client:
            for attempt in range(1, max_attempts + 1):
                try:
                    response = await client.post(
                        url,
                        json={"content": message},
                        headers=headers,
                        timeout=10,
                    )
                except httpx.RequestError:
                    error_code = "network_error"
                    retryable = True
                except Exception:
                    # Keep unexpected client failures credential-free as well.
                    error_code = "client_error"
                    retryable = False
                else:
                    if response.status_code in (200, 204):
                        return DiscordSendResult(
                            success=True,
                            attempted=True,
                            attempts=attempt,
                        )
                    if response.status_code == 429:
                        error_code = "rate_limited"
                        retryable = True
                        last_delay = _retry_after_seconds(response)
                    elif 500 <= response.status_code <= 599:
                        error_code = "discord_server_error"
                        retryable = True
                    else:
                        error_code = "discord_http_error"
                        retryable = False

                if not retryable or attempt >= max_attempts:
                    break
                last_delay = _retry_delay(attempt, last_delay)
                await asyncio.sleep(last_delay)
                last_delay = None
    except Exception:
        # Client construction, context entry, and context exit all happen outside
        # the request-level try above. Collapse them to one safe error code; never
        # expose an exception string that could contain an endpoint or credential.
        error_code = "client_error"
        retryable = False

    log.warning(
        "Discord squeeze delivery failed: %s after %s HTTP attempt(s)",
        error_code,
        attempt,
    )
    return DiscordSendResult(
        success=False,
        attempted=True,
        attempts=attempt,
        error_code=error_code,
        retryable=retryable,
        retry_after_seconds=(
            _retry_delay(attempt, last_delay) if retryable else None
        ),
    )


async def _send_message(message: str) -> bool:
    """Compatibility wrapper returning the historical boolean result."""
    return (await _send_message_result(message)).success


async def send_discord_alert(data: dict) -> bool:
    """Compatibility wrapper for manual single-name sends."""
    return await _send_message(format_alert(data))


async def send_discord_digest(items: list[dict], alert_threshold: int) -> bool:
    if not items:
        return False
    return (await send_discord_digest_result(items, alert_threshold)).success


async def send_discord_digest_result(
    items: list[dict],
    alert_threshold: int,
) -> DiscordSendResult:
    if not items:
        return DiscordSendResult(
            success=False,
            attempted=False,
            error_code="empty_digest",
            retryable=False,
        )
    try:
        message = format_digest(items, alert_threshold)
    except DigestTooLongError:
        log.warning("Discord squeeze digest rejected before delivery: digest_too_long")
        return DiscordSendResult(
            success=False,
            attempted=True,
            attempts=0,
            error_code="digest_too_long",
            retryable=False,
        )
    return await _send_message_result(message)


def discord_destination() -> tuple[str, dict[str, str]]:
    """Return the Discord endpoint for squeeze alerts.

    A channel webhook is preferred because it is scoped directly to the alert
    channel. Bot-token posting remains available for deployments that grant the
    bot explicit access to the channel.
    """
    webhook_url = settings.discord_webhook_url.strip()
    if webhook_url:
        return webhook_url.replace("https://discordapp.com/", "https://discord.com/"), {}

    bot_token = settings.discord_bot_token.strip()
    channel_id = settings.discord_channel_id.strip()
    if bot_token and channel_id:
        return (
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            {"Authorization": f"Bot {bot_token}"},
        )

    return "", {}


def discord_is_configured() -> bool:
    url, _ = discord_destination()
    return bool(url)
