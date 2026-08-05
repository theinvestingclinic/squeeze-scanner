import asyncio
import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import alerts
from eligibility import ELIGIBLE_COMMON_STOCK
from scanner import is_material_transition, material_transition_type, should_send_alert


class DiscordDestinationTests(unittest.TestCase):
    def test_webhook_takes_priority(self):
        with patch.object(alerts.settings, "discord_webhook_url", "https://discordapp.com/api/webhooks/example"):
            with patch.object(alerts.settings, "discord_bot_token", "token"):
                url, headers = alerts.discord_destination()

        self.assertEqual(url, "https://discord.com/api/webhooks/example")
        self.assertEqual(headers, {})

    def test_bot_token_posts_to_squeeze_channel(self):
        with patch.object(alerts.settings, "discord_webhook_url", ""):
            with patch.object(alerts.settings, "discord_bot_token", "token"):
                with patch.object(alerts.settings, "discord_channel_id", "1505287069512237177"):
                    url, headers = alerts.discord_destination()

        self.assertEqual(url, "https://discord.com/api/v10/channels/1505287069512237177/messages")
        self.assertEqual(headers, {"Authorization": "Bot token"})


class DiscordDigestTests(unittest.TestCase):
    @staticmethod
    def item(ticker: str, score: float = 76) -> dict:
        return {
            "ticker": ticker,
            "score": score,
            "setup_score": 30,
            "trigger_score": 31,
            "short_interest_pct": 25,
            "relative_volume": 2.5,
            "call_volume_ratio": 1.8,
        }

    @staticmethod
    def batch_line(message: str) -> str:
        return next(line for line in message.splitlines() if line.startswith("Batch ID:"))

    def test_digest_includes_every_selected_name_with_stable_payload_marker(self):
        items = [self.item("AAA"), self.item("BBB", 70)]

        message = alerts.format_digest(items, 75)
        same_payload = alerts.format_digest([dict(item) for item in items], 75)
        changed_payload = alerts.format_digest(
            [self.item("AAA", 77), self.item("BBB", 70)],
            75,
        )

        self.assertIn("**$AAA —", message)
        self.assertIn("**$BBB —", message)
        self.assertLessEqual(len(message), alerts.DISCORD_DIGEST_MAX_CHARS)
        self.assertEqual(self.batch_line(message), self.batch_line(same_payload))
        self.assertNotEqual(self.batch_line(message), self.batch_line(changed_payload))
        self.assertRegex(self.batch_line(message), r"^Batch ID: `sqz-[0-9a-f]{12}`$")

    def test_oversized_digest_fails_before_any_network_client_is_created(self):
        items = [self.item("X" * alerts.DISCORD_DIGEST_MAX_CHARS)]

        with self.assertRaises(alerts.DigestTooLongError):
            alerts.format_digest(items, 75)

        with patch.object(
            alerts.settings,
            "discord_webhook_url",
            "https://discord.com/api/webhooks/id/token",
        ):
            with patch.object(alerts.httpx, "AsyncClient") as client:
                result = asyncio.run(alerts.send_discord_digest_result(items, 75))

        self.assertFalse(result.success)
        self.assertTrue(result.attempted)
        self.assertEqual(result.attempts, 0)
        self.assertEqual(result.error_code, "digest_too_long")
        self.assertFalse(result.retryable)
        client.assert_not_called()


class _FakeAsyncClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, *args, **kwargs):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class DiscordRetryTests(unittest.TestCase):
    def test_client_construction_failure_returns_safe_controlled_result(self):
        sensitive_detail = "https://discord.com/api/webhooks/id/sensitive-token"
        with patch.object(
            alerts.settings,
            "discord_webhook_url",
            "https://discord.com/api/webhooks/id/token",
        ):
            with patch.object(
                alerts.httpx,
                "AsyncClient",
                side_effect=RuntimeError(sensitive_detail),
            ):
                with self.assertLogs(alerts.log, logging.WARNING) as captured:
                    result = asyncio.run(alerts._send_message_result("test"))

        self.assertFalse(result.success)
        self.assertTrue(result.attempted)
        self.assertEqual(result.attempts, 0)
        self.assertEqual(result.error_code, "client_error")
        self.assertFalse(result.retryable)
        rendered_logs = " ".join(captured.output)
        self.assertNotIn(sensitive_detail, rendered_logs)
        self.assertNotIn("sensitive-token", rendered_logs)

    def test_retries_rate_limit_and_server_error_before_success(self):
        client = _FakeAsyncClient(
            [
                httpx.Response(429, json={"retry_after": 0}),
                httpx.Response(503),
                httpx.Response(204),
            ]
        )
        with patch.object(alerts.settings, "discord_webhook_url", "https://discord.com/api/webhooks/id/token"):
            with patch.object(alerts.settings, "discord_max_attempts", 3):
                with patch.object(alerts.httpx, "AsyncClient", return_value=client):
                    with patch.object(alerts.asyncio, "sleep", new=AsyncMock()) as sleep:
                        result = asyncio.run(alerts._send_message_result("test"))

        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(client.calls, 3)
        self.assertEqual(sleep.await_count, 2)

    def test_retries_network_errors_without_exposing_exception(self):
        request = httpx.Request("POST", "https://discord.com/api/webhooks/id/secret")
        client = _FakeAsyncClient(
            [
                httpx.ConnectError("contains-sensitive-url", request=request),
                httpx.Response(204),
            ]
        )
        with patch.object(alerts.settings, "discord_webhook_url", "https://discord.com/api/webhooks/id/token"):
            with patch.object(alerts.settings, "discord_max_attempts", 2):
                with patch.object(alerts.httpx, "AsyncClient", return_value=client):
                    with patch.object(alerts.asyncio, "sleep", new=AsyncMock()):
                        result = asyncio.run(alerts._send_message_result("test"))

        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)

    def test_does_not_retry_non_retryable_http_error(self):
        client = _FakeAsyncClient([httpx.Response(401, text="secret response body")])
        with patch.object(alerts.settings, "discord_webhook_url", "https://discord.com/api/webhooks/id/token"):
            with patch.object(alerts.settings, "discord_max_attempts", 3):
                with patch.object(alerts.httpx, "AsyncClient", return_value=client):
                    with self.assertLogs(alerts.log, logging.WARNING) as captured:
                        result = asyncio.run(alerts._send_message_result("test"))

        self.assertFalse(result.success)
        self.assertEqual(result.error_code, "discord_http_error")
        self.assertEqual(result.attempts, 1)
        self.assertFalse(result.retryable)
        self.assertNotIn("secret response body", " ".join(captured.output))
        self.assertNotIn("/api/webhooks/", " ".join(captured.output))

    def test_unconfigured_destination_does_not_attempt_delivery(self):
        with patch.object(alerts.settings, "discord_webhook_url", ""):
            with patch.object(alerts.settings, "discord_bot_token", ""):
                with patch.object(alerts.httpx, "AsyncClient") as client:
                    result = asyncio.run(alerts._send_message_result("test"))

        self.assertFalse(result.success)
        self.assertFalse(result.attempted)
        self.assertEqual(result.error_code, "not_configured")
        client.assert_not_called()


class AlertGateTests(unittest.TestCase):
    def wen_style_result(self):
        return {
            "ticker": "WEN",
            "score": 54.3,
            "setup_score": 25.0,
            "trigger_score": 32.7,
            "short_interest_pct": 32.04,
            "relative_volume": 2.28,
            "eligibility_status": ELIGIBLE_COMMON_STOCK,
            "score_breakdown": {
                "_data_quality": {
                    "has_short_data": True,
                    "signals_calibrated": True,
                },
                "_eligibility": {"status": ELIGIBLE_COMMON_STOCK},
            },
        }

    def test_potential_squeeze_result_alerts(self):
        self.assertTrue(should_send_alert(self.wen_style_result(), 75))

    def test_requires_setup_and_trigger_confirmation(self):
        weak_setup = self.wen_style_result()
        weak_setup["setup_score"] = 19.9
        weak_trigger = self.wen_style_result()
        weak_trigger["trigger_score"] = 19.9

        self.assertFalse(should_send_alert(weak_setup, 75))
        self.assertFalse(should_send_alert(weak_trigger, 75))

    def test_potential_squeeze_requires_relative_volume(self):
        low_volume = self.wen_style_result()
        low_volume["relative_volume"] = 1.9

        self.assertFalse(should_send_alert(low_volume, 75))

    def test_uncalibrated_result_never_alerts(self):
        uncalibrated = self.wen_style_result()
        uncalibrated["score_breakdown"]["_data_quality"]["signals_calibrated"] = False

        self.assertFalse(should_send_alert(uncalibrated, 75))

    def test_stable_candidate_does_not_repeat(self):
        previous = self.wen_style_result()
        current = self.wen_style_result()
        current["score"] = previous["score"] + 1

        self.assertFalse(is_material_transition(current, previous, 75))

    def test_tier_entry_is_material(self):
        previous = self.wen_style_result()
        previous["score"] = 45
        previous["relative_volume"] = 1
        current = self.wen_style_result()

        self.assertTrue(is_material_transition(current, previous, 75))

    def test_tier_upgrade_is_never_suppressed_by_small_score_change(self):
        previous = self.wen_style_result()
        previous["score"] = 74.9
        current = self.wen_style_result()
        current["score"] = 75

        self.assertEqual(
            material_transition_type(current, previous, 75),
            "tier_upgrade",
        )


if __name__ == "__main__":
    unittest.main()
