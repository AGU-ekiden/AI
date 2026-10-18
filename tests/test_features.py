import unittest
from datetime import date, timedelta

from labo.cohorts import CohortDefinition, builtin_cohorts, evaluate, validate_criteria
from labo.definitions import SpecError, validate_spec
from labo.ekiden import leg_pace_s_per_km, self_leg
from labo.evaluation import LABEL_TRACKING, LABEL_UNKNOWN, label_status, split_by_generation, trainable
from labo.marks import parse_time_mark
from labo.model import (
    COVERAGE_UNKNOWN, STATUS_DNF, STATUS_DNS, STATUS_BLANK, STATUS_FETCH_FAILED, DuplicateLink,
    EkidenLeg, ResultKey,
)
from labo.periods import CUTOFF_PRESETS
from labo.quality import Options, select_runs
from labo.periods import hs_window

from .helpers import CUTOFF, ENTRY, G2, custom, ds_of, res, values

D = date


class LeakageAndDates(unittest.TestCase):
    def test_result_after_cutoff_does_not_change_values(self):
        base = [res("A", D(2020, 6, 1), 950), res("A", D(2021, 6, 1), 930),
                res("A", D(2021, 9, 1), 925), res("A", D(2022, 3, 31), 920)]
        before = values(ds_of(base))
        after = values(ds_of(base + [res("A", D(2022, 4, 1), 880)]))
        for k in before:
            self.assertEqual(before[k].value, after[k].value, k)
            self.assertEqual(before[k].evidence, after[k].evidence, k)

    def test_multiday_competition_spanning_cutoff_is_held(self):
        r = res("A", None, 900, start=D(2022, 3, 30), end=D(2022, 4, 1))
        ds = ds_of([r, res("A", D(2021, 6, 1), 930)])
        _, decisions = select_runs(ds, "A", "5000m", CUTOFF, hs_window(ENTRY, CUTOFF))
        dec = next(x for x in decisions if x.key == r.key)
        self.assertEqual((dec.decision, dec.reason), ("held", "date_spans_cutoff"))
        self.assertEqual(values(ds)["best_5000_s"].value, 930)

    def test_multiday_first_day_is_not_assumed(self):
        r = res("A", None, 900, start=D(2021, 6, 1), end=D(2021, 6, 3))
        ds = ds_of([r])
        self.assertIsNone(values(ds)["best_5000_s"].value)
        known = res("A", None, 900, start=D(2021, 6, 1), end=D(2021, 6, 3), performed=D(2021, 6, 3))
        v = values(ds_of([known]))
        self.assertEqual(v["best_5000_s"].value, 900)
        self.assertEqual(v["days_since_last_5000"].value, (CUTOFF - D(2021, 6, 3)).days)

    def test_grade_boundary_april_first(self):
        v = values(ds_of([res("A", D(2021, 3, 31), 950), res("A", D(2021, 4, 1), 940)]))
        self.assertEqual(v["grade1_best_5000_s"].value, 950)
        self.assertEqual(v["grade2_best_5000_s"].value, 940)

    def test_unknown_entry_year_is_not_imputed(self):
        v = values(ds_of([res("A", D(2021, 6, 1), 930)], entry=None))
        self.assertIsNone(v["best_5000_s"].value)
        self.assertEqual(v["best_5000_s"].reason, "hs_entry_year_unknown")
        self.assertEqual(v["grade1_to_grade2_improvement_s"].reason, "input_null")

    def test_publication_strict_mode(self):
        ds = ds_of([res("A", D(2021, 6, 1), 930),
                    res("A", D(2021, 7, 1), 920, first_available_at=D(2021, 7, 2))])
        v = values(ds, options=Options(require_published_by_cutoff=True))
        self.assertEqual(v["best_5000_s"].value, 920)
        self.assertEqual(v["best_5000_s"].evidence_count, 1)

    def test_summer_cutoff_notes_unequal_periods(self):
        ds = ds_of([res("A", D(2020, 6, 1), 950), res("A", D(2021, 6, 1), 930),
                    res("A", D(2021, 9, 1), 900)])
        v = values(ds, rule=CUTOFF_PRESETS["g2_aug31"])
        self.assertEqual(v["grade2_best_5000_s"].value, 930)
        self.assertIn("期間の長さが異なる", v["grade1_to_grade2_improvement_s"].note)


class EventsAndRecords(unittest.TestCase):
    def test_steeplechase_not_in_3000_best(self):
        d = custom("best_3000_s", {"op": "min", "event": "3000m", "window": {"kind": "hs"}})
        ds = ds_of([res("A", D(2021, 6, 1), 500, event="3000mSC"),
                    res("A", D(2021, 7, 1), 520, event="3000m")])
        self.assertEqual(values(ds, defs=[d])["best_3000_s"].value, 520)

    def test_ekiden_team_total_not_in_individual_best(self):
        ds = ds_of([res("A", D(2021, 12, 20), 800, group="ekiden"),
                    res("A", D(2021, 6, 1), 900, group="relay"),
                    res("A", D(2021, 7, 1), 910)])
        v = values(ds)
        self.assertEqual(v["best_5000_s"].value, 910)
        self.assertEqual(v["runs_5000_count"].value, 1)

    def test_ekiden_self_leg_vs_pass_time(self):
        k = ResultKey("A", "P1", "E1")
        legs = [EkidenLeg(k, 1, False, 1800, 1800, 10000), EkidenLeg(k, 3, True, 900, 3600, None)]
        leg, why = self_leg(legs, k)
        self.assertEqual((leg.leg_value, why), (900, "ok"))
        self.assertEqual(leg_pace_s_per_km(leg), (None, "leg_distance_unknown"))
        two = legs + [EkidenLeg(k, 5, True, 950, 5000, 3000)]
        self.assertEqual(self_leg(two, k), (None, "ambiguous_multiple_self_legs"))

    def test_same_record_id_different_people_kept(self):
        ds = ds_of([res("A", D(2021, 6, 1), 930, rid="SAME"), res("B", D(2021, 6, 1), 940, rid="SAME")])
        self.assertEqual(values(ds, "A")["best_5000_s"].value, 930)
        self.assertEqual(values(ds, "B")["best_5000_s"].value, 940)

    def test_duplicate_listing_does_not_inflate(self):
        rows = [res("A", D(2021, 5, 1), 930), res("A", D(2021, 6, 1), 920, rid="X"),
                res("A", D(2021, 6, 1), 920, rid="X", profile="P2"), res("A", D(2021, 7, 1), 910)]
        link = DuplicateLink(ResultKey("A", "P1", "X"), ResultKey("A", "P2", "X"), "同一大会・同記録", "t")
        v = values(ds_of(rows, links=[link]))
        self.assertEqual(v["runs_5000_count"].value, 3)
        self.assertEqual(v["latest3_5000_median_s"].value, 920)
        # 統合根拠がない疑いは保留：件数・中央値は null、最小値は影響しない
        rows2 = rows[:2] + [res("A", D(2021, 6, 1), 920, dup=True), rows[3]]
        v2 = values(ds_of(rows2))
        self.assertIsNone(v2["runs_5000_count"].value)
        self.assertEqual(v2["runs_5000_count"].reason, "pending_duplicate_review")
        self.assertIsNone(v2["latest3_5000_median_s"].value)
        self.assertEqual(v2["best_5000_s"].value, 910)

    def test_dns_dnf_blank_failed_zero_are_distinct(self):
        rows = [res("A", D(2021, 6, 1), None, status=STATUS_DNS),
                res("A", D(2021, 6, 2), None, status=STATUS_DNF),
                res("A", D(2021, 6, 3), None, status=STATUS_BLANK),
                res("A", D(2021, 6, 4), None, status=STATUS_FETCH_FAILED),
                res("A", D(2021, 6, 5), 0.0)]
        ds = ds_of(rows)
        _, decisions = select_runs(ds, "A", "5000m", CUTOFF, hs_window(ENTRY, CUTOFF))
        self.assertEqual([d.reason for d in decisions],
                         ["DNS", "DNF", "blank", "fetch_failed", "nonpositive_time"])
        self.assertEqual(values(ds)["runs_5000_count"].value, 0)  # 取得済みで該当なし=0
        self.assertIsNone(values(ds_of(rows, coverage=COVERAGE_UNKNOWN))["runs_5000_count"].value)
        self.assertEqual(parse_time_mark("0:00.00")[2], "nonpositive_time")
        self.assertEqual(parse_time_mark("")[2], "blank")
        self.assertEqual(parse_time_mark("DNF")[2], "DNF")

    def test_raw_only_not_excluded_but_unverified_rows_not_adopted(self):
        ds = ds_of([res("A", D(2021, 6, 1), 930, vstatus="raw_only"),
                    res("A", D(2021, 7, 1), 900, row_checked=False)])
        v = values(ds)
        self.assertEqual(v["best_5000_s"].value, 930)
        _, decisions = select_runs(ds, "A", "5000m", CUTOFF, hs_window(ENTRY, CUTOFF))
        self.assertEqual(sorted(d.reason for d in decisions), ["ok", "row_unverified"])

    def test_implausible_value_held(self):
        v = values(ds_of([res("A", D(2021, 6, 1), 9.0), res("A", D(2021, 7, 1), 930)]))
        self.assertEqual(v["best_5000_s"].value, 930)

    def test_mark_parsing(self):
        self.assertEqual(parse_time_mark("14:32.15")[:2], (872.15, 2))
        self.assertEqual(parse_time_mark("14'32\"1")[:2], (872.1, 1))
        self.assertEqual(parse_time_mark("1:04:32")[:2], (3872.0, 0))
        self.assertEqual(parse_time_mark("14:72.00")[2], "format_unknown")


class HandCalculations(unittest.TestCase):
    def test_five_percent_improvement(self):
        v = values(ds_of([res("A", D(2020, 6, 1), 1000), res("A", D(2021, 6, 1), 950)]))
        self.assertEqual(v["grade1_to_grade2_improvement_s"].value, 50)
        self.assertEqual(v["grade1_to_grade2_improvement_pct"].value, 5.0)

    def test_latest_n_medians(self):
        times = [930, 920, 910, 905, 915, 900]
        rows = [res("A", D(2021, 5, 1) + timedelta(days=20 * i), t) for i, t in enumerate(times)]
        v = values(ds_of(rows))
        self.assertEqual(v["latest3_5000_median_s"].value, 905)
        self.assertEqual(v["latest5_5000_median_s"].value, 910)
        v4 = values(ds_of(rows[:4]))
        self.assertIsNone(v4["latest5_5000_median_s"].value)

    def test_ambiguous_same_day_boundary(self):
        rows = [res("A", D(2021, 5, 1), 930), res("A", D(2021, 6, 1), 920),
                res("A", D(2021, 6, 1), 910), res("A", D(2021, 7, 1), 905),
                res("A", D(2021, 8, 1), 900)]
        v = values(ds_of(rows))
        self.assertIsNone(v["latest3_5000_median_s"].value)
        self.assertEqual(v["latest3_5000_median_s"].reason, "ambiguous_order")
        rows[1] = res("A", D(2021, 6, 1), 920, round_order=1)
        rows[2] = res("A", D(2021, 6, 1), 910, round_order=2)
        self.assertEqual(values(ds_of(rows))["latest3_5000_median_s"].value, 905)

    def test_iqr(self):
        rows = [res("A", D(2021, 5, 1), 900, comp="C1"), res("A", D(2021, 6, 1), 910, comp="C2"),
                res("A", D(2021, 7, 1), 920, comp="C3"), res("A", D(2021, 8, 1), 940, comp="C3b")]
        self.assertEqual(values(ds_of(rows))["iqr_5000_365d_s"].value, 17.5)
        self.assertEqual(values(ds_of(rows[:3]))["iqr_5000_365d_s"].reason, "insufficient_runs")
        same = [res("A", D(2021, 5, 1) + timedelta(days=i), t, comp="ONE")
                for i, t in enumerate([900, 910, 920, 940])]
        self.assertEqual(values(ds_of(same))["iqr_5000_365d_s"].reason, "insufficient_competitions")

    def test_window_edges(self):
        self.assertEqual(CUTOFF - timedelta(days=364), D(2021, 4, 1))
        self.assertEqual(CUTOFF - timedelta(days=179), D(2021, 10, 3))
        rows = [res("A", D(2021, 3, 31), 870), res("A", D(2021, 4, 1), 880),
                res("A", D(2021, 10, 2), 890), res("A", D(2021, 10, 3), 900),
                res("A", D(2022, 3, 31), 910)]
        v = values(ds_of(rows))
        self.assertEqual(v["best_5000_s"].value, 870)
        self.assertEqual(v["best_5000_365d_s"].value, 880)
        self.assertEqual(v["best_5000_180d_s"].value, 900)
        self.assertEqual(v["days_since_last_5000"].value, 0)
        self.assertEqual(v["observed_5000_span_days"].value, 365)

    def test_pb_updates(self):
        rows = [res("A", D(2020, 6, 1), 900),   # 窓より前の基準
                res("A", D(2021, 5, 1), 905),   # 窓内だが基準を超えない
                res("A", D(2021, 6, 1), 895),   # 更新
                res("A", D(2021, 7, 1), 890), res("A", D(2021, 7, 1), 885),  # 同日は1回
                res("A", D(2021, 8, 1), 885),   # 同タイムは更新でない
                res("A", D(2021, 9, 1), 880)]   # 更新
        self.assertEqual(values(ds_of(rows))["observed_5000_pb_updates_365d_count"].value, 3)
        only_before = values(ds_of([res("A", D(2020, 6, 1), 900), res("A", D(2020, 7, 1), 890)]))
        self.assertEqual(only_before["observed_5000_pb_updates_365d_count"].value, 0)
        self.assertIsNone(values(ds_of([]))["observed_5000_pb_updates_365d_count"].value)

    def test_gap_median(self):
        rows = [res("A", D(2021, 3, 1), 930),  # 窓外
                res("A", D(2021, 4, 10), 920, round_order=1), res("A", D(2021, 4, 10), 915, round_order=2),
                res("A", D(2021, 5, 10), 910), res("A", D(2021, 7, 9), 905), res("A", D(2021, 7, 19), 900)]
        self.assertEqual(values(ds_of(rows))["median_5000_race_gap_365d_days"].value, 30)
        two = values(ds_of(rows[:4]))
        self.assertEqual(two["median_5000_race_gap_365d_days"].reason, "insufficient_dates")


class SafetyAndScope(unittest.TestCase):
    def test_spec_rejects_code_and_sql(self):
        bad = [
            {"op": "min; DROP TABLE rkm.records", "event": "5000m", "window": {"kind": "hs"}},
            {"op": "min", "event": "5000m'; --", "window": {"kind": "hs"}},
            {"op": "min", "event": "5000m", "window": {"kind": "hs"}, "sql": "SELECT 1"},
            {"op": "min", "event": "5000m", "window": {"kind": "recent_days", "days": "365"}},
            {"op": "__import__('os').system('x')"},
            {"op": "diff", "inputs": ["a@1", "b@1"], "expr": "eval"},
            "min(5000m)",
        ]
        for spec in bad:
            with self.assertRaises(SpecError, msg=str(spec)):
                validate_spec(spec, set())

    def test_cohort_uses_only_info_available_at_cutoff(self):
        ds = ds_of([res("A", D(2022, 7, 30), 880, comp="NAT22"),
                    res("B", D(2021, 7, 30), 900, comp="NAT21")], national={"NAT21", "NAT22"})
        cohort = next(c for c in builtin_cohorts() if c.cohort_id == "national_by_cutoff")
        self.assertEqual(evaluate(cohort, ds, ds.athletes["A"], G2), (False, "no_national_by_cutoff"))
        self.assertEqual(evaluate(cohort, ds, ds.athletes["B"], G2), (True, ""))
        for future in ({"hakone_entry": True}, {"university": "X"}, {"national_any_time": True}):
            with self.assertRaises(ValueError):
                validate_criteria(future)
        self.assertIsInstance(cohort, CohortDefinition)

    def test_future_labels_not_zero_and_no_person_leak(self):
        self.assertEqual(label_status(False, D(2027, 1, 3), D(2026, 10, 18)), LABEL_TRACKING)
        self.assertEqual(label_status(False, D(2025, 1, 3), D(2026, 10, 18)), LABEL_UNKNOWN)
        self.assertIsNone(trainable(LABEL_TRACKING))
        self.assertIsNone(trainable(LABEL_UNKNOWN))
        tr, te = split_by_generation({"A": 2018, "B": 2021},
                                     2019, [("A", 1), ("A", 2), ("B", 3)])
        self.assertEqual(({p for p, _ in tr}, {p for p, _ in te}), ({"A"}, {"B"}))

    def test_adapter_queries_are_readonly(self):
        from labo.adapters.rkm_readonly import AUDIT_QUERIES, SAFETY_QUERIES, assert_readonly_sql
        for sql in list(AUDIT_QUERIES.values()) + list(SAFETY_QUERIES.values()):
            assert_readonly_sql(sql)
        for sql in ("DELETE FROM rkm.records", "SELECT 1; DROP TABLE rkm.records",
                    "WITH x AS (SELECT 1) UPDATE rkm.athletes SET name='x'", "TRUNCATE rkm.records",
                    "SELECT 'a'; DELETE FROM rkm.records", "SELECT 1 WHERE 'x'='x' OR 1=1; DROP TABLE t"):
            with self.assertRaises(ValueError):
                assert_readonly_sql(sql)


if __name__ == "__main__":
    unittest.main()
