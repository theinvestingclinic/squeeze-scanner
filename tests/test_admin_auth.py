import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from main import require_admin
from config import settings


class AdminAuthTests(unittest.TestCase):
    def test_admin_endpoints_are_disabled_without_token(self):
        with patch.object(settings, "admin_token", ""):
            with self.assertRaises(HTTPException) as raised:
                require_admin("")

        self.assertEqual(raised.exception.status_code, 503)

    def test_admin_endpoints_reject_wrong_token(self):
        with patch.object(settings, "admin_token", "expected"):
            with self.assertRaises(HTTPException) as raised:
                require_admin("wrong")

        self.assertEqual(raised.exception.status_code, 401)

    def test_admin_endpoints_accept_matching_token(self):
        with patch.object(settings, "admin_token", "expected"):
            self.assertIsNone(require_admin("expected"))


if __name__ == "__main__":
    unittest.main()
