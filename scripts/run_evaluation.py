"""研究評価：特徴量の組み合わせの評価値（世代順の検証での PR-AUC）を出す（チームPCで実行）。

    python scripts/run_evaluation.py                          # 基準＋「研究で採用」のセット（候補は1つずつ試す）
    python scripts/run_evaluation.py --all                    # 承認済みの全特徴量を入れたセット
    python scripts/run_evaluation.py --features best_5000_s@1,grade1_to_grade2_improvement_s@1
    python scripts/run_evaluation.py --final-check            # 取り置いた最新世代も含めた最終確認（たまにだけ）

出力（集計のみ・氏名・ID・個人ごとのスコアなし。Claude と共有してよい）：
- data/eval_summary.json   … 評価値・基準との差・特徴量ごとの上積み・係数・較正
- data/eval_history.jsonl  … 実行ごとの評価値の記録（特徴量を増やしたときの推移）
個人ごとの予測値・確率・順位は作成も保存もしない。
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labo.periods import CUTOFF_PRESETS, DEFAULT_CUTOFF  # noqa: E402
from labo.research_job import BASELINE, build_rows, choose, evaluate_and_save, research_definitions  # noqa: E402,F401


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", help="評価値を出すセット（カンマ区切りの ref）。省略時は「研究で採用」の特徴量")
    ap.add_argument("--all", action="store_true", help="評価値を出すセットを承認済みの全特徴量にする")
    ap.add_argument("--final-check", action="store_true", help="取り置いた最新世代も含める（最終確認用）")
    ap.add_argument("--cutoff", default=DEFAULT_CUTOFF, choices=sorted(CUTOFF_PRESETS))
    ap.add_argument("--data-dir", default=os.environ.get("LABO_DATA_DIR", str(ROOT / "data")))
    ap.add_argument("--note", default="", help="この実行のメモ（履歴に残る。氏名は書かない）")
    args = ap.parse_args()

    from labo.adapters.rkm_loader import load_from_db
    rule = CUTOFF_PRESETS[args.cutoff]
    out = Path(args.data_dir)
    defs, _ = research_definitions(out)
    try:
        cand, selected, _ = choose(defs, args.features, args.all)
    except ValueError as e:
        raise SystemExit(str(e))
    print("読み込み中（読み取り専用）…")
    ds, hakone, _ = load_from_db()
    print(f"評価中（セット＝基準＋{len(selected)}件・1つずつ試す候補 {len(cand)}件）…")
    res = evaluate_and_save(ds, hakone, defs, rule, out, args.features, args.all, args.final_check, args.note)

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
    print(f"評価したセット: {', '.join(res['features_used'])}")
    ci_txt = lambda c: "" if not c else f"（95%区間 {c['low']:+.3f}〜{c['high']:+.3f}）"  # noqa: E731
    print("セットに足すと上がるか（いまのセットに1つ足したときの評価値の差）:")
    for p in sorted((p for p in res["per_feature"] if not p["in_set"]),
                    key=lambda p: -(p.get("add_to_set") if p.get("add_to_set") is not None else -9)):
        print(f"  {fmt(p.get('add_to_set')):>7}{ci_txt(p.get('add_to_set_ci'))}  {p.get('name', '')} {p['ref']}")
    inset = [p for p in res["per_feature"] if p["in_set"]]
    if inset:
        print("セットから抜くと下がるか（下がる幅が大きいほど効いている）:")
        for p in inset:
            print(f"  {fmt(p.get('drop_from_full')):>7}  {p.get('name', '')} {p['ref']}")
    print("「研究で採用」にした特徴量が次回からセットに入ります（画面のファクター一覧で変更）。")
    print(f"共有用の集計（氏名・IDなし）: {out / 'eval_summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
