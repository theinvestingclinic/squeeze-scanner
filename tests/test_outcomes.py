import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from outcomes import outcome_metrics


class OutcomeMetricTests(unittest.TestCase):
    def test_returns_and_excursions(self):
        metrics = outcome_metrics(100, [105, 95, 110])

        self.assertEqual(metrics["last_return"], 10.0)
        self.assertEqual(metrics["max_favorable"], 10.0)
        self.assertEqual(metrics["max_drawdown"], -5.0)

    def test_missing_prices_are_ignored(self):
        self.assertEqual(outcome_metrics(0, [100]), {})
        self.assertEqual(outcome_metrics(100, [0, None]), {})


if __name__ == "__main__":
    unittest.main()
