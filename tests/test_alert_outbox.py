import asyncio
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import alert_delivery
import alerts
from alerts import DiscordSendResult
from database import Alert, AlertOutbox, Base, SignalEvent


class AlertOutboxTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    @staticmethod
    def signal(ticker: str, score: float = 76) -> dict:
        return {
            "ticker": ticker,
            "score": score,
            "setup_score": 30,
            "trigger_score": 30,
            "price": 10,
            "short_interest_pct": 25,
            "relative_volume": 2.5,
        }

    def enqueue(self, ticker: str, run_id: int, score: float = 76, tier: int = 2):
        event = alert_delivery.enqueue_signal_event(
            self.session,
            self.signal(ticker, score),
            scan_run_id=run_id,
            tier=tier,
            event_type="tier_upgrade",
        )
        self.session.commit()
        return event

    def test_enqueue_is_idempotent_for_same_scan_event(self):
        first = self.enqueue("AAA", 10)
        second = self.enqueue("AAA", 10)

        self.assertEqual(first.id, second.id)
        self.assertEqual(self.session.query(SignalEvent).count(), 1)
        self.assertEqual(self.session.query(AlertOutbox).count(), 1)

    def test_newer_event_supersedes_stale_delivery_but_keeps_both_signals(self):
        first = self.enqueue("AAA", 10, score=60, tier=1)
        second = self.enqueue("AAA", 11, score=76, tier=2)

        first_row = self.session.query(AlertOutbox).filter_by(signal_event_id=first.id).one()
        second_row = self.session.query(AlertOutbox).filter_by(signal_event_id=second.id).one()
        self.assertEqual(first_row.status, "superseded")
        self.assertEqual(second_row.status, "pending")
        self.assertEqual(self.session.query(SignalEvent).count(), 2)

    def test_recent_dedupe_blocks_repeat_but_never_tier_upgrade(self):
        self.enqueue("AAA", 10, score=74.9, tier=1)

        repeat = self.signal("AAA", 75)
        repeat["trigger_score"] = 30
        self.assertTrue(
            alert_delivery.is_recent_signal_duplicate(
                self.session,
                repeat,
                tier=1,
            )
        )
        self.assertFalse(
            alert_delivery.is_recent_signal_duplicate(
                self.session,
                repeat,
                tier=2,
            )
        )

    def test_unconfigured_delivery_keeps_event_pending(self):
        self.enqueue("AAA", 10)
        with patch.object(alert_delivery, "discord_is_configured", return_value=False):
            delivered = asyncio.run(
                alert_delivery.deliver_pending_alerts(self.session, 75)
            )

        self.assertEqual(delivered, 0)
        row = self.session.query(AlertOutbox).one()
        self.assertEqual(row.status, "pending")
        self.assertEqual(row.attempt_count, 0)

    def test_client_construction_failure_is_recorded_in_outbox_health(self):
        self.enqueue("AAA", 10)
        with patch.object(alert_delivery, "discord_is_configured", return_value=True):
            with patch.object(
                alerts.settings,
                "discord_webhook_url",
                "https://discord.com/api/webhooks/id/token",
            ):
                with patch.object(
                    alerts.httpx,
                    "AsyncClient",
                    side_effect=RuntimeError("credential-bearing client failure"),
                ):
                    delivered = asyncio.run(
                        alert_delivery.deliver_pending_alerts(self.session, 75)
                    )
            health = alert_delivery.get_alert_health(self.session)

        self.assertEqual(delivered, 0)
        row = self.session.query(AlertOutbox).one()
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.attempt_count, 0)
        self.assertEqual(row.last_error_code, "client_error")
        self.assertIsNotNone(row.last_attempt_at)
        self.assertIsNotNone(row.last_failure_at)
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["last_error"], "client_error")

    def test_oversized_digest_is_not_silently_marked_sent(self):
        ticker = "X" * alerts.DISCORD_DIGEST_MAX_CHARS
        self.enqueue(ticker, 10)
        with patch.object(alert_delivery, "discord_is_configured", return_value=True):
            with patch.object(
                alerts.settings,
                "discord_webhook_url",
                "https://discord.com/api/webhooks/id/token",
            ):
                with patch.object(alerts.httpx, "AsyncClient") as client:
                    delivered = asyncio.run(
                        alert_delivery.deliver_pending_alerts(self.session, 75)
                    )

        self.assertEqual(delivered, 0)
        row = self.session.query(AlertOutbox).one()
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.last_error_code, "digest_too_long")
        self.assertIsNotNone(row.last_attempt_at)
        self.assertIsNotNone(row.last_failure_at)
        self.assertEqual(self.session.query(Alert).count(), 0)
        client.assert_not_called()

    def test_digest_cap_sends_five_and_retains_overflow(self):
        for index in range(7):
            self.enqueue(f"T{index}", index + 1, score=80 - index)
        success = DiscordSendResult(success=True, attempted=True, attempts=1)

        with patch.object(alert_delivery, "discord_is_configured", return_value=True):
            with patch.object(
                alert_delivery,
                "send_discord_digest_result",
                return_value=success,
            ) as send:
                with patch.object(alert_delivery.settings, "alert_digest_max_names", 5):
                    delivered = asyncio.run(
                        alert_delivery.deliver_pending_alerts(self.session, 75)
                    )

                    self.assertEqual(delivered, 5)
                    self.assertEqual(len(send.call_args.args[0]), 5)
                    self.assertEqual(
                        self.session.query(AlertOutbox).filter_by(status="pending").count(),
                        2,
                    )

                    delivered_later = asyncio.run(
                        alert_delivery.deliver_pending_alerts(self.session, 75)
                    )

        self.assertEqual(delivered_later, 2)
        self.assertEqual(len(send.call_args.args[0]), 2)
        self.assertEqual(self.session.query(AlertOutbox).filter_by(status="sent").count(), 7)
        self.assertEqual(self.session.query(AlertOutbox).filter_by(status="pending").count(), 0)
        self.assertEqual(self.session.query(Alert).count(), 7)

    def test_failed_delivery_is_retried_on_later_scan(self):
        self.enqueue("AAA", 10)
        failure = DiscordSendResult(
            success=False,
            attempted=True,
            attempts=3,
            error_code="network_error",
            retryable=True,
        )
        success = DiscordSendResult(success=True, attempted=True, attempts=1)

        with patch.object(alert_delivery, "discord_is_configured", return_value=True):
            with patch.object(
                alert_delivery,
                "send_discord_digest_result",
                return_value=failure,
            ):
                asyncio.run(alert_delivery.deliver_pending_alerts(self.session, 75))

            row = self.session.query(AlertOutbox).one()
            self.assertEqual(row.status, "failed")
            self.assertEqual(row.attempt_count, 3)
            self.assertEqual(row.last_error_code, "network_error")
            row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            self.session.commit()

            with patch.object(
                alert_delivery,
                "send_discord_digest_result",
                return_value=success,
            ):
                delivered = asyncio.run(
                    alert_delivery.deliver_pending_alerts(self.session, 75)
                )

        self.assertEqual(delivered, 1)
        row = self.session.query(AlertOutbox).one()
        self.assertEqual(row.status, "sent")
        self.assertEqual(row.attempt_count, 4)
        self.assertEqual(self.session.query(Alert).count(), 1)

    def test_health_is_credential_free_and_reports_queue_state(self):
        self.enqueue("AAA", 10)
        with patch.object(alert_delivery, "discord_is_configured", return_value=False):
            health = alert_delivery.get_alert_health(self.session)

        self.assertEqual(
            health,
            {
                "configured": False,
                "status": "not_configured",
                "pending_count": 1,
                "failed_count": 0,
                "last_attempt": None,
                "last_success": None,
                "last_failure": None,
                "last_error": None,
            },
        )
        serialized = str(health).lower()
        self.assertNotIn("webhook", serialized)
        self.assertNotIn("token", serialized)

    def test_health_reports_safe_failure_and_recovery_timestamps(self):
        self.enqueue("AAA", 10)
        failure = DiscordSendResult(
            success=False,
            attempted=True,
            attempts=3,
            error_code="rate_limited",
            retryable=True,
        )
        success = DiscordSendResult(success=True, attempted=True, attempts=1)

        with patch.object(alert_delivery, "discord_is_configured", return_value=True):
            with patch.object(
                alert_delivery,
                "send_discord_digest_result",
                return_value=failure,
            ):
                asyncio.run(alert_delivery.deliver_pending_alerts(self.session, 75))
            degraded = alert_delivery.get_alert_health(self.session)

            row = self.session.query(AlertOutbox).one()
            row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            self.session.commit()
            with patch.object(
                alert_delivery,
                "send_discord_digest_result",
                return_value=success,
            ):
                asyncio.run(alert_delivery.deliver_pending_alerts(self.session, 75))
            recovered = alert_delivery.get_alert_health(self.session)

        self.assertEqual(degraded["status"], "degraded")
        self.assertEqual(degraded["last_error"], "rate_limited")
        self.assertIsNotNone(degraded["last_attempt"])
        self.assertIsNotNone(degraded["last_failure"])
        self.assertEqual(recovered["status"], "healthy")
        self.assertEqual(recovered["pending_count"], 0)
        self.assertIsNotNone(recovered["last_success"])


if __name__ == "__main__":
    unittest.main()
