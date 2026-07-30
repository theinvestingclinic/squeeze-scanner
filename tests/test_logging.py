import logging
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from main import SensitiveUrlFilter


class SensitiveUrlFilterTests(unittest.TestCase):
    def test_discord_webhook_token_is_redacted(self):
        record = logging.LogRecord(
            "httpx",
            logging.INFO,
            __file__,
            1,
            "HTTP Request: POST https://discord.com/api/webhooks/123/sensitive-token",
            (),
            None,
        )

        self.assertTrue(SensitiveUrlFilter().filter(record))
        self.assertNotIn("sensitive-token", record.getMessage())
        self.assertIn("[REDACTED]", record.getMessage())


if __name__ == "__main__":
    unittest.main()
