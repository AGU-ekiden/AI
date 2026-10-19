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
import csv
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labo.adapters.rkm_loader import load_from_db, outcome_labels  # noqa: E402
from labo.cohorts import builtin_cohorts, evaluate  # noqa: E402
from labo.features import compute_person, make_context  # noqa: E402
from labo.outcomes import OutcomeDefinition  # noqa: E402
from labo.periods import CUTOFF_PRESETS, DEFAULT_CUTOFF  # noqa: E402
from labo.definitions import RUNNABLE_STATUSES  # noqa: E402
from labo.quality import Options, select_runs  # noqa: E402
from labo.store import Store  # noqa: E402


def quantiles(vals):
    if not vals:
        return None
    v = sorted(vals)
    pick = lambda q: v[min(len(v) - 1, int(round((len(v) - 1) * q)))]  # noqa: E731
    return {"p10": pick(0.1), "p50": pick(0.5), "p90": pick(0.9), "min": v[0], "max": v[-1]}


def _diagnose_ambiguous(ds, evidence_keys, counter) -> None:
    """直近N出走の境界で順序不明になった同日の出走の組み合わせを、氏名なしの型として数える。"""
    from labo.adapters.rkm_mapping import round_class
    by_key = {r.key.as_str(): r for r in ds.results}
    rows = [by_key[k] for k in evidence_keys if k in by_key]
    if len(rows) < 2:
        counter["不明（根拠行なし）"] += 1
        return
    same_comp = len({r.competition_id for r in rows}) == 1
    classes = "/".join(sorted(str(round_class(r.round_raw)) for r in rows))
    secs = [r.seconds for r in rows if r.seconds is not None]
    diff = max(secs) - min(secs) if len(secs) >= 2 else None
    bucket = ("差なし" if diff == 0 else "1秒未満" if diff is not None and diff < 1
              else "1〜10秒" if diff is not None and diff < 10 else "10秒以上" if diff is not None else "不明")
    counter[f"{'同じ大会' if same_comp else '別の大会'}｜ラウンド {classes}｜記録の差 {bucket}"] += 1


def research_definitions(data_dir: Path, builtin_only: bool = False):
    """計算対象の定義と、対象外にした利用者定義（理由つき）を返す。"""
    defs = Store(data_dir).definitions()
    chosen, skipped = [], {}
    for d in defs:
        if d.builtin:
            ok = d.review_status != "廃止"
        else:
            ok = not builtin_only and d.review_status in RUNNABLE_STATUSES
        if ok:
            chosen.append(d)
        elif not d.builtin and not builtin_only:
            skipped[d.ref] = f"状態が「{d.review_status}」"
    refs = {d.ref for d in chosen}
    changed = True
    while changed:  # 参照先が対象外の派生特徴量は計算しない
        changed = False
        for d in list(chosen):
            missing = [r for r in d.spec.get("inputs", []) if r not in refs]
            if missing:
                chosen.remove(d)
                refs.discard(d.ref)
                skipped[d.ref] = f"参照先 {', '.join(missing)} が計算対象でない"
                changed = True
    return chosen, skipped


def feature_meta(d) -> dict:
    return {"feature_id": d.feature_id, "version": d.version, "name": d.display_name,
            "category": d.category, "unit": d.unit, "model_input": d.model_input_allowed,
            "builtin": d.builtin, "status": d.review_status}


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
    print(f"計算する特徴量 {len(defs)}件（初期 {len(defs) - n_user}・利用者定義 {n_user}）")
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

    cohort = next(c for c in builtin_cohorts() if c.cohort_id == "all_with_entry_year")
    out_csv = ROOT / "data" / "real_features.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    feat_vals = {d.ref: [] for d in defs}
    feat_reasons = {d.ref: Counter() for d in defs}
    excluded = Counter()
    decisions = Counter()
    ambiguous = Counter()
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
                if v.reason == "ambiguous_order" and v.feature_ref.startswith("latest3"):
                    _diagnose_ambiguous(ds, v.evidence, ambiguous)
                feat_reasons[v.feature_ref][v.reason] += 1
                if v.value is not None:
                    feat_vals[v.feature_ref].append(v.value)
            w.writerow([pid, ath.name, ath.hs_entry_fiscal_year, ctx.cutoff]
                       + ["" if v.value is None else v.value for v in vals])

    # 成果ラベル（世代別の件数のみ）
    od = OutcomeDefinition()
    today = datetime.now(timezone.utc).date()
    labels = Counter()
    unknown_reasons = Counter()
    hakone_gaps = Counter()
    by_person = {}
    for lg in hakone.legs:
        by_person.setdefault(lg.person_id, []).append(lg)
    for pid, years in hakone.run_years.items():
        for y in years or []:
            recs = [lg for lg in by_person.get(pid, []) if lg.edition_fy == y - 1]
            if not recs:
                hakone_gaps[(str(y), "箱根本戦の記録なし")] += 1
            elif not any(lg.official_rank is not None or lg.reference_only for lg in recs):
                hakone_gaps[(str(y), "記録はあるが区間順位なし")] += 1
    all_labels = outcome_labels(ds, hakone, od, today)
    for pid, ath in ds.athletes.items():
        if ath.hs_entry_fiscal_year is None:
            labels[("入学年度不明", "unknown")] += 1
            continue
        lab = all_labels[pid]
        labels[(str(ath.hs_entry_fiscal_year), lab.label)] += 1
        if lab.label == "unknown":
            reason = lab.reason.split("：")[0].split(":")[0]
            if reason.startswith("区間順位が未取り込み"):
                reason = "出走年にあるのに箱根本戦の区間記録が見つからない年がある"
            unknown_reasons[(str(ath.hs_entry_fiscal_year), reason)] += 1

    n_in = len(ds.athletes) - sum(excluded.values())
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cutoff": rule.label, "dataset": ds.label,
        "load": {"persons": rep.persons, "result_rows": rep.results, "entry_year_reasons": rep.entry_year,
                 "duplicate_links": rep.duplicate_links, "date_maybe_first_day_rows": rep.date_maybe_first_day,
                 "excluded_rows": rep.excluded_rows, "entry_year_conflicts": rep.entry_conflicts,
                 "hakone_legs": len(hakone.legs),
                 "hakone_supplement": {"used": hakone.supplement_used, "rejected": hakone.supplement_rejected},
                 "hakone_ambiguous_records": hakone.ambiguous_records},
        "cohort": {"included": n_in, "excluded": dict(excluded)},
        "decisions_5000m": {f"{k[0]}:{k[1]}": v for k, v in decisions.most_common()},
        "features": {d.ref: {**feature_meta(d), "non_null": len(feat_vals[d.ref]),
                             "reasons": dict(feat_reasons[d.ref]),
                             "quantiles": quantiles(feat_vals[d.ref])} for d in defs},
        "features_skipped": skipped_defs,
        "outcome_labels_by_entry_fy": {f"{k[0]}:{k[1]}": v for k, v in sorted(labels.items())},
        "outcome_unknown_reasons": {f"{k[0]}:{k[1]}": v for k, v in sorted(unknown_reasons.items())},
        "outcome_definition": od.ref,
        "hakone_gaps_by_run_year": {f"{k[0]}:{k[1]}": v for k, v in sorted(hakone_gaps.items())},
        "ambiguous_order_patterns": {k: v for k, v in ambiguous.most_common()},
    }
    out_json = ROOT / "data" / "real_summary.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"対象 {n_in}人（除外 {dict(excluded)}）")
    print(f"ローカル専用（氏名あり・共有しない）: {out_csv}")
    print(f"共有用の集計（氏名・IDなし）: {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
