import sys
import unittest
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

import historical
from database import Base, ScanResult
from market_calendar import is_market_day
from scoring import calculate_score


EASTERN = ZoneInfo("America/New_York")


class HistoricalCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    @staticmethod
    def prior_market_days(count: int):
        day = datetime.now(EASTERN).date() - timedelta(days=1)
        days = []
        while len(days) < count:
            if is_market_day(day):
                days.append(day)
            day -= timedelta(days=1)
        return days

    def add_scan(self, day, hour: int, call_volume: float):
        local_time = datetime.combine(day, time(hour, 0), tzinfo=EASTERN)
        scanned_at = local_time.astimezone(timezone.utc).replace(tzinfo=None)
        session = self.session_factory()
        try:
            session.add(
                ScanResult(
                    ticker="AAA",
                    scanned_at=scanned_at,
                    call_volume_ratio=call_volume,
                    call_oi_pct_change=call_volume,
                    iv_percentile=call_volume * 10,
                )
            )
            session.commit()
        finally:
            session.close()

    def test_many_intraday_rows_do_not_replace_five_distinct_sessions(self):
        days = self.prior_market_days(5)
        for index, day in enumerate(days[:4], start=1):
            self.add_scan(day, 11, index)
            self.add_scan(day, 15, index + 0.5)

        with patch.object(historical, "SessionLocal", self.session_factory):
            with patch.object(historical.settings, "calibration_min_sessions", 5):
                stats = historical.get_historical_stats("AAA")

        self.assertEqual(stats["history_points"], 8)
        self.assertEqual(stats["history_sessions"], 4)
        self.assertNotIn("call_vol_mean", stats)

        self.add_scan(days[4], 15, 5.5)
        with patch.object(historical, "SessionLocal", self.session_factory):
            with patch.object(historical.settings, "calibration_min_sessions", 5):
                calibrated = historical.get_historical_stats("AAA")

        self.assertEqual(calibrated["history_sessions"], 5)
        self.assertIn("call_vol_mean", calibrated)
        # One latest/closing observation per day feeds the baseline.
        self.assertEqual(calibrated["call_vol_mean"], 3.5)

    def test_scoring_calibration_uses_session_count_not_observation_count(self):
        data = {
            "short_interest_pct": 25,
            "_hist": {
                "history_points": 100,
                "history_sessions": 4,
                "calibration_min_sessions": 5,
            },
        }
        _, building = calculate_score(data)
        data["_hist"]["history_sessions"] = 5
        _, ready = calculate_score(data)

        self.assertFalse(building["_data_quality"]["signals_calibrated"])
        self.assertTrue(ready["_data_quality"]["signals_calibrated"])


if __name__ == "__main__":
    unittest.main()
