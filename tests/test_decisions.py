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

    def test_student_alliance_excluded_v3(self):
        self.assertEqual(OD.ref, "hakone_leg_top@3")
        # 学生連合の区間は相当順位が良くても達成に数えない。それしかなければ「不明」
        r = self.lab([leg("A", 2022, 1, None, reference_only=True, reference_rank=1)])
        self.assertEqual(r.label, UNKNOWN)
        # 別の年に自チームで達成していれば達成
        r = self.lab([leg("A", 2022, 1, None, reference_only=True, reference_rank=1), leg("A", 2023, 2, 4)])
        self.assertEqual(r.label, POSITIVE)
        # 過去の版も再現できる：v2（相当順位で含める）
        v2 = OutcomeDefinition(version=2, include_reference=True)
        r2 = label_person("A", 2018, [leg("A", 2022, 1, None, reference_only=True, reference_rank=4)],
                          definition=v2, as_of=D(2026, 10, 18),
                          complete_editions=set(range(2015, 2026)), linkage_checked=True)
        self.assertEqual(r2.label, POSITIVE)

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


class RkmDecisions20261019(unittest.TestCase):
    def test_date_is_race_day(self):
        from labo.adapters.rkm_mapping import parse_date
        self.assertEqual(parse_date("2021-07-30"), D(2021, 7, 30))
        self.assertEqual(parse_date("2021/7/3"), D(2021, 7, 3))
        self.assertIsNone(parse_date("2021-02-30"))
        self.assertIsNone(parse_date("7月30日"))

    def test_grade_parsing(self):
        from labo.adapters.rkm_mapping import parse_grade
        for raw, g in (("2", 2), ("2+", 2), ("高2", 2), ("高校3年", 3), ("２", 2), ("1年生", 1)):
            self.assertEqual(parse_grade(raw), g, raw)
        for raw in ("4", "中3", "M1", "", None, "大2"):
            self.assertIsNone(parse_grade(raw), raw)

    def test_entry_year_from_grades(self):
        from labo.adapters.rkm_mapping import infer_hs_entry_fy
        rows = [(D(2020, 6, 1), "1", "洛北高"), (D(2021, 9, 1), "2+", "洛北高"), (D(2022, 2, 1), "2", "洛北高"),
                (D(2023, 6, 1), "1", "東西大")]  # 大学のレースは使わない
        self.assertEqual(infer_hs_entry_fy(rows), (2020, "derived_from_grade", 3))
        conflict = rows + [(D(2021, 6, 1), "3", "洛北高")]
        self.assertEqual(infer_hs_entry_fy(conflict)[:2], (None, "conflicting_grades"))
        self.assertEqual(infer_hs_entry_fy([(D(2020, 6, 1), "2", None)])[:2], (None, "no_high_school_grade"))
        # 多数決（利用者決定）：3件以上かつ8割以上
        five = [(D(2020, m, 1), "1", "洛北高") for m in (5, 6, 7, 8)] + [(D(2020, 9, 1), "2", "洛北高")]
        self.assertEqual(infer_hs_entry_fy(five), (2020, "majority_of_grades", 4))
        tie = [(D(2020, 6, 1), "1", "洛北高"), (D(2020, 7, 1), "1", "洛北高"),
               (D(2020, 8, 1), "2", "洛北高"), (D(2020, 9, 1), "2", "洛北高")]
        self.assertEqual(infer_hs_entry_fy(tie)[:2], (None, "conflicting_grades"))
        few = [(D(2020, 6, 1), "1", "洛北高"), (D(2020, 7, 1), "1", "洛北高"), (D(2020, 8, 1), "2", "洛北高")]
        self.assertEqual(infer_hs_entry_fy(few)[:2], (None, "conflicting_grades"))  # 2/3=67%

    def test_cross_profile_duplicates_merged(self):
        from labo.adapters.rkm_mapping import build_duplicate_links
        a = res("A", D(2021, 6, 1), 930, rid="X1", profile="P1")
        b = res("A", D(2021, 6, 1), 930, rid="Y9", profile="P2")      # 別プロフィールの同じレース
        c = res("A", D(2021, 6, 1), 930, rid="X2", profile="P1")      # 同プロフィール内は統合しない
        other = res("B", D(2021, 6, 1), 930, rid="X1", profile="P1")  # 別人は統合しない
        links = build_duplicate_links([a, b, c, other])
        self.assertEqual([(l.canonical, l.duplicate) for l in links], [(a.key, b.key)])
        v = values(ds_of([a, b, res("A", D(2021, 7, 1), 920), res("A", D(2021, 8, 1), 910)], links=links))
        self.assertEqual(v["runs_5000_count"].value, 3)

    def test_student_alliance_detection(self):
        from labo.adapters.rkm_mapping import is_student_alliance
        self.assertTrue(is_student_alliance("関東学生連合"))
        self.assertFalse(is_student_alliance("青山学院大"))
        self.assertFalse(is_student_alliance(None))


class RkmRound2Findings(unittest.TestCase):
    """第2回監査（2026-10-19）の所見に基づくルール。"""

    def test_first_day_fallback_held_only_when_meet_spans_cutoff(self):
        from dataclasses import replace
        from labo.periods import hs_window
        from labo.quality import select_runs
        aug = CUTOFF_PRESETS["g2_aug31"]
        cutoff = aug.resolve(2020)  # 2021-08-31
        base = res("A", D(2021, 8, 30), 900)
        spans = replace(base, competition_start=D(2021, 8, 30), competition_end=D(2021, 9, 1),
                        date_maybe_first_day=True)
        dec = select_runs(ds_of([spans]), "A", "5000m", cutoff, hs_window(2020, cutoff))[1][0]
        self.assertEqual((dec.decision, dec.reason), ("held", "date_spans_cutoff"))
        # 締切をまたがない大会なら、初日の可能性があっても日付をそのまま使う（利用者決定：date は実施日）
        inside = replace(spans, competition_end=D(2021, 8, 31))
        self.assertEqual(values(ds_of([inside]), rule=aug)["best_5000_s"].value, 900)

    def test_round_class(self):
        from labo.adapters.rkm_mapping import round_class, same_race_rounds
        self.assertEqual(round_class("ﾀｲﾑﾚｰ\nｽ総合結果\n"), "final")
        self.assertEqual(round_class("タイムレース決勝総合"), "final")
        self.assertEqual(round_class("予選"), "prelim")
        self.assertEqual(round_class("準決勝"), "semi")
        self.assertIsNone(round_class(""))
        self.assertTrue(same_race_rounds("ﾀｲﾑﾚｰｽ", "ﾀｲﾑﾚｰｽ総合結果"))
        self.assertFalse(same_race_rounds("予選", "決勝"))

    def test_same_profile_double_listing_merged(self):
        from dataclasses import replace
        from labo.adapters.rkm_mapping import build_duplicate_links
        a = replace(res("A", D(2021, 6, 1), 930, comp="C1", rid="R1"), round_raw="ﾀｲﾑﾚｰｽ")
        b = replace(res("A", D(2021, 6, 1), 930, comp="C1", rid="R2"), round_raw="ﾀｲﾑﾚｰｽ総合結果")
        p = replace(res("A", D(2021, 6, 2), 940, comp="C2", rid="R3"), round_raw="予選")
        f = replace(res("A", D(2021, 6, 2), 940, comp="C2", rid="R4"), round_raw="決勝")  # 予選と決勝が同タイム
        links = build_duplicate_links([a, b, p, f])
        self.assertEqual([(l.canonical, l.duplicate) for l in links], [(a.key, b.key)])
        self.assertEqual(build_duplicate_links([a, b], merge_same_profile=False), [])
        v = values(ds_of([a, b, p, f], links=links))
        self.assertEqual(v["runs_5000_count"].value, 3)

    def test_grade_variants_from_audit(self):
        from labo.adapters.rkm_mapping import infer_hs_entry_fy, parse_grade
        for raw, g in (("H3", 3), ("高校3", 3), ("３+", 3), ("1+", 1)):
            self.assertEqual(parse_grade(raw), g, raw)
        for raw in ("J3", "中1+", "M1", "-", "?", "96", "2000", "▲+", "2*", "4+", "6"):
            self.assertIsNone(parse_grade(raw), raw)
        # 所属名が無くても年次ベストのカテゴリー「高校」で高校と判定。大学カテゴリーとは矛盾扱い
        rows = [(D(2020, 6, 1), "1", None, "高校"), (D(2021, 6, 1), "2", None, "高校"),
                (D(2023, 6, 1), "1", "洛北高", "大学")]
        self.assertEqual(infer_hs_entry_fy(rows), (2020, "derived_from_grade", 2))

    def test_alliance_by_open_participation(self):
        from labo.adapters.rkm_mapping import is_student_alliance
        self.assertTrue(is_student_alliance(None, "OP"))
        self.assertTrue(is_student_alliance(None, " op "))
        self.assertFalse(is_student_alliance(None, "3"))


class HakoneYears(unittest.TestCase):
    def test_parse_years(self):
        from labo.adapters.rkm_mapping import parse_years
        self.assertEqual(parse_years('["2022","2021"]'), [2021, 2022])
        self.assertEqual(parse_years("[]"), [])
        self.assertIsNone(parse_years(None))
        self.assertIsNone(parse_years("abc"))

    def test_complete_editions_per_person(self):
        from labo.adapters.rkm_mapping import person_complete_editions
        window = [2021, 2022, 2023, 2024]
        # 2023年1月・2024年1月に出走（暦年）→ 年度2022・2023。2022年度だけ区間順位の記録あり
        got = person_complete_editions(window, [2023, 2024], ranked_record_fys={2022})
        self.assertEqual(got, {2021, 2022, 2024})
        self.assertEqual(person_complete_editions(window, [], set()), set(window))  # 一度も走っていない
        self.assertEqual(person_complete_editions(window, None, set()), set())       # 情報なし

    def test_label_with_notion_run_years(self):
        from labo.adapters.rkm_mapping import person_complete_editions
        window = OD.edition_fys(2018)
        never_ran = label_person("A", 2018, [], definition=OD, as_of=D(2026, 10, 18),
                                 complete_editions=person_complete_editions(window, [], set()),
                                 linkage_checked=True)
        self.assertEqual(never_ran.label, NEGATIVE_CONFIRMED)
        # 出走年はあるのに区間順位の記録が無い → 不明（未達成と確定しない）
        missing = label_person("A", 2018, [], definition=OD, as_of=D(2026, 10, 18),
                               complete_editions=person_complete_editions(window, [2023], set()),
                               linkage_checked=True)
        self.assertEqual(missing.label, UNKNOWN)

    def test_linkage_checked(self):
        from labo.adapters.rkm_mapping import linkage_checked
        self.assertTrue(linkage_checked('["2021"]', "[]"))
        self.assertFalse(linkage_checked(None, None))  # 追加収集の112人など
