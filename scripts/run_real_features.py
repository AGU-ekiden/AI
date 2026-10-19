"""実データ（rkm・読み取り専用）で特徴量を計算する（チームPCで実行）。

計算するのは初期15特徴量と、特徴量ラボの画面で「計算可能」「研究で採用」になった利用者定義
（data/definitions/ と判断履歴。廃止・未承認は含めない）。特徴量を増やしたら再実行するだけでよい。

    python scripts/run_real_features.py                 # 全員を計算
    python scripts/run_real_features.py --builtin-only  # 初期15特徴量だけ
    python scripts/run_real_features.py --person <ID>   # 1人分の根拠を表示（手計算との突き合わせ用）

出力：
- data/real_features.csv  … 氏名を含む（チームPCの中だけで使う。チャット等に貼らない）
- data/real_summary.json   … 集計のみ（氏名・IDなし）。Claude との共有用
予測・順位付けは行わない。成果ラベルは世代別の件数の集計だけを出す。
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labo.adapters.rkm_loader import load_from_db  # noqa: E402
from labo.features import compute_person, make_context  # noqa: E402
from labo.periods import CUTOFF_PRESETS, DEFAULT_CUTOFF  # noqa: E402
from labo.quality import Options, select_runs  # noqa: E402
from labo.research_job import INITIAL_15, feature_meta, research_definitions, summarize  # noqa: E402,F401

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default=DEFAULT_CUTOFF, choices=sorted(CUTOFF_PRESETS))
    ap.add_argument("--person", help="この person_id の根拠を表示（ローカル確認用）")
    ap.add_argument("--builtin-only", action="store_true", help="初期15特徴量だけを計算")
    ap.add_argument("--data-dir", default=os.environ.get("LABO_DATA_DIR", str(ROOT / "data")),
                    help="特徴量ラボの保存先（利用者定義を読む）")
    args = ap.parse_args()
    rule = CUTOFF_PRESETS[args.cutoff]
    print("読み込み中（読み取り専用）…")
    ds, hakone, rep = load_from_db()
    defs, skipped_defs = research_definitions(Path(args.data_dir), args.builtin_only)
    n_user = sum(not d.builtin for d in defs)
    n_init = sum(d.ref in INITIAL_15 for d in defs)
    print(f"計算する特徴量 {len(defs)}件（初期 {n_init}・第2弾 {len(defs) - n_user - n_init}・利用者定義 {n_user}）")
    for ref, why in skipped_defs.items():
        print(f"  対象外 {ref}：{why}")

    if args.person:
        ath = ds.athletes.get(args.person)
        if ath is None:
            print("その person_id は見つかりません")
            return 1
        ctx = make_context(ds, ath, rule, Options())
        print(f"{ath.name}  入学年度={ath.hs_entry_fiscal_year}（{ath.hs_entry_evidence}）  締切={ctx.cutoff}")
        if ctx.cutoff:
            runs, decisions = select_runs(ds, ath.person_id, "5000m", ctx.cutoff, ctx.hs)
            by_key = {r.key: r for r in ds.results_of(ath.person_id)}
            for d in sorted(decisions, key=lambda d: (by_key[d.key].performed_date or date.min)):
                r = by_key[d.key]
                print(f"  {r.performed_date}  {r.mark_raw:>10}  {d.decision:8} {d.reason:24} {r.competition_name} {r.round_raw}")
        for v in compute_person(ds, ath, defs, rule):
            print(f"  {v.feature_ref:40} {v.value!s:>10} {v.unit:3} {v.reason}  {v.note}")
        return 0

    summary = summarize(ds, hakone, rep, defs, skipped_defs, rule, ROOT / "data" / "real_features.csv")
    out_csv = ROOT / "data" / "real_features.csv"
    n_in, excluded = summary["cohort"]["included"], summary["cohort"]["excluded"]
    out_json = ROOT / "data" / "real_summary.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"対象 {n_in}人（除外 {excluded}）")
    print(f"ローカル専用（氏名あり・共有しない）: {out_csv}")
    print(f"共有用の集計（氏名・IDなし）: {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
