import unittest
from pathlib import Path

from labo.adapters.hakone_reference import (
    load_reference, match, norm_name, norm_univ, to_supplement_row, univ_match,
)

ROOT = Path(__file__).resolve().parents[1]


class ReferenceData(unittest.TestCase):
    """reference/hakone_2025_official.tsv の整合（公式記録の合計・順位）を毎回確認する。"""

    def setUp(self):
        self.ref = load_reference([ROOT / "reference" / "hakone_2025_official.tsv"])

    def test_shape_and_ranks(self):
        self.assertEqual(len(self.ref), 210)
        to_s = lambda t: sum(int(x) * m for x, m in zip(t.split(":"), (3600, 60, 1)))  # noqa: E731
        for leg in range(1, 11):
            rows = [r for r in self.ref if int(r["leg"]) == leg]
            self.assertEqual(len(rows), 21)
            official = sorted((int(r["leg_rank"]), to_s(r["leg_time"])) for r in rows if r["is_student_alliance"] == "0")
            self.assertEqual(len(official), 20)
            for (ra, ta), (rb, tb) in zip(official, official[1:]):
                self.assertLessEqual(ta, tb)
                if ra == rb:
                    self.assertEqual(ta, tb)

    def test_team_totals(self):
        to_s = lambda t: sum(int(x) * m for x, m in zip(t.split(":"), (3600, 60, 1)))  # noqa: E731
        total = {}
        for r in self.ref:
            total[r["team"]] = total.get(r["team"], 0) + to_s(r["leg_time"])
        self.assertEqual(total["青山学院大学"], to_s("10:41:19"))
        self.assertEqual(total["専修大学"], to_s("11:08:53"))
        self.assertEqual(total["関東学生連合"], to_s("11:06:53"))


class Matching(unittest.TestCase):
    def setUp(self):
        self.ref = load_reference([ROOT / "reference" / "hakone_2025_official.tsv"])

    def test_normalization(self):
        self.assertEqual(norm_name("山﨑 一吹"), norm_name("山崎一吹"))
        self.assertEqual(norm_univ("國學院大學"), norm_univ("国学院大学"))
        self.assertTrue(univ_match("駒澤大学", "駒沢大"))
        self.assertFalse(univ_match("", "中央大学"))

    def test_match_cases(self):
        hit, why = match("黒田 朝日", "青山学院大学", 2025, self.ref)
        self.assertEqual((why, hit["leg"], hit["leg_rank"]), ("matched", "2", "3"))
        self.assertEqual(match("黒田朝日", "中央大学", 2025, self.ref)[1], "university_mismatch")
        self.assertEqual(match("架空 太郎", "青山学院大学", 2025, self.ref)[1], "name_not_found")
        self.assertEqual(match("黒田朝日", "青山学院大学", 2024, self.ref)[1], "no_reference_year")

    def test_partial_name_for_one_name_listing(self):
        hit, why = match("ダンカン マイナ", "専修大学", 2025, self.ref)
        self.assertEqual((why, hit["name"], hit["leg"], hit["leg_rank"]), ("matched_partial_name", "マイナ", "2", "13"))
        self.assertEqual(match("ダンカン マイナ", "青山学院大学", 2025, self.ref)[1], "name_not_found")  # 大学不一致は採らない

    def test_student_alliance_row(self):
        hit, why = match("古川 大晃", "東京大学", 2025, self.ref)
        self.assertEqual(why, "matched")
        row = to_supplement_row("P9", "古川大晃", "東京大学", hit)
        self.assertEqual((row["leg"], row["leg_rank"], row["is_student_alliance"]), ("9", "", "1"))
        self.assertIn("第101回", row["source_note"])
