import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import alerts
from eligibility import ELIGIBLE_COMMON_STOCK
from scanner import is_material_transition, should_send_alert


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


if __name__ == "__main__":
    unittest.main()
