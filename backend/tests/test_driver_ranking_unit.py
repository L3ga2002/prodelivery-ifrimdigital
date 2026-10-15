"""Deterministic ranking tests; no services or third-party packages required."""

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend.utils import driver_ranking as ranking


TZ = ZoneInfo("Europe/Bucharest")
FIXED_NOW = datetime(2026, 1, 12, 9, tzinfo=TZ)


class FixedDatetime(datetime):
    current = FIXED_NOW

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


class FixedClockTests(unittest.TestCase):
    def setUp(self):
        FixedDatetime.current = FIXED_NOW
        clock = patch.object(ranking, "datetime", FixedDatetime)
        clock.start()
        self.addCleanup(clock.stop)


class ScoreTests(FixedClockTests):
    def driver(self, **changes):
        data = {
            "total_deliveries": 150,
            "punctuality_rate": 1,
            "joined_at": (FIXED_NOW - timedelta(days=720)).isoformat(),
        }
        data.update(changes)
        return data

    def test_maximum_score_and_result_contract(self):
        self.assertEqual(ranking.calculate_driver_score(self.driver(), 0), {
            "score": 100.0,
            "breakdown": {"deliveries": 45.0, "cancellations": 25.0,
                          "punctuality": 15.0, "seniority": 15.0},
            "metrics": {"total_deliveries": 150, "cancelled_by_driver": 0,
                        "cancellation_rate": 0.0, "punctuality_rate": 1.0,
                        "seniority_months": 24.0},
        })

    def test_missing_data_uses_defaults(self):
        result = ranking.calculate_driver_score({}, 0)
        self.assertEqual(result["score"], 38.4)
        self.assertEqual(result["breakdown"], {
            "deliveries": 0.0, "cancellations": 25.0,
            "punctuality": 12.8, "seniority": 0.6,
        })
        self.assertEqual(result["metrics"]["seniority_months"], 1.0)

    def test_null_numeric_fields_use_defaults(self):
        result = ranking.calculate_driver_score({
            "total_deliveries": None, "punctuality_rate": None, "joined_at": None,
        }, 0)
        self.assertEqual(result, ranking.calculate_driver_score({}, 0))

    def test_zero_punctuality_earns_no_points(self):
        result = ranking.calculate_driver_score(self.driver(punctuality_rate=0), 0)
        self.assertEqual(result["breakdown"]["punctuality"], 0.0)
        self.assertEqual(result["metrics"]["punctuality_rate"], 0.0)
        self.assertEqual(result["score"], 85.0)

    def test_numeric_strings_are_supported(self):
        result = ranking.calculate_driver_score(self.driver(
            total_deliveries="75", punctuality_rate="0.5"), 0)
        self.assertEqual(result["score"], 70.0)

    def test_component_caps(self):
        result = ranking.calculate_driver_score(self.driver(
            total_deliveries=300, punctuality_rate=2,
            joined_at=(FIXED_NOW - timedelta(days=1500)).isoformat()), 0)
        self.assertEqual(result["score"], 100.0)
        result = ranking.calculate_driver_score(self.driver(punctuality_rate=-1), 0)
        self.assertEqual(result["breakdown"]["punctuality"], 0.0)

    def test_future_join_date_has_zero_seniority(self):
        result = ranking.calculate_driver_score(self.driver(
            joined_at=(FIXED_NOW + timedelta(days=30)).isoformat()), 0)
        self.assertEqual(result["metrics"]["seniority_months"], 0.0)
        self.assertEqual(result["breakdown"]["seniority"], 0.0)

    def test_invalid_and_empty_join_dates_use_fixed_fallback(self):
        for value in (None, "", "invalid", "2026-02-30"):
            with self.subTest(value=value):
                result = ranking.calculate_driver_score(self.driver(joined_at=value), 0)
                self.assertEqual(result["metrics"]["seniority_months"], 1.0)

    def test_naive_and_utc_join_dates_represent_same_instant(self):
        results = [ranking.calculate_driver_score(self.driver(joined_at=value), 0)
                   for value in ("2025-01-12T09:00:00", "2025-01-12T07:00:00Z",
                                 "2025-01-12T07:00:00+00:00")]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_cancellation_penalty_below_at_and_above_cap(self):
        for deliveries, cancellations, rate, points in (
            (90, 10, 0.1, 16.7), (70, 30, 0.3, 0.0), (60, 40, 0.4, 0.0),
        ):
            with self.subTest(rate=rate):
                result = ranking.calculate_driver_score(
                    self.driver(total_deliveries=deliveries), cancellations)
                self.assertEqual(result["metrics"]["cancellation_rate"], rate)
                self.assertEqual(result["breakdown"]["cancellations"], points)

    def test_cancellations_without_deliveries_and_empty_denominator(self):
        for cancellations, rate, points in ((0, 0.0, 25.0), (3, 1.0, 0.0)):
            with self.subTest(cancellations=cancellations):
                result = ranking.calculate_driver_score({}, cancellations)
                self.assertEqual(result["metrics"]["cancellation_rate"], rate)
                self.assertEqual(result["breakdown"]["cancellations"], points)

    def test_invalid_numeric_data_raises_value_error(self):
        for field in ("total_deliveries", "punctuality_rate"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    ranking.calculate_driver_score(self.driver(**{field: "invalid"}), 0)


class TierTests(unittest.TestCase):
    def test_tier_thresholds_including_equality(self):
        cases = ((-1, "start"), (0, "start"), (0.1, "start"),
                 (39.9, "start"), (40, "bronze"), (40.1, "bronze"),
                 (59.9, "bronze"), (60, "silver"), (60.1, "silver"),
                 (79.9, "silver"), (80, "gold"), (80.1, "gold"), (100, "gold"))
        for score, key in cases:
            with self.subTest(score=score):
                self.assertEqual(ranking.get_tier_for_score(score)["key"], key)

    def test_next_tier_thresholds_including_equality(self):
        cases = ((-1, "start"), (0, "bronze"), (0.1, "bronze"),
                 (39.9, "bronze"), (40, "silver"), (40.1, "silver"),
                 (59.9, "silver"), (60, "gold"), (60.1, "gold"),
                 (79.9, "gold"), (80, None), (80.1, None), (100, None))
        for score, key in cases:
            with self.subTest(score=score):
                tier = ranking.get_next_tier_for_score(score)
                self.assertEqual(tier["key"] if tier else None, key)


class AccessTests(FixedClockTests):
    def test_cycle_before_at_and_after_close(self):
        for instant, monday in (
            ("2026-01-12T09:59:59", "2026-01-12"),
            ("2026-01-12T10:00:00", "2026-01-19"),
            ("2026-01-12T10:00:01", "2026-01-19"),
        ):
            with self.subTest(instant=instant):
                now = datetime.fromisoformat(instant).replace(tzinfo=TZ)
                sunday, start, close = ranking._build_cycle_window(now)
                self.assertEqual(start, datetime.fromisoformat(monday).replace(tzinfo=TZ))
                self.assertEqual(sunday, start - timedelta(days=1))
                self.assertEqual(close, start.replace(hour=ranking.CLOSE_HOUR))

    def test_cycle_sunday_open_and_midweek(self):
        for instant in ("2026-01-11T21:59:59", "2026-01-11T22:00:00",
                        "2026-01-11T22:00:01", "2026-01-07T12:00:00"):
            with self.subTest(instant=instant):
                now = datetime.fromisoformat(instant).replace(tzinfo=TZ)
                self.assertEqual(ranking._build_cycle_window(now)[1],
                                 datetime(2026, 1, 12, tzinfo=TZ))

    def test_each_tier_opens_at_inclusive_boundary(self):
        openings = {"gold": datetime(2026, 1, 11, 22, tzinfo=TZ),
                    "silver": datetime(2026, 1, 12, 2, tzinfo=TZ),
                    "bronze": datetime(2026, 1, 12, 6, tzinfo=TZ),
                    "start": datetime(2026, 1, 12, 8, tzinfo=TZ)}
        for key, opening in openings.items():
            for offset, allowed in ((-1, False), (0, True), (1, True)):
                with self.subTest(key=key, offset=offset):
                    FixedDatetime.current = opening + timedelta(seconds=offset)
                    state = ranking.build_tier_access_state(key)
                    self.assertEqual(state["can_select_schedule"], allowed)
                    self.assertEqual(state["opens_at"], opening.isoformat())
                    self.assertEqual(state["next_open_at"], opening.isoformat())

    def test_access_closes_exclusively_and_moves_to_next_cycle(self):
        close = datetime(2026, 1, 12, ranking.CLOSE_HOUR, tzinfo=TZ)
        for key in ("gold", "silver", "bronze", "start"):
            for offset, allowed in ((-1, True), (0, False), (1, False)):
                with self.subTest(key=key, offset=offset):
                    FixedDatetime.current = close + timedelta(seconds=offset)
                    state = ranking.build_tier_access_state(key)
                    self.assertEqual(state["can_select_schedule"], allowed)
                    expected_close = close if allowed else close + timedelta(days=7)
                    self.assertEqual(state["closes_at"], expected_close.isoformat())

    def test_unknown_tier_falls_back_to_start_and_labels_match(self):
        state = ranking.build_tier_access_state("unknown")
        self.assertEqual(state, ranking.build_tier_access_state("start"))
        self.assertEqual(state["tier_label"], "Start")
        self.assertEqual(state["current_local_time"], FIXED_NOW.isoformat())
        for field in ("opens_at", "closes_at", "next_open_at"):
            self.assertEqual(state[field + "_label"],
                             datetime.fromisoformat(state[field]).strftime("%a %H:%M"))

    def test_dst_transition_cycles_use_local_wall_time(self):
        # Bucharest changes at 03:00 in spring and repeats 03:00 in autumn.
        for month, day, old_hours, new_hours in ((3, 29, 2, 3), (10, 25, 3, 2)):
            for hour, fold, offset in ((2, 0, old_hours), (3, 1, new_hours),
                                       (4, 0, new_hours), (22, 0, new_hours)):
                with self.subTest(month=month, hour=hour, fold=fold):
                    now = datetime(2026, month, day, hour, tzinfo=TZ, fold=fold)
                    self.assertEqual(now.utcoffset(), timedelta(hours=offset))
                    sunday, monday, close = ranking._build_cycle_window(now)
                    self.assertEqual(sunday.utcoffset(), timedelta(hours=old_hours))
                    self.assertEqual(monday.utcoffset(), timedelta(hours=new_hours))
                    self.assertEqual(close.hour, ranking.CLOSE_HOUR)
                    self.assertEqual(close.utcoffset(), timedelta(hours=new_hours))
                    FixedDatetime.current = now
                    state = ranking.build_tier_access_state("gold")
                    self.assertEqual(state["opens_at"],
                                     sunday.replace(hour=22).isoformat())
                    self.assertEqual(state["can_select_schedule"], hour == 22)

    def test_both_folds_of_autumn_hour_keep_same_cycle(self):
        windows = []
        for fold, offset in ((0, 3), (1, 2)):
            now = datetime(2026, 10, 25, 3, 30, tzinfo=TZ, fold=fold)
            self.assertEqual(now.utcoffset(), timedelta(hours=offset))
            windows.append(ranking._build_cycle_window(now))
        self.assertEqual(windows[0], windows[1])


class MemoryOrders:
    """Local count_documents adapter, filtering real fixture rows by the query."""
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    async def count_documents(self, query):
        self.queries.append(query)
        return sum(all(row.get(key) == value for key, value in query.items())
                   for row in self.rows)


class MemoryDatabase:
    def __init__(self, rows=()):
        self.orders = MemoryOrders(rows)


class PayloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FixedDatetime.current = FIXED_NOW
        clock = patch.object(ranking, "datetime", FixedDatetime)
        clock.start()
        self.addCleanup(clock.stop)
        self.driver = {"id": "d1", "total_deliveries": 150,
                       "punctuality_rate": 1,
                       "joined_at": (FIXED_NOW - timedelta(days=720)).isoformat()}

    async def test_payload_filters_only_this_drivers_cancellations(self):
        db = MemoryDatabase([
            {"driver_id": "d1", "status": "CANCELLED", "cancelled_by": "driver"},
            {"driver_id": "d2", "status": "CANCELLED", "cancelled_by": "driver"},
            {"driver_id": "d1", "status": "CANCELLED", "cancelled_by": "client"},
            {"driver_id": "d1", "status": "DELIVERED", "cancelled_by": "driver"},
        ])
        result = await ranking.build_driver_ranking_payload(db, self.driver)
        self.assertEqual(db.orders.queries, [{"driver_id": "d1", "status": "CANCELLED",
                                             "cancelled_by": "driver"}])
        expected = ranking.calculate_driver_score(self.driver, 1)
        self.assertEqual(result["ranking_score"], expected["score"])
        self.assertEqual(result["ranking_base_score"], expected["score"])
        self.assertEqual(result["ranking_metrics"]["cancelled_by_driver"], 1)
        self.assertFalse(result["ranking_metrics"]["has_manual_override"])
        self.assertEqual(result["ranking_breakdown"], {**expected["breakdown"], "manual": 0.0})
        self.assertEqual(result["ranking_tier_key"], "gold")
        self.assertIsNone(result["next_tier"])
        self.assertEqual(result["points_to_next_tier"], 0.0)
        self.assertEqual(result["schedule_access"], ranking.build_tier_access_state("gold"))

    async def test_manual_score_clamping_rounding_and_zero(self):
        for value, score, tier, next_key, points in (
            (-10, 0.0, "start", "bronze", 40.0),
            (0, 0.0, "start", "bronze", 40.0),
            ("59.96", 60.0, "silver", "gold", 20.0),
            (150, 100.0, "gold", None, 0.0),
        ):
            with self.subTest(value=value):
                driver = {**self.driver, "manual_ranking_score": value,
                          "manual_rank_note": "review", "manual_rank_updated_at": "2026-01-01"}
                result = await ranking.build_driver_ranking_payload(MemoryDatabase(), driver)
                self.assertEqual(result["ranking_score"], score)
                self.assertEqual(result["manual_ranking_score"], score)
                self.assertEqual(result["ranking_base_score"], 100.0)
                self.assertEqual(result["ranking_breakdown"]["manual"], score - 100.0)
                self.assertTrue(result["ranking_metrics"]["has_manual_override"])
                self.assertEqual(result["ranking_tier_key"], tier)
                self.assertEqual(result["ranking_tier"], ranking.get_tier_for_score(score)["label"])
                self.assertEqual(result["next_tier"]["key"] if result["next_tier"] else None, next_key)
                self.assertEqual(result["points_to_next_tier"], points)
                self.assertEqual(result["manual_rank_note"], "review")
                self.assertEqual(result["manual_rank_updated_at"], "2026-01-01")
                self.assertEqual(result["schedule_access"]["tier_key"], tier)

    async def test_invalid_or_absent_manual_score_uses_base(self):
        for value in (None, "", "invalid", {}):
            with self.subTest(value=value):
                result = await ranking.build_driver_ranking_payload(
                    MemoryDatabase(), {**self.driver, "manual_ranking_score": value})
                self.assertEqual(result["ranking_score"], 100.0)
                self.assertIsNone(result["manual_ranking_score"])
                self.assertFalse(result["ranking_metrics"]["has_manual_override"])
                self.assertIsNone(result["manual_rank_note"])
                self.assertIsNone(result["manual_rank_updated_at"])

    async def test_payload_missing_statistics(self):
        result = await ranking.build_driver_ranking_payload(MemoryDatabase(), {"id": "d1"})
        self.assertEqual(result["ranking_score"], 38.4)
        self.assertEqual(result["ranking_tier_key"], "start")
        self.assertEqual(result["next_tier"]["key"], "bronze")
        self.assertEqual(result["points_to_next_tier"], 1.6)

    async def test_missing_driver_id_raises_before_database_call(self):
        db = MemoryDatabase()
        with self.assertRaises(KeyError):
            await ranking.build_driver_ranking_payload(db, {})
        self.assertEqual(db.orders.queries, [])

    async def test_database_error_propagates(self):
        class FailingOrders:
            async def count_documents(self, query):
                raise RuntimeError("count failed")

        db = MemoryDatabase()
        db.orders = FailingOrders()
        with self.assertRaisesRegex(RuntimeError, "count failed"):
            await ranking.build_driver_ranking_payload(db, self.driver)


if __name__ == "__main__":
    unittest.main()
