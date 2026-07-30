import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from market_calendar import is_market_day, is_scan_window


EASTERN = ZoneInfo("America/New_York")


class MarketCalendarTests(unittest.TestCase):
    def test_regular_session_window(self):
        self.assertTrue(is_scan_window(datetime(2026, 7, 30, 10, 10, tzinfo=EASTERN)))
        self.assertTrue(is_scan_window(datetime(2026, 7, 30, 15, 58, tzinfo=EASTERN)))
        self.assertFalse(is_scan_window(datetime(2026, 7, 30, 9, 30, tzinfo=EASTERN)))
        self.assertFalse(is_scan_window(datetime(2026, 7, 30, 16, 30, tzinfo=EASTERN)))

    def test_weekend_and_holiday_are_closed(self):
        self.assertFalse(is_market_day(datetime(2026, 8, 1).date()))
        self.assertFalse(is_market_day(datetime(2026, 12, 25).date()))

    def test_early_close_is_respected(self):
        self.assertTrue(is_scan_window(datetime(2026, 11, 27, 12, 40, tzinfo=EASTERN)))
        self.assertFalse(is_scan_window(datetime(2026, 11, 27, 13, 10, tzinfo=EASTERN)))


if __name__ == "__main__":
    unittest.main()
