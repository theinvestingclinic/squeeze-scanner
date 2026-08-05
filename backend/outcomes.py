"""Forward outcome tracking for published squeeze candidates."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from database import Alert, ScanResult, SignalEvent


def outcome_metrics(entry_price: float, prices: list[float]) -> dict:
    usable = [float(price) for price in prices if price and price > 0]
    if entry_price <= 0 or not usable:
        return {}
    returns = [(price / entry_price - 1) * 100 for price in usable]
    return {
        "last_return": round(returns[-1], 2),
        "max_favorable": round(max(returns), 2),
        "max_drawdown": round(min(returns), 2),
    }


def _update_records(
    db: Session,
    records: list,
    *,
    timestamp_attr: str,
    price_attr: str,
) -> int:
    updated = 0

    for record in records:
        event_time = getattr(record, timestamp_attr)
        entry_price = getattr(record, price_attr)
        if not entry_price:
            prior = (
                db.query(ScanResult)
                .filter(
                    ScanResult.ticker == record.ticker,
                    ScanResult.scanned_at <= event_time,
                    ScanResult.price > 0,
                )
                .order_by(ScanResult.scanned_at.desc())
                .first()
            )
            if prior:
                setattr(record, price_attr, prior.price)
                entry_price = prior.price

        if not entry_price:
            continue

        rows = (
            db.query(ScanResult)
            .filter(
                ScanResult.ticker == record.ticker,
                ScanResult.scanned_at > event_time,
                ScanResult.scanned_at <= event_time + timedelta(days=10),
                ScanResult.price > 0,
            )
            .order_by(ScanResult.scanned_at.asc())
            .all()
        )
        by_session = {}
        for row in rows:
            if row.scanned_at.date() == event_time.date():
                continue
            by_session[row.scanned_at.date()] = row
        sessions = list(by_session.values())
        if not sessions:
            continue

        if record.return_1d is None:
            record.return_1d = outcome_metrics(entry_price, [sessions[0].price]).get(
                "last_return"
            )

        evaluation_rows = rows
        if len(sessions) >= 5:
            fifth_session = sessions[4].scanned_at.date()
            evaluation_rows = [row for row in rows if row.scanned_at.date() <= fifth_session]
        metrics = outcome_metrics(entry_price, [row.price for row in evaluation_rows])
        record.max_favorable_5d = metrics.get("max_favorable")
        record.max_drawdown_5d = metrics.get("max_drawdown")

        if len(sessions) >= 5:
            record.return_5d = outcome_metrics(entry_price, [sessions[4].price]).get(
                "last_return"
            )
            record.evaluated_at = datetime.utcnow()
        updated += 1

    return updated


def update_alert_outcomes(db: Session) -> int:
    """Update returns for detected signals and successfully delivered alerts."""
    cutoff = datetime.utcnow() - timedelta(days=14)
    alerts = db.query(Alert).filter(Alert.sent_at >= cutoff).all()
    signals = db.query(SignalEvent).filter(SignalEvent.detected_at >= cutoff).all()
    updated = _update_records(
        db,
        alerts,
        timestamp_attr="sent_at",
        price_attr="price_at_alert",
    )
    updated += _update_records(
        db,
        signals,
        timestamp_attr="detected_at",
        price_attr="price_at_signal",
    )

    if updated:
        db.commit()
    return updated
