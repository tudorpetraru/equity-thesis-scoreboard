from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from scripts.score import PriceSeries, entry_session, score_call, verdict


def record(rating: str = "BUY") -> dict:
    return {
        "rating": rating, "target_price": 120.0, "stop_price": 80.0,
        "generated_at": "2025-01-04T12:00:00Z",
    }


class ScoringTest(unittest.TestCase):
    def test_saturday_call_enters_on_monday(self):
        prices = {date(2025, 1, 3): 100, date(2025, 1, 6): 101}
        generated = datetime(2025, 1, 4, 12, tzinfo=timezone.utc)
        self.assertEqual(entry_session(generated, prices), date(2025, 1, 6))

    def test_after_close_enters_next_session(self):
        prices = {date(2025, 1, 6): 100, date(2025, 1, 7): 101}
        generated = datetime(2025, 1, 6, 22, tzinfo=timezone.utc)
        self.assertEqual(entry_session(generated, prices), date(2025, 1, 7))

    def test_hold_band_is_inclusive(self):
        self.assertEqual(verdict("HOLD", 0.05), "correct")
        self.assertEqual(verdict("HOLD", -0.05), "correct")
        self.assertEqual(verdict("HOLD", 0.050001), "incorrect")

    def test_excess_return_and_delisting(self):
        stock = PriceSeries(
            {date(2025, 1, 6): 100, date(2025, 6, 1): 130}, "fixture", True
        )
        spy = PriceSeries(
            {date(2025, 1, 6): 100, date(2025, 7, 7): 110, date(2026, 1, 6): 120}, "fixture", True
        )
        result = score_call(record(), stock, spy, datetime(2026, 2, 1, tzinfo=timezone.utc))
        self.assertEqual(result["horizons"]["6m"]["verdict"], "correct")
        self.assertAlmostEqual(result["horizons"]["6m"]["excess_return"], 0.2)
        self.assertTrue(result["delisted"])

    def test_pending_horizon(self):
        stock = PriceSeries({date(2025, 1, 6): 100}, "fixture", True)
        spy = PriceSeries({date(2025, 1, 6): 100}, "fixture", True)
        result = score_call(record(), stock, spy, datetime(2025, 2, 1, tzinfo=timezone.utc))
        self.assertEqual(result["horizons"]["6m"]["verdict"], "pending")


if __name__ == "__main__":
    unittest.main()
