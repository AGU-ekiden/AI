"""2026-10-18 の利用者決定（高2の8/31締切・箱根の成果定義）に関するテスト。"""
import unittest
from datetime import date as D

from labo.outcomes import (
    NEGATIVE_CONFIRMED, POSITIVE, TRACKING, UNKNOWN, HakoneLegResult, OutcomeDefinition, label_person,
)
from labo.periods import CUTOFF_PRESETS, DEFAULT_CUTOFF
from labo.model import IDENTITY_UNCONFIRMED

from .helpers import ds_of, res, values

JUL = CUTOFF_PRESETS["g2_jul31"]
AUG = CUTOFF_PRESETS["g2_aug31"]
OD = OutcomeDefinition()


class August31Cutoff(unittest.TestCase):
    def test_default_and_dates(self):
        self.assertEqual(DEFAULT_CUTOFF, "g2_aug31")
        self.assertEqual(AUG.resolve(2020), D(2021, 8, 31))

    def test_interhigh_included_when_day_confirmed(self):
        ih = dict(start=D(2021, 7, 28), end=D(2021, 8, 1))
        rows = [res("A", D(2020, 9, 1), 950), res("A", None, 900, performed=D(2021, 7, 30), **ih),
                res("A", D(2021, 9, 1), 880)]
        v = values(ds_of(rows), rule=AUG)
        self.assertEqual(v["best_5000_s"].value, 900)
        self.assertEqual(v["grade2_best_5000_s"].period_end, "2021-08-31")
        self.assertIn("期間の長さが異なる", v["grade1_to_grade2_improvement_s"].note)
        # 実施日未確認なら、締切前の大会でも初日を実施日と見なさず保留
        from labo.periods import hs_window
        from labo.quality import select_runs
        ds = ds_of([res("A", None, 900, **ih)])
        dec = select_runs(ds, "A", "5000m", D(2021, 8, 31), hs_window(2020, D(2021, 8, 31)))[1][0]
        self.assertEqual((dec.decision, dec.reason), ("held", "performed_date_unknown"))

    def test_window_edges_at_august31(self):
        rows = [res("A", D(2020, 9, 1), 880), res("A", D(2020, 8, 31), 870), res("A", D(2021, 8, 31), 900)]
        v = values(ds_of(rows), rule=AUG)
        self.assertEqual(v["best_5000_365d_s"].value, 880)   # 2020-09-01〜2021-08-31
        self.assertEqual(v["days_since_last_5000"].value, 0)


class July31CutoffOption(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(JUL.resolve(2020), D(2021, 7, 31))

    def test_interhigh_spanning_cutoff_is_held(self):
        rows = [res("A", D(2020, 9, 1), 950), res("A", D(2021, 5, 1), 930),
                res("A", None, 900, start=D(2021, 7, 28), end=D(2021, 8, 1)),
                res("A", D(2021, 8, 1), 890)]
        v = values(ds_of(rows), rule=JUL)
        self.assertEqual(v["best_5000_s"].value, 930)
        self.assertEqual(v["grade2_best_5000_s"].period_end, "2021-07-31")
        self.assertIn("期間の長さが異なる", v["grade1_to_grade2_improvement_s"].note)
        rows[2] = res("A", None, 900, start=D(2021, 7, 28), end=D(2021, 8, 1), performed=D(2021, 7, 30))
        self.assertEqual(values(ds_of(rows), rule=JUL)["best_5000_s"].value, 900)

    def test_window_edges_at_july31(self):
        rows = [res("A", D(2020, 8, 1), 880), res("A", D(2020, 7, 31), 870), res("A", D(2021, 7, 31), 900)]
        v = values(ds_of(rows), rule=JUL)
        self.assertEqual(v["best_5000_365d_s"].value, 880)   # 2020-08-01〜2021-07-31
        self.assertEqual(v["days_since_last_5000"].value, 0)


def leg(pid, fy, leg_no, rank, **kw):
    return HakoneLegResult(pid, fy, D(fy + 1, 1, 2 if leg_no <= 5 else 3), leg_no, rank,
                           source_ref=f"{pid}-{fy}-{leg_no}", **kw)


class HakoneOutcome(unittest.TestCase):
    # 高校入学2018年度 → 対象大会は2021〜2024年度（2022〜2025年1月）
    def lab(self, legs, entry=2018, as_of=D(2026, 10, 18), complete=frozenset(range(2015, 2026)),
            linked=True):
        return label_person("A", entry, legs, definition=OD, as_of=as_of,
                            complete_editions=set(complete), linkage_checked=linked)

    def test_editions(self):
        self.assertEqual(OD.edition_fys(2018), [2021, 2022, 2023, 2024])

    def test_thresholds(self):
        self.assertEqual(self.lab([leg("A", 2022, 3, 5)]).label, POSITIVE)
        self.assertEqual(self.lab([leg("A", 2022, 3, 6)]).label, NEGATIVE_CONFIRMED)
        r = self.lab([leg("A", 2023, 8, 2)])
        self.assertEqual((r.label, r.outbound_top, r.return_top), (POSITIVE, False, True))
        self.assertEqual(self.lab([leg("A", 2023, 8, 3)]).label, NEGATIVE_CONFIRMED)

    def test_student_alliance_counted_by_equivalent_rank(self):
        self.assertEqual(OD.ref, "hakone_leg_top@2")
        r = self.lab([leg("A", 2022, 1, None, reference_only=True, reference_rank=4)])
        self.assertEqual((r.label, r.outbound_top), (POSITIVE, True))
        r = self.lab([leg("A", 2022, 7, None, reference_only=True, reference_rank=3)])
        self.assertEqual((r.label, r.reason), (NEGATIVE_CONFIRMED, "参考記録のみあり"))
        # 相当順位が未確認なら未達成と確定しない
        self.assertEqual(self.lab([leg("A", 2022, 1, None, reference_only=True)]).label, UNKNOWN)
        # v1（参考記録を含めない）も再現できる
        v1 = OutcomeDefinition(version=1, include_reference=False)
        r1 = label_person("A", 2018, [leg("A", 2022, 1, None, reference_only=True, reference_rank=4)],
                          definition=v1, as_of=D(2026, 10, 18),
                          complete_editions=set(range(2015, 2026)), linkage_checked=True)
        self.assertEqual(r1.label, NEGATIVE_CONFIRMED)

    def test_unconfirmed_identity_not_counted(self):
        self.assertEqual(self.lab([leg("A", 2022, 1, 1, identity=IDENTITY_UNCONFIRMED)]).label, UNKNOWN)

    def test_outside_window_ignored(self):
        self.assertEqual(self.lab([leg("A", 2025, 1, 1)]).label, NEGATIVE_CONFIRMED)

    def test_untracked_generation_is_not_zero(self):
        r = self.lab([], entry=2022)  # 対象 2025〜2028年度
        self.assertEqual(r.label, TRACKING)
        self.assertEqual(self.lab([], linked=False).label, UNKNOWN)
        self.assertEqual(self.lab([], complete={2021, 2022, 2023}).label, UNKNOWN)
        self.assertEqual(self.lab([], entry=None).label, UNKNOWN)

    def test_future_race_not_visible_before_it_happens(self):
        r = self.lab([leg("A", 2024, 2, 1)], as_of=D(2024, 12, 31))
        self.assertEqual(r.label, TRACKING)


if __name__ == "__main__":
    unittest.main()


class RkmMapping(unittest.TestCase):
    def test_status_map(self):
        from labo.adapters.rkm_mapping import map_status
        from labo.model import STATUS_DSQ, STATUS_NO_MARK, STATUS_OK, STATUS_UNCONFIRMED
        for raw in ("NM", "NI", "DNE"):
            self.assertEqual(map_status(raw), STATUS_NO_MARK)
        self.assertEqual(map_status(None), STATUS_OK)
        self.assertEqual(map_status("DQ"), STATUS_DSQ)
        self.assertEqual(map_status("競走中止"), STATUS_UNCONFIRMED)  # 推測で DNF にしない

    def test_event_map_uses_name_not_distance(self):
        from labo.adapters.rkm_mapping import map_event
        self.assertEqual(map_event("5000m", "track"), "5000m")
        self.assertIsNone(map_event("5km", "road"))
        self.assertIsNone(map_event("5000mW", "walk"))
        self.assertEqual(map_event("3000mSC(91.4cm)", "track"), "3000mSC")
        self.assertIsNone(map_event("3000mSC(76.2cm)", "track"))
        self.assertIsNone(map_event("駅伝", "ekiden"))

    def test_no_mark_rows_are_excluded_not_zero(self):
        from labo.model import STATUS_NO_MARK
        v = values(ds_of([res("A", D(2021, 6, 1), None, status=STATUS_NO_MARK),
                          res("A", D(2021, 7, 1), 930)]))
        self.assertEqual(v["runs_5000_count"].value, 1)
        self.assertEqual(v["best_5000_s"].value, 930)
