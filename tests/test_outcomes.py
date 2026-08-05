import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from database import AlertOutbox, Base, ScanResult, SignalEvent
from outcomes import outcome_metrics, update_alert_outcomes


class OutcomeMetricTests(unittest.TestCase):
    def test_returns_and_excursions(self):
        metrics = outcome_metrics(100, [105, 95, 110])

        self.assertEqual(metrics["last_return"], 10.0)
        self.assertEqual(metrics["max_favorable"], 10.0)
        self.assertEqual(metrics["max_drawdown"], -5.0)

    def test_missing_prices_are_ignored(self):
        self.assertEqual(outcome_metrics(0, [100]), {})
        self.assertEqual(outcome_metrics(100, [0, None]), {})

    def test_pending_signal_outcome_is_measured_without_discord_delivery(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            detected_at = datetime.utcnow() - timedelta(days=2)
            signal = SignalEvent(
                event_key="scan:1:AAA:tier:2",
                scan_run_id=1,
                ticker="AAA",
                tier=2,
                event_type="tier_upgrade",
                score=80,
                price_at_signal=100,
                payload='{"ticker":"AAA","score":80}',
                detected_at=detected_at,
            )
            session.add(signal)
            session.flush()
            session.add(AlertOutbox(signal_event_id=signal.id, status="pending"))
            session.add(
                ScanResult(
                    ticker="AAA",
                    price=105,
                    scanned_at=detected_at + timedelta(days=1),
                )
            )
            session.commit()

            update_alert_outcomes(session)
            session.refresh(signal)

            self.assertEqual(signal.return_1d, 5.0)
            self.assertEqual(signal.max_favorable_5d, 5.0)
            self.assertEqual(session.query(AlertOutbox).one().status, "pending")
        finally:
            session.close()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
