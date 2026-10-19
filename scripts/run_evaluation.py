"""研究評価：特徴量の組み合わせの評価値（世代順の検証での PR-AUC）を出す（チームPCで実行）。

    python scripts/run_evaluation.py                          # 承認済みの全特徴量（モデル入力可のもの）
    python scripts/run_evaluation.py --features best_5000_s@1,grade1_to_grade2_improvement_s@1
    python scripts/run_evaluation.py --final-check            # 取り置いた最新世代も含めた最終確認（たまにだけ）

出力（集計のみ・氏名・ID・個人ごとのスコアなし。Claude と共有してよい）：
- data/eval_summary.json   … 評価値・基準との差・特徴量ごとの上積み・係数・較正
- data/eval_history.jsonl  … 実行ごとの評価値の記録（特徴量を増やしたときの推移）
個人ごとの予測値・確率・順位は作成も保存もしない。
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from run_real_features import feature_meta, research_definitions  # noqa: E402

from labo.cohorts import builtin_cohorts, evaluate as in_cohort  # noqa: E402
from labo.features import compute_person  # noqa: E402
from labo.outcomes import OutcomeDefinition  # noqa: E402
from labo.periods import CUTOFF_PRESETS, DEFAULT_CUTOFF  # noqa: E402
from labo.research_eval import EvalConfig, EvalRow, evaluate  # noqa: E402

BASELINE = ["best_5000_s@1"]


def build_rows(ds, labels, defs, rule) -> list[EvalRow]:
    """対象者ごとの特徴量と成果ラベル（メモリ内のみ）。人物IDは持たない。"""
    cohort = next(c for c in builtin_cohorts() if c.cohort_id == "all_with_entry_year")
    rows = []
    for pid in sorted(ds.athletes):
        ath = ds.athletes[pid]
        if not in_cohort(cohort, ds, ath, rule)[0]:
            continue
        vals = {v.feature_ref: v.value for v in compute_person(ds, ath, defs, rule)}
        rows.append(EvalRow(ath.hs_entry_fiscal_year, labels[pid].label, vals))
    return rows


def choose(defs, requested: str | None) -> tuple[list[str], list[str]]:
    """（候補, 使わなかった理由つきの一覧）。品質表示専用（model_input=False）は使わない。"""
    by_ref = {d.ref: d for d in defs}
    if requested:
        refs = [r.strip() for r in requested.split(",") if r.strip()]
        unknown = [r for r in refs if r not in by_ref]
        if unknown:
            raise SystemExit(f"計算対象にない特徴量: {', '.join(unknown)}")
    else:
        refs = [d.ref for d in defs]
    cand = [r for r in refs if by_ref[r].model_input_allowed and r not in BASELINE]
    not_model = [r for r in refs if not by_ref[r].model_input_allowed]
    return cand, not_model


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", help="評価する特徴量（カンマ区切りの ref）。省略時は承認済みの全特徴量")
    ap.add_argument("--final-check", action="store_true", help="取り置いた最新世代も含める（最終確認用）")
    ap.add_argument("--cutoff", default=DEFAULT_CUTOFF, choices=sorted(CUTOFF_PRESETS))
    ap.add_argument("--data-dir", default=os.environ.get("LABO_DATA_DIR", str(ROOT / "data")))
    ap.add_argument("--note", default="", help="この実行のメモ（履歴に残る。氏名は書かない）")
    args = ap.parse_args()

    from labo.adapters.rkm_loader import load_from_db, outcome_labels
    rule = CUTOFF_PRESETS[args.cutoff]
    defs, _ = research_definitions(Path(args.data_dir))
    cand, not_model = choose(defs, args.features)
    print("読み込み中（読み取り専用）…")
    ds, hakone, _ = load_from_db()
    od = OutcomeDefinition()
    labels = outcome_labels(ds, hakone, od, datetime.now(timezone.utc).date())
    rows = build_rows(ds, labels, defs, rule)
    cfg = EvalConfig(baseline=BASELINE, candidates=cand, include_holdout=args.final_check)
    info = {d.ref: {"name": d.display_name, "category": d.category} for d in defs}
    print(f"評価中（候補 {len(cand)}件・基準 {BASELINE[0]}）…")
    res = evaluate(rows, cfg, info)

    feature_set = sorted(res["features_used"])
    res.update({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cutoff": rule.label, "outcome_definition": od.ref, "dataset": ds.label,
        "feature_set_id": hashlib.sha256(json.dumps(feature_set).encode()).hexdigest()[:10],
        "not_model_input": not_model, "note": args.note,
        "features_meta": {d.ref: feature_meta(d) for d in defs if d.ref in feature_set},
    })
    out = Path(args.data_dir)
    (out / "eval_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    hist = {k: res[k] for k in ("generated_at", "feature_set_id", "score", "baseline_score",
                                "gain_over_baseline", "gain_ci", "note")}
    hist.update({"n_features": len(feature_set), "final_check": args.final_check,
                 "features": feature_set, "n": res["full"].get("n"), "positives": res["full"].get("positives")})
    with open(out / "eval_history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(hist, ensure_ascii=False) + "\n")

    fmt = lambda v: "—" if v is None else f"{v:.3f}"  # noqa: E731
    print(f"評価値（{res['score_name']}）: {fmt(res['score'])}　基準（5000mベストのみ）: {fmt(res['baseline_score'])}"
          f"　上積み: {fmt(res['gain_over_baseline'])}")
    if res["score"] is None:
        print("  評価できる世代がありません（成果ラベルが確定した人・学習側の達成者が足りない）")
    ci = res["gain_ci"]
    if ci:
        print(f"  上積みの95%区間: {ci['low']:+.3f} 〜 {ci['high']:+.3f}（再抽出で上積みが正だった割合 {ci['share_positive']:.0%}）")
    print(f"  評価した人数 {res['full'].get('n')}（達成 {res['full'].get('positives')}）・評価年度 {res['tested_years']}"
          f"{'・最終確認（取り置き世代を含む）' if args.final_check else ''}")
    print("特徴量ごとの上積み（基準に1つ足したときの PR-AUC の差）:")
    for p in res["per_feature"]:
        print(f"  {fmt(p['add_to_baseline']):>7}  {p['ref']}")
    print(f"共有用の集計（氏名・IDなし）: {out / 'eval_summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
