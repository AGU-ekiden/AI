import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from labo.store import Store

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RealRunDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.store = Store(self.dir)
        self.run = _load("run_real_features")

    def tearDown(self):
        self.tmp.cleanup()

    def _approve(self, ref):
        for to in ("定義確認", "テスト済み"):
            self.store.change_status(ref, to, "ok", "t")
        self.store.change_status(ref, "計算可能", "ok", "u2:other")

    def test_only_runnable_user_definitions_are_added(self):
        ok = self.store.create_definition({"feature_id": "best_1500_s", "spec": {
            "op": "min", "event": "1500m", "window": {"kind": "hs"}}}, "t")
        self._approve(ok.ref)
        draft = self.store.create_definition({"feature_id": "best_3000_s", "spec": {
            "op": "min", "event": "3000m", "window": {"kind": "hs"}}}, "t")
        defs, skipped = self.run.research_definitions(self.dir)
        refs = [d.ref for d in defs]
        self.assertEqual(len(refs), 16)
        self.assertIn(ok.ref, refs)
        self.assertIn(draft.ref, skipped)
        builtin_only, _ = self.run.research_definitions(self.dir, builtin_only=True)
        self.assertEqual(len(builtin_only), 15)

    def test_deprecated_definition_is_dropped(self):
        d = self.store.create_definition({"feature_id": "best_1500_s", "spec": {
            "op": "min", "event": "1500m", "window": {"kind": "hs"}}}, "t")
        self._approve(d.ref)
        self.store.change_status(d.ref, "廃止", "やめる", "t")
        defs, skipped = self.run.research_definitions(self.dir)
        self.assertNotIn(d.ref, [x.ref for x in defs])
        self.assertIn(d.ref, skipped)


class DashboardCsvTests(unittest.TestCase):
    def test_build_has_no_person_columns_and_includes_user_features(self):
        mod = _load("make_dashboard_csv")
        summary = {
            "cohort": {"included": 10, "excluded": {"hs_entry_year_unknown": 2}},
            "load": {"entry_year_reasons": {"derived_from_grade": 9, "majority_of_grades": 1},
                     "duplicate_links": 3, "hakone_supplement": {"used": 1}},
            "decisions_5000m": {"used:ok": 20, "excluded:after_cutoff": 5, "excluded:DNS": 1},
            "features": {
                "runs_5000_count@1": {"non_null": 10, "reasons": {"ok": 10}, "quantiles": {"p10": 1, "p50": 2, "p90": 3}},
                "best_1500_s@1": {"feature_id": "best_1500_s", "name": "1500mベスト", "category": "記録",
                                  "unit": "秒", "model_input": True, "non_null": 4,
                                  "reasons": {"ok": 4, "insufficient_runs": 6}, "quantiles": None},
            },
            "outcome_labels_by_entry_fy": {"2018:positive": 1, "入学年度不明:unknown": 2},
            "hakone_gaps_by_run_year": {"2015:箱根本戦の記録なし": 6},
        }
        out = mod.build(summary)
        feats = out["features.csv"][1]
        self.assertEqual([r[0] for r in feats], ["runs_5000_count", "best_1500_s"])
        self.assertEqual(feats[0][4], "品質表示専用")
        self.assertEqual(feats[1][7], "必要な出走数に満たない")
        self.assertEqual(out["outcomes.csv"][1], [["2018", "達成", 1]])
        self.assertIn(["除外", "DNS（出走せず）", 1], out["decisions_5000m.csv"][1])
        text = json.dumps(out, ensure_ascii=False)
        self.assertNotIn("person_id", text)


if __name__ == "__main__":
    unittest.main()
