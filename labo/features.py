"""特徴量計算エンジン（純粋関数）。

値と同時に件数・対象期間・使った行ID・欠損理由を返す。データ不足は null と理由で示す。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import Optional

from .definitions import DUP_SENSITIVE_OPS, EKIDEN_OPS, FeatureDefinition
from .model import COVERAGE_FETCHED, Athlete, Dataset
from .periods import Window, grade_window, hs_window, junior_grade_window, junior_window, recent_window
from .quality import EligibleRun, Options, RowDecision, select_runs

MISSING_LABELS = {
    "hs_entry_year_unknown": "高校入学年度が不明（年齢・現在の所属から補完しない）",
    "coverage_unknown": "対象人物の取得状態が不明",
    "insufficient_runs": "必要な出走数に満たない",
    "insufficient_competitions": "必要な大会数に満たない",
    "insufficient_dates": "必要な異なる出走日数に満たない",
    "competition_id_missing": "大会IDがなく同一大会の照合根拠がない",
    "ambiguous_order": "直近N出走の選択境界に同日で順序不明の出走がある",
    "pending_duplicate_review": "二重掲載疑いが未解決（件数・分布が水増しされる恐れ）",
    "window_empty": "窓と観測期間の共通範囲がない",
    "input_null": "参照する特徴量が null",
    "nonpositive_base": "基準値が正でない",
    "cutoff_before_hs": "締切が高校観測期間より前",
    "no_ekiden_leg": "対象の駅伝の本人区間が見つからない（出場していない・未掲載を区別しない）",
    "no_ranked_leg": "本人区間はあるが区間順位がない",
}


@dataclass
class FeatureValue:
    feature_ref: str
    value: Optional[float]
    unit: str
    reason: str = "ok"
    evidence: list[str] = field(default_factory=list)
    evidence_count: int = 0
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "feature_ref": self.feature_ref, "value": self.value, "unit": self.unit,
            "reason": self.reason, "evidence": self.evidence,
            "evidence_count": self.evidence_count, "period_start": self.period_start,
            "period_end": self.period_end, "note": self.note,
        }


@dataclass
class PersonContext:
    athlete: Athlete
    cutoff: Optional[date]
    hs: Optional[Window]
    dataset: Dataset
    options: Options
    _runs: dict[str, tuple[list[EligibleRun], list[RowDecision]]] = field(default_factory=dict)

    def runs(self, event: str, junior: bool = False) -> tuple[list[EligibleRun], list[RowDecision]]:
        """junior=True なら観測の下限を中1の4月1日まで広げる（中学期間の窓用）。"""
        key = f"{event}:junior" if junior else event
        if key not in self._runs:
            assert self.cutoff is not None and self.hs is not None
            lower = Window(junior_window(self.athlete.hs_entry_fiscal_year).start, self.cutoff) if junior else self.hs
            self._runs[key] = select_runs(
                self.dataset, self.athlete.person_id, event, self.cutoff, lower, self.options)
        return self._runs[key]


def quantile_linear(sorted_vals: list[float], q: float) -> float:
    """ソート済み配列の位置 (n-1)*q を線形補間する方式（固定）。"""
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _resolve_window(spec_w: dict, ctx: PersonContext) -> Optional[Window]:
    assert ctx.hs is not None and ctx.cutoff is not None
    kind = spec_w["kind"]
    if kind == "hs":
        return ctx.hs
    if kind == "recent_days":
        return recent_window(ctx.cutoff, spec_w["days"]).intersect(ctx.hs)
    if kind == "grade":
        return grade_window(ctx.athlete.hs_entry_fiscal_year, spec_w["grade"]).intersect(ctx.hs)
    if kind == "junior":
        return junior_window(ctx.athlete.hs_entry_fiscal_year)
    if kind == "junior_grade":
        return junior_grade_window(ctx.athlete.hs_entry_fiscal_year, spec_w["grade"])
    raise ValueError(kind)


def _ekiden(defn: FeatureDefinition, ctx: PersonContext, window: Window, fv: "FeatureValue") -> "FeatureValue":
    spec = defn.spec
    race = spec["race"]
    rows = sorted((e for e in ctx.dataset.ekiden_of(ctx.athlete.person_id)
                   if window.contains(e.run_date) and e.run_date <= ctx.cutoff
                   and (race == "any" or e.race_class == race)),
                  key=lambda e: (e.run_date, e.key.as_str()))
    if spec["op"] == "ekiden_count":
        if ctx.athlete.coverage != COVERAGE_FETCHED:
            fv.reason = "coverage_unknown"
            return fv
        fv.evidence = [e.key.as_str() for e in rows]
        fv.evidence_count = len(rows)
        fv.value = float(len(rows))
        fv.note = "観測できた本人区間の数（出場機会は学校・地域で違う）"
        return fv
    if not rows:
        fv.reason = "no_ekiden_leg"
        return fv
    ranked = [e for e in rows if e.leg_rank is not None]
    if not ranked:
        fv.reason = "no_ranked_leg"
        fv.evidence = [e.key.as_str() for e in rows]
        return fv
    best = min(ranked, key=lambda e: (e.leg_rank, e.run_date))
    fv.evidence = [best.key.as_str()]
    fv.evidence_count = 1
    fv.value = float(best.leg_rank)
    fv.note = f"{len(ranked)}区間中の最高（{best.run_date} {best.leg}区）"
    return fv


def _order_known(group: list[EligibleRun]) -> bool:
    if len(group) <= 1:
        return True
    if all(g.start_time for g in group) and len({g.start_time for g in group}) == len(group):
        return True
    if all(g.round_order is not None for g in group) and \
            len({g.round_order for g in group}) == len(group):
        return True
    return False


def _sort_key(r: EligibleRun):
    return (r.run_date, r.start_time or "", r.round_order if r.round_order is not None else 0)


def compute_one(defn: FeatureDefinition, ctx: PersonContext,
                computed: dict[str, FeatureValue]) -> FeatureValue:
    spec = defn.spec
    op = spec["op"]
    fv = FeatureValue(defn.ref, None, defn.unit)

    if op in ("diff", "pct_change"):
        a, b = (computed.get(ref) for ref in spec["inputs"])
        if a is None or b is None or a.value is None or b.value is None:
            inner = next((x.reason for x in (a, b) if x is not None and x.value is None), "")
            fv.reason = "input_null"
            fv.note = f"参照先の理由: {inner}" if inner else ""
            return fv
        fv.evidence = sorted(set(a.evidence) | set(b.evidence))
        fv.evidence_count = len(fv.evidence)
        fv.period_start, fv.period_end = a.period_start, b.period_end
        fv.note = (f"比較元 {a.evidence_count}件（〜{a.period_end}）/ "
                   f"比較先 {b.evidence_count}件（〜{b.period_end}）")
        if ctx.cutoff and (ctx.cutoff.month, ctx.cutoff.day) != (3, 31):
            fv.note += "。締切が年度末でないため比較期間の長さが異なる"
        if op == "diff":
            fv.value = round(a.value - b.value, 3)
        else:
            if a.value <= 0:
                fv.reason = "nonpositive_base"
                return fv
            fv.value = round(100.0 * (a.value - b.value) / a.value, 4)
        return fv

    if ctx.athlete.hs_entry_fiscal_year is None:
        fv.reason = "hs_entry_year_unknown"
        return fv
    if ctx.hs is None:
        fv.reason = "cutoff_before_hs"
        return fv
    window = _resolve_window(spec["window"], ctx)
    if window is None:
        fv.reason = "window_empty"
        return fv
    fv.period_start, fv.period_end = window.start.isoformat(), window.end.isoformat()
    if op in EKIDEN_OPS:
        return _ekiden(defn, ctx, window, fv)

    all_runs, _ = ctx.runs(spec["event"], junior=spec["window"]["kind"].startswith("junior"))
    in_window = [r for r in all_runs if window.contains(r.run_date)]

    if op in DUP_SENSITIVE_OPS and any(r.duplicate_suspect for r in in_window):
        fv.reason = "pending_duplicate_review"
        fv.evidence = [r.key.as_str() for r in in_window if r.duplicate_suspect]
        return fv

    def use(rows: list[EligibleRun]) -> None:
        fv.evidence = [r.key.as_str() for r in rows]
        fv.evidence_count = len(rows)

    min_n = spec.get("min_n", 1)

    if op == "count":
        if ctx.athlete.coverage != COVERAGE_FETCHED:
            fv.reason = "coverage_unknown"
            return fv
        use(in_window)
        fv.value = float(len(in_window))
        fv.note = "観測できた有効出走数（出走機会・完全な出走数ではない）"
        return fv

    if op not in ("pb_updates", "median_gap") and (len(in_window) < min_n or not in_window):
        fv.reason = "insufficient_runs"
        use(in_window)
        return fv

    if op == "span_days":
        use(in_window)
        fv.value = float((in_window[-1].run_date - in_window[0].run_date).days)
        fv.note = f"{in_window[0].run_date}〜{in_window[-1].run_date}"
    elif op == "days_since_last":
        use([in_window[-1]])
        fv.value = float((ctx.cutoff - in_window[-1].run_date).days)
        fv.note = f"最終観測日 {in_window[-1].run_date}"
    elif op == "min":
        best = min(in_window, key=lambda r: (r.seconds, r.run_date))
        use([best])
        fv.value = best.seconds
        fv.note = f"{len(in_window)}件中の最小（{best.run_date}）"
    elif op == "median_latest_n":
        n = spec["n"]
        if len(in_window) < n:
            fv.reason = "insufficient_runs"
            use(in_window)
            return fv
        ordered = sorted(in_window, key=_sort_key)
        cut = len(ordered) - n
        boundary_date = ordered[cut].run_date
        same_day = [r for r in ordered if r.run_date == boundary_date]
        straddles = cut > 0 and ordered[cut - 1].run_date == boundary_date
        if straddles and not _order_known(same_day):
            fv.reason = "ambiguous_order"
            use(same_day)
            return fv
        chosen = ordered[cut:]
        use(chosen)
        fv.value = round(median([r.seconds for r in chosen]), 3)
        fv.note = f"直近{n}出走 {chosen[0].run_date}〜{chosen[-1].run_date}（一定日数内の値ではない）"
    elif op == "iqr":
        if any(r.competition_id is None for r in in_window):
            fv.reason = "competition_id_missing"
            use(in_window)
            return fv
        if len({r.competition_id for r in in_window}) < spec.get("min_competitions", 1):
            fv.reason = "insufficient_competitions"
            use(in_window)
            return fv
        vals = sorted(r.seconds for r in in_window)
        use(in_window)
        fv.value = round(quantile_linear(vals, 0.75) - quantile_linear(vals, 0.25), 3)
        fv.note = f"{len(vals)}件・{len({r.competition_id for r in in_window})}大会。安定性の記述であり精神力等ではない"
    elif op == "pb_updates":
        # H全体を日付順に進み、窓より前の結果も基準に使う。
        if not all_runs:
            fv.reason = "insufficient_runs"
            return fv
        by_day: dict[date, float] = {}
        rows_by_day: dict[date, EligibleRun] = {}
        for r in all_runs:
            if r.run_date not in by_day or r.seconds < by_day[r.run_date]:
                by_day[r.run_date] = r.seconds
                rows_by_day[r.run_date] = r
        best: Optional[float] = None
        updates: list[EligibleRun] = []
        for d in sorted(by_day):
            v = by_day[d]
            if best is None:
                best = v  # 最初の観測日は基準（更新に数えない）
                continue
            if v < best:
                best = v
                if window.contains(d):
                    updates.append(rows_by_day[d])
        use(updates)
        fv.value = float(len(updates))
        fv.note = "高校観測期間の最良記録を窓内で更新した日数（真の生涯PB更新回数ではない）"
    elif op == "median_gap":
        dates = sorted({r.run_date for r in in_window})
        if len(dates) < spec.get("min_dates", 3):
            fv.reason = "insufficient_dates"
            use(in_window)
            return fv
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        use(in_window)
        fv.value = float(median(gaps))
        fv.note = f"異なる出走日 {len(dates)}日の隣接間隔（大会間隔・練習頻度ではない）"
    else:  # pragma: no cover - validate_spec で弾かれる
        raise ValueError(op)
    return fv


def topo_order(defs: list[FeatureDefinition]) -> list[FeatureDefinition]:
    by_ref = {d.ref: d for d in defs}
    out: list[FeatureDefinition] = []
    seen: set[str] = set()

    def visit(d: FeatureDefinition, stack: tuple = ()) -> None:
        if d.ref in seen:
            return
        if d.ref in stack:
            raise ValueError(f"循環参照: {d.ref}")
        for ref in d.spec.get("inputs", []):
            if ref not in by_ref:
                raise ValueError(f"{d.ref} の参照先 {ref} が計算対象に含まれていません")
            visit(by_ref[ref], stack + (d.ref,))
        seen.add(d.ref)
        out.append(d)

    for d in defs:
        visit(d)
    return out


def make_context(ds: Dataset, athlete: Athlete, cutoff_rule, options: Options) -> PersonContext:
    cutoff = hs = None
    if athlete.hs_entry_fiscal_year is not None:
        cutoff = cutoff_rule.resolve(athlete.hs_entry_fiscal_year)
        hs = hs_window(athlete.hs_entry_fiscal_year, cutoff)
    return PersonContext(athlete, cutoff, hs, ds, options)


def compute_person(ds: Dataset, athlete: Athlete, defs: list[FeatureDefinition],
                   cutoff_rule, options: Options = Options()) -> list[FeatureValue]:
    ctx = make_context(ds, athlete, cutoff_rule, options)
    computed: dict[str, FeatureValue] = {}
    for d in topo_order(defs):
        computed[d.ref] = compute_one(d, ctx, computed)
    return [computed[d.ref] for d in defs]
