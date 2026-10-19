"""第2弾の特徴量（中学の記録・高校の他種目・駅伝）。氏名は架空。"""
import tempfile
import unittest
from pathlib import Path

from labo.adapters.rkm_loader import build_dataset
from labo.adapters.rkm_mapping import ekiden_race_class
from labo.catalog import phase2_definitions
from labo.definitions import SpecError, validate_spec
from labo.features import compute_person
from labo.periods import CUTOFF_PRESETS, junior_grade_window, junior_window
from labo.store import Store
from tests.test_rkm_loader import rows

AUG = CUTOFF_PRESETS["g2_aug31"]
NAT = "第71回全国高等学校駅伝競走大会"
TDF = "第26回全国都道府県対抗男子駅伝競走大会"


def rows2():
    r = rows()
    r["results"] = r["results"] + [
        ("P1", "pa", "j1", "2019-08-01", "J1", "全日本中学校選手権", "3000m", "track", "決勝", "8.40.00", 520.0, "s", "electronic", None),
        ("P1", "pa", "j2", "2018-07-01", "J2", "記録会", "3000m", "track", None, "9.10.00", 550.0, "s", "electronic", None),
        ("P1", "pa", "j3", "2016-07-01", "J3", "記録会", "3000m", "track", None, "8.00.00", 480.0, "s", "electronic", None),  # 中学より前
    ]
    r["hs_ekiden"] = [
        ("P1", "pa", "e1", "2020-12-20", NAT, 3, 1500.0, 5, None),
        ("P1", "pb", "e1b", "2020-12-20", NAT, 3, 1500.0, 5, None),        # 別プロフィールの同じ区間
        ("P1", "pa", "e2", "2021-01-17", TDF, None, None, None, None),     # 区間は ekiden_legs から
        ("P1", "pa", "e3", "2019-01-20", TDF, 8, 900.0, 3, None),          # 中学生区間
        ("P1", "pa", "e4", "2021-12-26", NAT, 1, 1800.0, 1, None),         # 締切後（高2の12月）
        ("P1", "pa", "e5", "2020-11-01", "第73回架空県高校駅伝", 2, 600.0, None, None),
        ("P1", "pa", "e6", "2020-12-20", "全国高校駅伝（女子）", 1, 1200.0, 1, None),
        ("P1", "pa", "e7", "2020-10-01", "架空地区高校駅伝", 4, None, None, "DNS"),
    ]
    r["hs_ekiden_self_legs"] = [("P1", "pa", "e2", 4, 12, 1000.0)]
    return r


class Phase2Tests(unittest.TestCase):
    def setUp(self):
        self.ds, _, self.rep = build_dataset(rows2())
        self.p1 = self.ds.athletes["P1"]
        vals = compute_person(self.ds, self.p1, phase2_definitions(), AUG)
        self.v = {x.feature_ref.split("@")[0]: x for x in vals}

    def test_windows(self):
        self.assertEqual(self.p1.hs_entry_fiscal_year, 2020)
        jw = junior_window(2020)
        self.assertEqual((jw.start.isoformat(), jw.end.isoformat()), ("2017-04-01", "2020-03-31"))
        self.assertEqual(junior_grade_window(2020, 3).start.isoformat(), "2019-04-01")

    def test_junior_records(self):
        self.assertEqual(self.v["junior_best_3000_s"].value, 520.0)  # 中学より前の 8:00 は使わない
        self.assertEqual(self.v["junior3_best_3000_s"].value, 520.0)
        self.assertIsNone(self.v["junior_best_1500_s"].value)
        self.assertEqual(self.v["hs_best_3000_s"].reason, "insufficient_runs")  # 中学の記録は高校の窓に入らない

    def test_ekiden(self):
        self.assertEqual(self.v["national_hs_ekiden_best_rank"].value, 5.0)  # 締切後の区間1位は使わない
        self.assertEqual(self.v["national_hs_ekiden_legs"].value, 1.0)     # 重複をまとめる
        self.assertEqual(self.v["todofuken_hs_best_rank"].value, 12.0)     # ekiden_legs の本人区間で補完
        self.assertEqual(self.v["todofuken_junior_best_rank"].value, 3.0)
        self.assertEqual(self.v["regional_hs_ekiden_best_rank"].reason, "no_ranked_leg")
        self.assertEqual(self.rep.ekiden.get("重複としてまとめた"), 1)
        self.assertEqual(self.rep.ekiden.get("記録なし・棄権など"), 1)

    def test_race_class(self):
        self.assertEqual(ekiden_race_class(NAT), "national_hs")
        self.assertEqual(ekiden_race_class(TDF), "todofuken")
        self.assertEqual(ekiden_race_class("第73回架空県高校駅伝"), "regional_hs")
        self.assertIsNone(ekiden_race_class("全国高校駅伝（女子）"))
        self.assertIsNone(ekiden_race_class("第100回東京箱根間往復大学駅伝競走"))

    def test_spec_validation(self):
        ok = validate_spec({"op": "ekiden_best_rank", "race": "national_hs", "window": {"kind": "hs"}})
        self.assertEqual(ok["race"], "national_hs")
        with self.assertRaises(SpecError):
            validate_spec({"op": "ekiden_best_rank", "race": "hakone", "window": {"kind": "hs"}})
        with self.assertRaises(SpecError):
            validate_spec({"op": "ekiden_count", "race": "any", "event": "5000m", "window": {"kind": "hs"}})
        with self.assertRaises(SpecError):
            validate_spec({"op": "min", "event": "3000m", "window": {"kind": "junior_grade", "grade": 4}})

    def test_phase2_needs_approval_before_real_runs(self):
        import importlib.util
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("rrf", root / "scripts" / "run_real_features.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            defs, skipped = mod.research_definitions(Path(tmp))
            self.assertEqual(len(defs), 15)
            self.assertIn("junior_best_3000_s@1", skipped)
            store.change_status("junior_best_3000_s@1", "計算可能", "中学の影響を見る", "admin")
            defs, _ = mod.research_definitions(Path(tmp))
            self.assertIn("junior_best_3000_s@1", [d.ref for d in defs])


if __name__ == "__main__":
    unittest.main()
