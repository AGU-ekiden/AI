"""rkm 読み込み（build_dataset）のテスト。実DBと同じ形のタプルで確認する（氏名は架空）。"""
import unittest
from datetime import date as D

from labo.adapters.rkm_loader import build_dataset
from labo.catalog import builtin_definitions
from labo.features import compute_person
from labo.model import STATUS_NO_MARK
from labo.periods import CUTOFF_PRESETS

AUG = CUTOFF_PRESETS["g2_aug31"]


def rows():
    return {
        "athletes": [("P1", "架空A", '["2023","2024"]', '["2024"]'), ("P2", "架空B", None, None)],
        "profiles": [("P1", "pa", "primary"), ("P1", "pb", "additional"), ("P2", "pc", "primary")],
        "comp_range": [("C1", "2020-06-01", "2020-06-01", 1, "記録会"),
                       ("C2", "2021-06-05", "2021-06-06", 2, "県総体"),
                       ("IH", "2021-07-28", "2021-08-01", 5, "令和3年度全国高校総合体育大会"),
                       ("C9", "2021-08-30", "2021-09-01", 3, "またぎ大会"),
                       ("HK", "2024-01-02", "2024-01-03", 2, "第100回東京箱根間往復大学駅伝競走")],
        "grades": [("P1", "2020-06-01", "1", "架空高", None), ("P1", "2021-06-05", "2+", None, "高校"),
                   ("P1", "2023-05-01", "1", "架空大", "大学"), ("P2", "2021-06-05", "2", "架空中", None)],
        "results": [
            ("P1", "pa", "r1", "2020-06-01", "C1", "記録会", "5000m", "track", "ﾀｲﾑﾚｰｽ", "15.30.00", 930.0, "s", "electronic", None),
            ("P1", "pa", "r2", "2020-06-01", "C1", "記録会", "5000m", "track", "ﾀｲﾑﾚｰｽ総合結果", "15.30.00", 930.0, "s", "electronic", None),
            ("P1", "pb", "r3", "2020-06-01", "C1", "記録会", "5000m", "track", None, "15.30.00", 930.0, "s", "electronic", None),
            ("P1", "pa", "r4", "2021-06-05", "C2", "県総体", "5000m", "track", "予選", "15.00.00", 900.0, "s", "electronic", None),
            ("P1", "pa", "r5", "2021-06-06", "C2", "県総体", "5000m", "track", "決勝", "15.00.00", 900.0, "s", "electronic", None),
            ("P1", "pa", "r6", "2021-06-10", None, "記録会", "5000m", "track", None, None, None, None, None, "NM"),
            ("P1", "pa", "r7", "2021-07-30", "IH", "インターハイ", "5000m", "track", "決勝", "14.50.00", 890.0, "s", "electronic", None),
            ("P1", "pa", "r8", "2021-08-30", "C9", "またぎ大会", "5000m", "track", "決勝", "14.40.00", 880.0, "s", "electronic", None),
            ("P1", "pa", "r9", "2021-07-01", "C1", "記録会", "5km", "road", None, "14.00", 840.0, "s", "electronic", None),
            ("P1", "pa", "r10", "2021-07-02", "C1", "記録会", "3000mSC(91.4cm)", "track", None, "9.00.00", 540.0, "s", "electronic", None),
        ],
        "national_results": [("P1", "pa", "r7", "2021-07-30", "IH", "インターハイ", "5000m", "track", None)],
        "hakone": [("P1", "pa", "h1", "2024-01-02", 2023, 3, 4, "5", None),
                   ("P1", "pb", "h2", "2024-01-02", 2023, 3, 4, "5", None),     # 別プロフィールの同じ出走
                   ("P2", "pc", "h3", "2024-01-03", 2023, None, None, "OP", None)],  # 学生連合
        "hakone_self_legs": [("P2", "pc", "h3", 8, None)],
        "counts": [(10, 2)],
    }


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.ds, self.hk, self.rep = build_dataset(rows())

    def test_entry_year_from_high_school_grades_only(self):
        self.assertEqual(self.ds.athletes["P1"].hs_entry_fiscal_year, 2020)
        self.assertIsNone(self.ds.athletes["P2"].hs_entry_fiscal_year)  # 中学の所属しかない

    def test_events_and_statuses(self):
        codes = {r.key.record_id: r.event_code for r in self.ds.results}
        self.assertNotIn("r9", codes)            # 5km ロードは 5000m にしない（取り込まない）
        self.assertEqual(self.rep.excluded_rows.get("unmapped_event_or_person"), 1)
        self.assertEqual(codes["r10"], "3000mSC")
        r6 = next(r for r in self.ds.results if r.key.record_id == "r6")
        self.assertEqual(r6.status, STATUS_NO_MARK)

    def test_duplicates_and_features(self):
        dup = {(l.canonical.record_id, l.duplicate.record_id) for l in self.ds.duplicate_links}
        self.assertEqual(dup, {("r1", "r2"), ("r1", "r3")})  # 別表示・別プロフィールはまとめ、予選・決勝は別
        v = {x.feature_ref.split("@")[0]: x for x in
             compute_person(self.ds, self.ds.athletes["P1"], builtin_definitions(), AUG)}
        # 有効：r1(2020-06-01) r4 r5 r7(インターハイ)。r8 は大会初日と同じ日付で大会が8/31をまたぐため保留
        self.assertEqual(v["runs_5000_count"].value, 4)
        self.assertEqual(v["best_5000_s"].value, 890.0)
        self.assertEqual(v["grade1_best_5000_s"].value, 930.0)

    def test_first_day_fallback_spanning_cutoff_is_held(self):
        from labo.periods import hs_window
        from labo.quality import select_runs
        r8 = next(r for r in self.ds.results if r.key.record_id == "r8")
        self.assertTrue(r8.date_maybe_first_day)
        cutoff = AUG.resolve(2020)
        dec = [d for d in select_runs(self.ds, "P1", "5000m", cutoff, hs_window(2020, cutoff))[1]
               if d.key == r8.key][0]
        self.assertEqual((dec.decision, dec.reason), ("held", "date_spans_cutoff"))
        # インターハイ（7/28〜8/1）の 7/30 は初日ではないので採用
        r7 = next(r for r in self.ds.results if r.key.record_id == "r7" and r.event_code)
        self.assertFalse(r7.date_maybe_first_day)

    def test_national_cohort_and_hakone(self):
        self.assertIn("IH", self.ds.competitions_national)
        self.assertEqual(len([l for l in self.hk.legs if l.person_id == "P1"]), 1)  # 重複をまとめる
        p2 = next(l for l in self.hk.legs if l.person_id == "P2")
        self.assertTrue(p2.reference_only)
        self.assertIsNone(p2.official_rank)
        self.assertEqual(p2.leg, 8)  # ekiden_legs の本人区間で補完
        self.assertEqual(self.hk.run_years["P1"], [2024])
        self.assertIsNone(self.hk.run_years["P2"])


if __name__ == "__main__":
    unittest.main()
