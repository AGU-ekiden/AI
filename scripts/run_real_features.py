"""実データ（rkm・読み取り専用）で15特徴量を計算する（チームPCで実行）。

    python scripts/run_real_features.py                 # 全員を計算
    python scripts/run_real_features.py --person <ID>   # 1人分の根拠を表示（手計算との突き合わせ用）

出力：
- data/real_features.csv  … 氏名を含む（チームPCの中だけで使う。チャット等に貼らない）
- data/real_summary.json   … 集計のみ（氏名・IDなし）。Claude との共有用
予測・順位付けは行わない。成果ラベルは世代別の件数の集計だけを出す。
"""
import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labo.adapters.rkm_loader import load_from_db  # noqa: E402
from labo.adapters.rkm_mapping import person_complete_editions  # noqa: E402
from labo.catalog import builtin_definitions  # noqa: E402
from labo.cohorts import builtin_cohorts, evaluate  # noqa: E402
from labo.features import compute_person, make_context  # noqa: E402
from labo.outcomes import OutcomeDefinition, label_person  # noqa: E402
from labo.periods import CUTOFF_PRESETS, DEFAULT_CUTOFF  # noqa: E402
from labo.quality import Options, select_runs  # noqa: E402


def quantiles(vals):
    if not vals:
        return None
    v = sorted(vals)
    pick = lambda q: v[min(len(v) - 1, int(round((len(v) - 1) * q)))]  # noqa: E731
    return {"p10": pick(0.1), "p50": pick(0.5), "p90": pick(0.9), "min": v[0], "max": v[-1]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default=DEFAULT_CUTOFF, choices=sorted(CUTOFF_PRESETS))
    ap.add_argument("--person", help="この person_id の根拠を表示（ローカル確認用）")
    args = ap.parse_args()
    rule = CUTOFF_PRESETS[args.cutoff]
    print("読み込み中（読み取り専用）…")
    ds, hakone, rep = load_from_db()
    defs = builtin_definitions()

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

    cohort = next(c for c in builtin_cohorts() if c.cohort_id == "all_with_entry_year")
    out_csv = ROOT / "data" / "real_features.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    feat_vals = {d.ref: [] for d in defs}
    feat_reasons = {d.ref: Counter() for d in defs}
    excluded = Counter()
    decisions = Counter()
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["# 実データ（非公開）。チームPCの外に出さないこと。予測・順位ではありません"])
        w.writerow(["person_id", "name", "hs_entry_fy", "cutoff"] + [d.ref for d in defs])
        for pid in sorted(ds.athletes):
            ath = ds.athletes[pid]
            ok, why = evaluate(cohort, ds, ath, rule)
            if not ok:
                excluded[why] += 1
                continue
            ctx = make_context(ds, ath, rule, Options())
            for d in select_runs(ds, pid, "5000m", ctx.cutoff, ctx.hs)[1]:
                decisions[(d.decision, d.reason)] += 1
            vals = compute_person(ds, ath, defs, rule)
            for v in vals:
                feat_reasons[v.feature_ref][v.reason] += 1
                if v.value is not None:
                    feat_vals[v.feature_ref].append(v.value)
            w.writerow([pid, ath.name, ath.hs_entry_fiscal_year, ctx.cutoff]
                       + ["" if v.value is None else v.value for v in vals])

    # 成果ラベル（世代別の件数のみ）
    od = OutcomeDefinition()
    today = datetime.now(timezone.utc).date()
    labels = Counter()
    for pid, ath in ds.athletes.items():
        if ath.hs_entry_fiscal_year is None:
            labels[("入学年度不明", "unknown")] += 1
            continue
        window = od.edition_fys(ath.hs_entry_fiscal_year)
        mine = [lg for lg in hakone.legs if lg.person_id == pid]
        ranked = {lg.edition_fy for lg in mine if lg.official_rank is not None or lg.reference_only}
        lab = label_person(pid, ath.hs_entry_fiscal_year, mine, definition=od, as_of=today,
                           complete_editions=person_complete_editions(window, hakone.run_years.get(pid), ranked),
                           linkage_checked=hakone.run_years.get(pid) is not None and hakone.entry_years.get(pid) is not None)
        labels[(str(ath.hs_entry_fiscal_year), lab.label)] += 1

    n_in = len(ds.athletes) - sum(excluded.values())
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cutoff": rule.label, "dataset": ds.label,
        "load": {"persons": rep.persons, "result_rows": rep.results, "entry_year_reasons": rep.entry_year,
                 "duplicate_links": rep.duplicate_links, "date_maybe_first_day_rows": rep.date_maybe_first_day,
                 "excluded_rows": rep.excluded_rows, "hakone_legs": len(hakone.legs),
                 "hakone_ambiguous_records": hakone.ambiguous_records},
        "cohort": {"included": n_in, "excluded": dict(excluded)},
        "decisions_5000m": {f"{k[0]}:{k[1]}": v for k, v in decisions.most_common()},
        "features": {ref: {"non_null": len(feat_vals[ref]), "reasons": dict(feat_reasons[ref]),
                           "quantiles": quantiles(feat_vals[ref])} for ref in feat_vals},
        "outcome_labels_by_entry_fy": {f"{k[0]}:{k[1]}": v for k, v in sorted(labels.items())},
        "outcome_definition": od.ref,
    }
    out_json = ROOT / "data" / "real_summary.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"対象 {n_in}人（除外 {dict(excluded)}）")
    print(f"ローカル専用（氏名あり・共有しない）: {out_csv}")
    print(f"共有用の集計（氏名・IDなし）: {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
