"""実データでの特徴量の集計と研究評価（スクリプトと画面「研究状況」の共通処理）。

出力のうち real_summary.json・eval_summary.json・eval_history.jsonl は集計のみ（氏名・IDなし）。
real_features.csv と candidates.json（候補者の点数）は氏名入りでチームPCの外に出さない。
個人の点数はスカウトの対象を絞るための参考で、最終判断は人が行う（2026-10-20 利用者決定）。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .catalog import builtin_definitions
from .cohorts import builtin_cohorts, evaluate
from .definitions import RUNNABLE_STATUSES
from .features import compute_person, make_context
from .outcomes import OutcomeDefinition
from .quality import Options, select_runs
from .research_eval import EvalConfig, EvalRow, SelectionSettings, auto_select, evaluate as evaluate_rows
from .store import Store


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


INITIAL_15 = {d.ref for d in builtin_definitions()}


def research_definitions(data_dir: Path, builtin_only: bool = False):
    """計算対象の定義と、対象外にした利用者定義（理由つき）を返す。"""
    defs = Store(data_dir).definitions()
    chosen, skipped = [], {}
    for d in defs:
        if d.builtin and builtin_only:
            ok = d.ref in INITIAL_15
        elif d.builtin:
            ok = d.review_status in RUNNABLE_STATUSES
        else:
            ok = not builtin_only and d.review_status in RUNNABLE_STATUSES
        if ok:
            chosen.append(d)
        elif not builtin_only:
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



def summarize(ds, hakone, rep, defs, skipped_defs, rule, out_csv: Optional[Path] = None) -> dict:
    """全員の特徴量を計算して集計を返す。out_csv があれば氏名入りの値を書く（ローカル専用）。"""
    from .adapters.rkm_loader import outcome_labels
    cohort = next(c for c in builtin_cohorts() if c.cohort_id == "all_with_entry_year")
    feat_vals = {d.ref: [] for d in defs}
    feat_reasons = {d.ref: Counter() for d in defs}
    excluded = Counter()
    decisions = Counter()
    ambiguous = Counter()
    f = None
    if out_csv is not None:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        f = open(out_csv, "w", newline="", encoding="utf-8-sig")
    try:
        w = csv.writer(f) if f else None
        if w:
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
            if w:
                w.writerow([pid, ath.name, ath.hs_entry_fiscal_year, ctx.cutoff]
                           + ["" if v.value is None else v.value for v in vals])
    finally:
        if f:
            f.close()

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
                 "hs_ekiden": rep.ekiden,
                 "hs_ekiden_names": {k: dict(sorted(v.items(), key=lambda t: -t[1])[:30])
                                     for k, v in rep.ekiden_names.items()},
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
    return summary


# ---- 研究評価 ----
BASELINE = ["best_5000_s@1"]


def build_rows(ds, labels, defs, rule) -> list[EvalRow]:
    """対象者ごとの特徴量と成果ラベル（メモリ内のみ）。人物IDは持たない。"""
    cohort = next(c for c in builtin_cohorts() if c.cohort_id == "all_with_entry_year")
    rows = []
    for pid in sorted(ds.athletes):
        ath = ds.athletes[pid]
        if not evaluate(cohort, ds, ath, rule)[0]:
            continue
        vals = {v.feature_ref: v.value for v in compute_person(ds, ath, defs, rule)}
        rows.append(EvalRow(ath.hs_entry_fiscal_year, labels[pid].label, vals))
    return rows


def choose(defs, requested: Optional[str] = None, use_all: bool = False):
    """（1つずつ試す候補, 評価値を出すセット, 品質表示専用で使わない一覧）。

    セットの既定は「研究で採用」にした特徴量（＋基準）。requested で指定、use_all で候補すべて。
    品質表示専用（model_input=False）はモデルに入れない。"""
    by_ref = {d.ref: d for d in defs}
    cand = [d.ref for d in defs if d.model_input_allowed and d.ref not in BASELINE]
    not_model = [d.ref for d in defs if not d.model_input_allowed]
    if requested:
        refs = [r.strip() for r in requested.split(",") if r.strip()]
        unknown = [r for r in refs if r not in by_ref]
        if unknown:
            raise ValueError(f"計算対象にない特徴量: {', '.join(unknown)}")
        selected = [r for r in refs if r in cand]
    elif use_all:
        selected = list(cand)
    else:
        selected = [r for r in cand if by_ref[r].review_status == "研究で採用"]
    return cand, selected, not_model


def load_selection_settings(data_dir: Path) -> SelectionSettings:
    p = Path(data_dir) / "selection_settings.json"
    try:
        return SelectionSettings.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return SelectionSettings()


def save_selection_settings(data_dir: Path, payload: dict) -> SelectionSettings:
    s = SelectionSettings.from_dict(payload)
    (Path(data_dir) / "selection_settings.json").write_text(json.dumps(s.to_dict(), ensure_ascii=False), encoding="utf-8")
    return s


def evaluate_and_save(ds, hakone, defs, rule, data_dir: Path, requested: Optional[str] = None,
                      use_all: bool = False, final_check: bool = False, note: str = "") -> dict:
    """研究評価を実行し、eval_summary.json と eval_history.jsonl（集計のみ）に書く。"""
    from .adapters.rkm_loader import outcome_labels
    cand, selected, not_model = choose(defs, requested, use_all)
    od = OutcomeDefinition()
    labels = outcome_labels(ds, hakone, od, datetime.now(timezone.utc).date())
    rows = build_rows(ds, labels, defs, rule)
    cfg = EvalConfig(baseline=BASELINE, candidates=cand, selected=selected, include_holdout=final_check)
    info = {d.ref: {"name": d.display_name, "category": d.category} for d in defs}
    res = evaluate_rows(rows, cfg, info)
    settings = load_selection_settings(data_dir)
    if settings.enabled and not final_check:  # 提案だけ。採用は人が「研究で採用」で決める
        res["auto_selection"] = auto_select(rows, cfg, list(res["features_used"]), cand, settings, info)
    feature_set = sorted(res["features_used"])
    res.update({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cutoff": rule.label, "outcome_definition": od.ref, "dataset": ds.label,
        "feature_set_id": hashlib.sha256(json.dumps(feature_set).encode()).hexdigest()[:10],
        "not_model_input": not_model, "note": note, "final_check": final_check,
        "features_meta": {d.ref: feature_meta(d) for d in defs if d.ref in set(feature_set) | set(cand)},
    })
    data_dir = Path(data_dir)
    (data_dir / "eval_summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    hist = {k: res[k] for k in ("generated_at", "feature_set_id", "score", "baseline_score",
                                "gain_over_baseline", "gain_ci", "note")}
    hist.update({"n_features": len(feature_set), "final_check": final_check,
                 "features": feature_set, "n": res["full"].get("n"), "positives": res["full"].get("positives")})
    with open(data_dir / "eval_history.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(hist, ensure_ascii=False) + "\n")
    return res


def run_all(data_dir: Path, rule, loaded=None, progress=lambda msg: None, note: str = "") -> tuple[dict, dict]:
    """DBから読み込み（loaded があればそれを使う）→ 集計 → 研究評価。画面の「再計算・再評価」用。"""
    from .adapters.rkm_loader import load_from_db
    data_dir = Path(data_dir)
    progress("実データを読み込み中（読み取り専用）")
    ds, hakone, rep = loaded if loaded is not None else load_from_db()
    defs, skipped = research_definitions(data_dir)
    progress(f"特徴量 {len(defs)}件を計算中")
    summary = summarize(ds, hakone, rep, defs, skipped, rule, data_dir / "real_features.csv")
    (data_dir / "real_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    progress("研究評価を実行中（数分かかることがあります）")
    ev = evaluate_and_save(ds, hakone, defs, rule, data_dir, note=note)
    progress("候補者の点数を計算中")
    from .adapters.rkm_loader import outcome_labels
    labels = outcome_labels(ds, hakone, OutcomeDefinition(), datetime.now(timezone.utc).date())
    score_candidates(ds, labels, defs, rule, data_dir)
    return summary, ev


# ---- 候補者の点数（2026-10-20 利用者決定：個人の点数・順位を作る。最終判断は人が行う）----
def score_candidates(ds, labels, defs, rule, data_dir: Path, n_boot: int = 40, seed: int = 20261020) -> dict:
    """箱根で活躍する可能性の点数（％）と、5000mベストだけの場合との差（期待超え）を対象者全員に付ける。

    - 学習は成果が確定した人（達成・未達成（確定））全員。点数は結果待ちの世代を含む全員に付ける。
    - 範囲：学習データを再抽出して学び直したときの点数の10〜90%。
    - 根拠：各入力が点数をどれだけ押し上げ・押し下げたか。記録の欠けは「データ不足」として示す。
    出力 data/candidates.json（権限600）は氏名を含むのでチームのPCの外に出さない。"""
    from .evaluation import trainable
    from .research_eval import contributions, fit_model, predict

    _, selected, _ = choose(defs)
    full = list(dict.fromkeys(BASELINE + selected))
    by_ref = {d.ref: d for d in defs}
    cohort = next(c for c in builtin_cohorts() if c.cohort_id == "all_with_entry_year")
    people = []
    for pid in sorted(ds.athletes):
        ath = ds.athletes[pid]
        if not evaluate(cohort, ds, ath, rule)[0]:
            continue
        vals = {v.feature_ref: v.value for v in compute_person(ds, ath, defs, rule)}
        people.append((pid, ath, EvalRow(ath.hs_entry_fiscal_year, labels[pid].label, vals)))
    era = EvalConfig(baseline=BASELINE, candidates=[]).data_from_fy  # 研究評価と同じく収録が十分な世代で学習
    train = [(row, trainable(row.label)) for _, _, row in people
             if trainable(row.label) is not None and (era is None or row.entry_fy >= era)]
    if not train or not any(t for _, t in train):
        raise ValueError("成果が確定した人（達成者を含む）がいないため点数を付けられません")
    l2 = EvalConfig(baseline=BASELINE, candidates=[]).l2
    prep, w = fit_model(train, full, l2)
    prep_b, w_b = fit_model(train, BASELINE, l2)
    rng = random.Random(seed)
    boots = []
    for _ in range(n_boot):
        smp = [rng.choice(train) for _ in train]
        if sum(t for _, t in smp) >= 5:
            boots.append(fit_model(smp, full, l2))
    out = []
    for pid, ath, row in people:
        p = predict(w, prep.vec(row))
        pb = predict(w_b, prep_b.vec(row))
        bs = sorted(predict(bw, bp.vec(row)) for bp, bw in boots)
        lo = round(bs[int(0.1 * len(bs))], 4) if bs else None
        hi = round(bs[min(len(bs) - 1, int(0.9 * len(bs)))], 4) if bs else None
        out.append({
            "person_id": pid, "name": ath.name, "entry_fy": ath.hs_entry_fiscal_year, "label": row.label,
            "score": round(p, 4), "score_baseline": round(pb, 4), "gain": round(p - pb, 4), "low": lo, "high": hi,
            "missing": [r for r in full if row.values.get(r) is None],
            "values": {r: row.values.get(r) for r in full},
            "contributions": contributions(prep, w, row),
        })
    res = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cutoff": rule.label, "outcome_definition": OutcomeDefinition().ref,
        "features": full, "feature_names": {r: by_ref[r].display_name for r in full if r in by_ref},
        "units": {r: by_ref[r].unit for r in full if r in by_ref},
        "trained_on": {"n": len(train), "positives": sum(t for _, t in train)},
        "bootstrap": len(boots), "persons": out,
        "note": "スカウトの対象を絞るための参考。最終判断は人が行う。記録が欠けている項目は「データ不足」と表示し、その人の点数は参考程度に見る。",
    }
    path = Path(data_dir) / "candidates.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    return res
