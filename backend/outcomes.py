"""Forward outcome tracking for published squeeze candidates."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from database import Alert, ScanResult


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


def update_alert_outcomes(db: Session) -> int:
    """Update 1/5-session returns and excursion for recent alert records."""
    cutoff = datetime.utcnow() - timedelta(days=14)
    alerts = db.query(Alert).filter(Alert.sent_at >= cutoff).all()
    updated = 0

    for alert in alerts:
        if not alert.price_at_alert:
            prior = (
                db.query(ScanResult)
                .filter(
                    ScanResult.ticker == alert.ticker,
                    ScanResult.scanned_at <= alert.sent_at,
                    ScanResult.price > 0,
                )
                .order_by(ScanResult.scanned_at.desc())
                .first()
            )
            if prior:
                alert.price_at_alert = prior.price

        if not alert.price_at_alert:
            continue

        rows = (
            db.query(ScanResult)
            .filter(
                ScanResult.ticker == alert.ticker,
                ScanResult.scanned_at > alert.sent_at,
                ScanResult.scanned_at <= alert.sent_at + timedelta(days=10),
                ScanResult.price > 0,
            )
            .order_by(ScanResult.scanned_at.asc())
            .all()
        )
        by_session = {}
        for row in rows:
            if row.scanned_at.date() == alert.sent_at.date():
                continue
            by_session[row.scanned_at.date()] = row
        sessions = list(by_session.values())
        if not sessions:
            continue

        if alert.return_1d is None:
            alert.return_1d = outcome_metrics(alert.price_at_alert, [sessions[0].price]).get(
                "last_return"
            )

        evaluation_rows = rows
        if len(sessions) >= 5:
            fifth_session = sessions[4].scanned_at.date()
            evaluation_rows = [row for row in rows if row.scanned_at.date() <= fifth_session]
        metrics = outcome_metrics(alert.price_at_alert, [row.price for row in evaluation_rows])
        alert.max_favorable_5d = metrics.get("max_favorable")
        alert.max_drawdown_5d = metrics.get("max_drawdown")

        if len(sessions) >= 5:
            alert.return_5d = outcome_metrics(alert.price_at_alert, [sessions[4].price]).get(
                "last_return"
            )
            alert.evaluated_at = datetime.utcnow()
        updated += 1

    if updated:
        db.commit()
    return updated
