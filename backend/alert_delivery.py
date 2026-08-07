"""Durable signal-event and Discord outbox handling.

Signal detection is committed before any network request. Discord delivery is
therefore an output of the scanner, never the system of record for a signal.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from alerts import DiscordSendResult, discord_is_configured, send_discord_digest_result
from config import settings
from database import Alert, AlertOutbox, SignalEvent


log = logging.getLogger(__name__)
RETRYABLE_STATUSES = ("pending", "failed")

_PAYLOAD_FIELDS = (
    "ticker",
    "score",
    "setup_score",
    "trigger_score",
    "price",
    "short_interest_pct",
    "float_shares_m",
    "call_volume_ratio",
    "is_negative_gamma",
    "call_wall",
    "put_wall",
    "zero_gamma",
    "volume_zones",
    "relative_volume",
    "reddit_saturation",
    "signal_state",
)


def _signal_payload(data: dict) -> dict:
    return {key: data.get(key) for key in _PAYLOAD_FIELDS}


def is_recent_signal_duplicate(
    db: Session,
    data: dict,
    *,
    tier: int,
    now: datetime | None = None,
) -> bool:
    """Suppress oscillation spam without ever blocking a true tier upgrade."""
    cutoff = (now or datetime.utcnow()) - timedelta(hours=24)
    latest = (
        db.query(SignalEvent)
        .filter(
            SignalEvent.ticker == str(data["ticker"]).upper(),
            SignalEvent.detected_at >= cutoff,
        )
        .order_by(SignalEvent.detected_at.desc())
        .first()
    )
    if latest is None:
        return False
    if tier > latest.tier:
        return False
    if tier < latest.tier:
        return True

    score_gain = float(data.get("score", 0) or 0) - latest.score
    trigger_gain = float(data.get("trigger_score", 0) or 0) - float(
        latest.trigger_score or 0
    )
    return (
        score_gain < settings.alert_material_score_change
        and trigger_gain < settings.alert_material_trigger_change
    )


def enqueue_signal_event(
    db: Session,
    data: dict,
    *,
    scan_run_id: int,
    tier: int,
    event_type: str,
) -> SignalEvent:
    """Persist one idempotent signal and its outbox row.

    A newer unsent material event supersedes an older delivery for the same
    ticker. The older SignalEvent remains available for outcome measurement,
    while Discord receives only the freshest state and avoids stale spam.
    """
    ticker = str(data["ticker"]).upper()
    event_key = f"scan:{scan_run_id}:{ticker}:tier:{tier}"
    existing = db.query(SignalEvent).filter(SignalEvent.event_key == event_key).first()
    if existing:
        if not db.query(AlertOutbox).filter(
            AlertOutbox.signal_event_id == existing.id
        ).first():
            db.add(AlertOutbox(signal_event_id=existing.id))
        return existing

    stale_rows = (
        db.query(AlertOutbox)
        .join(SignalEvent, SignalEvent.id == AlertOutbox.signal_event_id)
        .filter(
            SignalEvent.ticker == ticker,
            AlertOutbox.status.in_(RETRYABLE_STATUSES),
        )
        .all()
    )
    for row in stale_rows:
        row.status = "superseded"
        row.next_attempt_at = None

    event = SignalEvent(
        event_key=event_key,
        scan_run_id=scan_run_id,
        ticker=ticker,
        tier=tier,
        event_type=event_type,
        score=float(data.get("score", 0) or 0),
        setup_score=data.get("setup_score"),
        trigger_score=data.get("trigger_score"),
        price_at_signal=data.get("price"),
        payload=json.dumps(_signal_payload(data), separators=(",", ":"), default=str),
    )
    db.add(event)
    db.flush()
    db.add(AlertOutbox(signal_event_id=event.id))
    return event


def _due_outbox_rows(db: Session, now: datetime, limit: int) -> list[AlertOutbox]:
    return (
        db.query(AlertOutbox)
        .join(SignalEvent, SignalEvent.id == AlertOutbox.signal_event_id)
        .filter(
            AlertOutbox.status.in_(RETRYABLE_STATUSES),
            or_(
                AlertOutbox.next_attempt_at.is_(None),
                AlertOutbox.next_attempt_at <= now,
            ),
        )
        # Oldest first prevents a quiet overflow name from being starved by a
        # stream of newer high scores. Tiers/scores order events of equal age.
        .order_by(
            AlertOutbox.created_at.asc(),
            SignalEvent.tier.desc(),
            SignalEvent.score.desc(),
        )
        .limit(max(1, limit))
        .all()
    )


def _delivery_retry_at(now: datetime, result: DiscordSendResult) -> datetime:
    if result.retryable:
        seconds = max(
            result.retry_after_seconds or 0,
            settings.alert_outbox_retry_minutes * 60,
        )
    else:
        seconds = settings.alert_outbox_permanent_retry_hours * 60 * 60
    return now + timedelta(seconds=seconds)


def _digest_payloads(
    selected: list[tuple[AlertOutbox, SignalEvent]],
    current_candidates: list[dict] | None,
    limit: int,
) -> list[dict]:
    """Keep every queued event, then fill the digest with the current shortlist."""
    current_payloads = [_signal_payload(item) for item in current_candidates or []]
    current_by_ticker = {
        str(item.get("ticker", "")).upper(): item
        for item in current_payloads
        if item.get("ticker")
    }

    payloads = []
    included_tickers = set()
    for _, event in selected:
        stored = json.loads(event.payload)
        stored.setdefault(
            "signal_state",
            "active_trigger" if event.tier == 2 else "setup_watch",
        )
        ticker = str(stored.get("ticker", event.ticker)).upper()
        # Prefer fresh scan values when the transitioned name remains on the
        # current shortlist; otherwise retain the durable event snapshot.
        payloads.append(current_by_ticker.get(ticker, stored))
        included_tickers.add(ticker)

    for item in current_payloads:
        ticker = str(item.get("ticker", "")).upper()
        if not ticker or ticker in included_tickers:
            continue
        payloads.append(item)
        included_tickers.add(ticker)
        if len(payloads) >= limit:
            break

    state_rank = {"active_trigger": 2, "setup_watch": 1, "monitor": 0}
    payloads.sort(
        key=lambda item: (
            state_rank.get(str(item.get("signal_state", "")), 1),
            float(item.get("score", 0) or 0),
        ),
        reverse=True,
    )
    return payloads[:limit]


async def deliver_pending_alerts(
    db: Session,
    alert_threshold: int,
    current_candidates: list[dict] | None = None,
) -> int:
    """Deliver one ranked shortlist and durably update its triggering events."""
    if not discord_is_configured():
        return 0

    now = datetime.utcnow()
    digest_limit = max(1, settings.alert_digest_max_names)
    rows = _due_outbox_rows(db, now, digest_limit)
    if not rows:
        return 0

    events = {
        event.id: event
        for event in db.query(SignalEvent)
        .filter(SignalEvent.id.in_([row.signal_event_id for row in rows]))
        .all()
    }
    selected = [(row, events.get(row.signal_event_id)) for row in rows]
    selected = [(row, event) for row, event in selected if event is not None]
    if not selected:
        return 0

    payloads = _digest_payloads(selected, current_candidates, digest_limit)
    result = await send_discord_digest_result(payloads, alert_threshold)
    attempted_at = datetime.utcnow()

    for row, event in selected:
        row.attempt_count += result.attempts
        if result.attempted:
            row.last_attempt_at = attempted_at

        if result.success:
            alert = Alert(
                ticker=event.ticker,
                score=event.score,
                price_at_alert=event.price_at_signal,
                message=(
                    f"{'Active trigger' if event.tier == 2 else 'Setup watch'} "
                    f"{event.event_type.replace('_', ' ')} at {event.score}/100"
                ),
                sent_at=attempted_at,
            )
            db.add(alert)
            db.flush()
            row.status = "sent"
            row.sent_at = attempted_at
            row.next_attempt_at = None
            row.alert_id = alert.id
        else:
            row.status = "failed"
            row.last_failure_at = attempted_at
            row.last_error_code = result.error_code
            row.next_attempt_at = _delivery_retry_at(attempted_at, result)

    db.commit()
    if result.success:
        return len(selected)

    # Only controlled error codes are logged. HTTP bodies, exception strings,
    # endpoint URLs, channel IDs, and credentials never enter application logs.
    log.warning(
        "Discord squeeze digest remains queued: %s (%s event(s), %s HTTP attempt(s))",
        result.error_code,
        len(selected),
        result.attempts,
    )
    return 0


def get_alert_health(db: Session) -> dict:
    """Return credential-free alert delivery health for /api/health."""
    configured = discord_is_configured()
    retryable = db.query(AlertOutbox).filter(
        AlertOutbox.status.in_(RETRYABLE_STATUSES)
    )
    pending_count = retryable.count()
    failed_count = retryable.filter(AlertOutbox.status == "failed").count()

    last_attempt_row = (
        db.query(AlertOutbox)
        .filter(AlertOutbox.last_attempt_at.isnot(None))
        .order_by(AlertOutbox.last_attempt_at.desc())
        .first()
    )
    last_success_row = (
        db.query(AlertOutbox)
        .filter(AlertOutbox.sent_at.isnot(None))
        .order_by(AlertOutbox.sent_at.desc())
        .first()
    )
    last_failure_row = (
        db.query(AlertOutbox)
        .filter(AlertOutbox.last_failure_at.isnot(None))
        .order_by(AlertOutbox.last_failure_at.desc())
        .first()
    )

    last_success = last_success_row.sent_at if last_success_row else None
    last_failure = last_failure_row.last_failure_at if last_failure_row else None
    if not configured:
        status = "not_configured"
    elif last_failure and (not last_success or last_failure > last_success):
        status = "degraded"
    elif pending_count:
        status = "pending"
    elif last_success:
        status = "healthy"
    else:
        status = "ready"

    return {
        "configured": configured,
        "status": status,
        "pending_count": pending_count,
        "failed_count": failed_count,
        "last_attempt": (
            last_attempt_row.last_attempt_at.isoformat() if last_attempt_row else None
        ),
        "last_success": last_success.isoformat() if last_success else None,
        "last_failure": last_failure.isoformat() if last_failure else None,
        "last_error": last_failure_row.last_error_code if last_failure_row else None,
    }
