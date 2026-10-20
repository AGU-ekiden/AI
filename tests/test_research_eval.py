import json
import math
import random
import unittest
from datetime import date

from labo import research_eval as re_
from labo.research_eval import EvalConfig, EvalRow, average_precision, evaluate, roc_auc


def synthetic(seed=1, signal=1.0):
    rng = random.Random(seed)
    rows = []
    for fy in range(2004, 2024):
        for _ in range(50):
            z, u = rng.gauss(0, 1), rng.gauss(0, 1)
            vals = {"best": 900 - 20 * z + rng.gauss(0, 10), "sig": u,
                    "noise": rng.gauss(0, 1) if rng.random() > 0.3 else None}
            p = 1 / (1 + math.exp(-(-2 + 1.5 * z + signal * u)))
            label = "positive" if rng.random() < p else "negative_confirmed"
            if fy >= 2020:
                label = "tracking"
            elif rng.random() < 0.05:
                label = "unknown"
            rows.append(EvalRow(fy, label, vals))
    return rows


class MetricTests(unittest.TestCase):
    def test_metrics(self):
        self.assertAlmostEqual(average_precision([1, 0, 1, 0], [0.9, 0.8, 0.7, 0.1]), (1 + 2 / 3) / 2)
        self.assertEqual(roc_auc([1, 1, 0, 0], [0.9, 0.8, 0.2, 0.1]), 1.0)
        self.assertEqual(roc_auc([1, 0], [0.5, 0.5]), 0.5)
        self.assertIsNone(average_precision([0, 0], [0.1, 0.2]))


class EvaluationTests(unittest.TestCase):
    def test_real_signal_raises_score_over_baseline(self):
        res = evaluate(synthetic(), EvalConfig(baseline=["best"], candidates=["sig", "noise"], bootstrap=100))
        self.assertGreater(res["score"], res["baseline_score"])
        top = res["per_feature"][0]
        self.assertEqual(top["ref"], "sig")
        self.assertGreater(top["add_to_baseline"], 0.03)
        self.assertGreater(res["gain_ci"]["low"], 0)

    def test_selected_set_and_add_to_set(self):
        res = evaluate(synthetic(), EvalConfig(baseline=["best"], candidates=["sig", "noise"], selected=["noise"],
                                               bootstrap=40))
        self.assertEqual(res["features_used"], ["best", "noise"])
        by = {p["ref"]: p for p in res["per_feature"]}
        self.assertFalse(by["sig"]["in_set"])
        self.assertGreater(by["sig"]["add_to_set"], 0.03)   # いまのセットに足すと上がる
        self.assertIn("drop_from_full", by["noise"])
        base_only = evaluate(synthetic(), EvalConfig(baseline=["best"], candidates=["sig"], selected=[], bootstrap=0))
        self.assertEqual(base_only["score"], base_only["baseline_score"])

    def test_hits_at_10_backtest(self):
        res = evaluate(synthetic(), EvalConfig(baseline=["best"], candidates=["sig"], selected=["sig"], bootstrap=0))
        h = res["hits_at_10"]
        self.assertEqual(h["k"], 10)
        self.assertGreater(h["hits"], h["baseline_hits"])   # 本当に効く特徴量なら毎年10人選んだときの的中が増える
        self.assertLessEqual(h["hits_outside_baseline_top"], h["hits"])

    def test_group_description(self):
        from labo.research_eval import describe
        rows = [(EvalRow(2010, "positive", {"x": float(i)}), 1) for i in range(4)] + \
               [(EvalRow(2011, "negative_confirmed", {"x": float(i) if i < 6 else None}), 0) for i in range(8)]
        d = describe(rows, "x")
        self.assertIsNone(d["median_pos"])          # 4人は少なすぎるので出さない
        self.assertEqual(d["median_neg"], 2.5)
        self.assertEqual(d["coverage_by_year"], {"2010": 1.0, "2011": 0.75})

    def test_tracking_unknown_and_holdout_are_not_used(self):
        rows = synthetic()
        res = evaluate(rows, EvalConfig(baseline=["best"], candidates=["sig"], bootstrap=0))
        self.assertTrue(all(int(y) < 2018 for y in res["years"]))
        self.assertEqual(res["excluded_labels"], sum(r.label in ("tracking", "unknown") for r in rows))
        final = evaluate(rows, EvalConfig(baseline=["best"], candidates=["sig"], bootstrap=0, include_holdout=True))
        self.assertIn("2019", final["years"])
        self.assertNotIn("2020", final["years"])  # 追跡中は最終確認でも使わない

    def test_training_never_uses_test_or_later_generations(self):
        seen = []
        orig = re_.make_prep

        def spy(train, refs):
            seen.append(max(r.entry_fy for r in train))
            return orig(train, refs)
        re_.make_prep = spy
        try:
            data = re_.labeled(synthetic(), EvalConfig(baseline=["best"], candidates=[]))
            pred = re_.forward_chain(data, ["best"], EvalConfig(baseline=["best"], candidates=[]))
        finally:
            re_.make_prep = orig
        tested = sorted({yr for yr, _, _ in pred})
        self.assertEqual(len(seen), len(tested))
        self.assertTrue(all(s < t for s, t in zip(seen, tested)))

    def test_output_is_aggregate_only(self):
        rows = synthetic()
        res = evaluate(rows, EvalConfig(baseline=["best"], candidates=["sig", "noise"], bootstrap=20))
        text = json.dumps(res, ensure_ascii=False)
        self.assertLess(len(res["calibration"]), 10)

        def longest_list(o):
            if isinstance(o, dict):
                return max([longest_list(v) for v in o.values()] + [0])
            if isinstance(o, list):
                return max([len(o)] + [longest_list(v) for v in o])
            return 0
        self.assertLess(longest_list(res), 30)  # 個人ごとの値の並びを含まない
        self.assertNotIn("person", text)


class ScriptRowsTests(unittest.TestCase):
    def test_build_rows_from_loader(self):
        import importlib.util
        from pathlib import Path
        from labo.adapters.rkm_loader import build_dataset, outcome_labels
        from labo.catalog import builtin_definitions
        from labo.outcomes import OutcomeDefinition
        from labo.periods import CUTOFF_PRESETS
        from tests.test_rkm_loader import rows
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("run_evaluation", root / "scripts" / "run_evaluation.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ds, hk, _ = build_dataset(rows())
        labels = outcome_labels(ds, hk, OutcomeDefinition(), date(2026, 10, 19))
        defs = builtin_definitions()
        out = mod.build_rows(ds, labels, defs, CUTOFF_PRESETS["g2_aug31"])
        self.assertEqual(len(out), 1)  # P2 は入学年度不明で対象外
        self.assertIn("best_5000_s@1", out[0].values)
        cand, selected, not_model = mod.choose(defs)
        self.assertNotIn("best_5000_s@1", cand)
        self.assertIn("runs_5000_count@1", not_model)
        self.assertEqual(selected, [])  # 「研究で採用」がなければセットは基準だけ
        self.assertEqual(mod.choose(defs, use_all=True)[1], cand)
        self.assertEqual(mod.choose(defs, "best_5000_s@1,grade1_best_5000_s@1")[1], ["grade1_best_5000_s@1"])


if __name__ == "__main__":
    unittest.main()


class CandidateScoreTests(unittest.TestCase):
    """候補者の点数（合成データ・架空の人物で確認）。"""

    def test_scores_ranges_and_file_permissions(self):
        import os
        import stat
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from labo import synthetic
        from labo.features import compute_person
        from labo.periods import CUTOFF_PRESETS
        from labo.research_job import research_definitions, score_candidates
        ds = synthetic.generate()
        rule = CUTOFF_PRESETS["g2_aug31"]
        with tempfile.TemporaryDirectory() as tmp:
            defs, _ = research_definitions(Path(tmp))
            best = {}
            for pid, ath in ds.athletes.items():
                if ath.hs_entry_fiscal_year is None:
                    continue
                v = {x.feature_ref: x.value for x in compute_person(ds, ath, defs, rule)}.get("best_5000_s@1")
                best[pid] = v
            cut = sorted(v for v in best.values() if v is not None)[len(best) // 3]
            labels = {pid: SimpleNamespace(label=("tracking" if i % 5 == 0 else
                                                  "positive" if (best.get(pid) or 9999) <= cut else "negative_confirmed"))
                      for i, pid in enumerate(sorted(ds.athletes))}
            res = score_candidates(ds, labels, defs, rule, Path(tmp), n_boot=10)
            p = Path(tmp) / "candidates.json"
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        self.assertEqual(res["features"], ["best_5000_s@1"])  # 「研究で採用」がなければ基準だけ
        self.assertTrue(res["persons"])
        for x in res["persons"]:
            self.assertTrue(0 <= x["score"] <= 1)
            self.assertAlmostEqual(x["gain"], 0, places=4)      # セット＝基準なら期待超えは0
            if x["values"]["best_5000_s@1"] is None:
                self.assertIn("best_5000_s@1", x["missing"])
        self.assertTrue(any(x["label"] == "tracking" for x in res["persons"]))
