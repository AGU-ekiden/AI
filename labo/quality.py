"""行単位の適格判定。原本を変えず、採用・除外・保留とその理由を返す。

- validation_status=raw_only は除外理由にしない（原本保存の状態であり記録の不適格ではない）。
- 一方、行単位確認（row_checked）がない行は無条件には採用しない。
- 複数日大会で実施日不明かつ期間が締切をまたぐものは保留。初日を実施日と見なさない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .model import (
    IDENTITY_CONFIRMED, NON_INDIVIDUAL_GROUPS, STATUS_OK, Dataset, Result, ResultKey,
)
from .periods import Window

# 種目別の数値妥当性の範囲（秒）。範囲外は「単位異常の疑い」で保留。
PLAUSIBLE_RANGE_S = {
    "1500m": (210.0, 480.0),
    "3000m": (450.0, 1080.0),
    "3000mSC": (480.0, 1200.0),
    "5000m": (750.0, 1800.0),
}

# 保留（人の確認が必要）に分類する理由
HOLD_REASONS = {
    "date_spans_cutoff", "implausible_value", "identity_unconfirmed",
    "row_unverified", "performed_date_unknown", "date_unknown", "format_unknown",
}

REASON_LABELS = {
    "non_individual_parent": "駅伝・チーム・リレーの親レコード（チーム合計の可能性）",
    "identity_unconfirmed": "本人未確認",
    "DNS": "DNS（出走せず）",
    "DNF": "DNF（途中棄権）",
    "DSQ": "DSQ（失格）",
    "blank": "記録欄が空欄",
    "not_fetched": "未取得",
    "fetch_failed": "取得失敗",
    "format_unknown": "形式不明",
    "out_of_scope": "対象外",
    "nonpositive_time": "正の数値タイムでない",
    "implausible_value": "数値が妥当範囲外（単位異常の疑い）",
    "row_unverified": "行単位の確認が未了（原本の存在だけでは採用しない）",
    "date_unknown": "日付不明",
    "performed_date_unknown": "複数日大会で実施日が未確認",
    "date_spans_cutoff": "大会期間が締切をまたぎ実施日不明（保留）",
    "after_cutoff": "締切より後の実施",
    "before_hs_window": "高校観測期間より前",
    "publication_unknown": "公表日不明（厳密な当時再現モード）",
    "published_after_cutoff": "締切後に公表（厳密な当時再現モード）",
    "merged_duplicate": "証拠に基づき同一結果として統合（代表行のみ使用）",
}


@dataclass(frozen=True)
class EligibleRun:
    key: ResultKey
    run_date: date
    seconds: float
    competition_id: Optional[str]
    round_order: Optional[int]
    start_time: Optional[str]
    duplicate_suspect: bool


@dataclass(frozen=True)
class RowDecision:
    key: ResultKey
    decision: str  # "used" / "excluded" / "held"
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class Options:
    require_published_by_cutoff: bool = False


def _performed_date(r: Result, cutoff: date) -> tuple[Optional[date], Optional[str]]:
    if r.performed_date is not None:
        return r.performed_date, None
    if r.competition_start is None:
        return None, "date_unknown"
    if r.competition_end is not None and r.competition_end == r.competition_start:
        return r.competition_start, None  # 1日開催
    # 複数日 or 期間不明。初日を実施日と見なさない。
    if r.competition_start > cutoff:
        return None, "after_cutoff"
    end = r.competition_end
    if end is None:
        return None, "performed_date_unknown"  # 期間自体が不明
    if end > cutoff:
        return None, "date_spans_cutoff"
    return None, "performed_date_unknown"


def select_runs(
    ds: Dataset, person_id: str, event_code: str, cutoff: date, hs: Optional[Window],
    options: Options = Options(),
) -> tuple[list[EligibleRun], list[RowDecision]]:
    """本人・種目・締切・観測期間で有効な個人走を選ぶ。全行の判定を返す。"""
    merged = {link.duplicate: link for link in ds.duplicate_links
              if link.duplicate.person_id == person_id}
    used: list[EligibleRun] = []
    decisions: list[RowDecision] = []
    for r in ds.results_of(person_id):
        if r.event_code != event_code:
            continue
        def dec(kind: str, reason: str, detail: str = "") -> None:
            decisions.append(RowDecision(r.key, kind, reason, detail))
        if r.event_group in NON_INDIVIDUAL_GROUPS:
            dec("excluded", "non_individual_parent"); continue
        if r.key in merged:
            dec("excluded", "merged_duplicate", merged[r.key].canonical.as_str()); continue
        if r.identity != IDENTITY_CONFIRMED:
            dec("held", "identity_unconfirmed"); continue
        if r.status != STATUS_OK:
            dec("excluded" if r.status not in HOLD_REASONS else "held", r.status); continue
        if r.seconds is None or r.seconds <= 0:
            dec("excluded", "nonpositive_time"); continue
        lo_hi = PLAUSIBLE_RANGE_S.get(event_code)
        if lo_hi and not (lo_hi[0] <= r.seconds <= lo_hi[1]):
            dec("held", "implausible_value", f"{r.seconds}s"); continue
        if not r.row_checked:
            dec("held", "row_unverified"); continue
        d, why = _performed_date(r, cutoff)
        if d is None:
            dec("held" if why in HOLD_REASONS else "excluded", why or "date_unknown"); continue
        if d > cutoff:
            dec("excluded", "after_cutoff"); continue
        if hs is None or d < hs.start:
            dec("excluded", "before_hs_window"); continue
        if options.require_published_by_cutoff:
            if r.first_available_at is None:
                dec("excluded", "publication_unknown"); continue
            if r.first_available_at > cutoff:
                dec("excluded", "published_after_cutoff"); continue
        used.append(EligibleRun(r.key, d, r.seconds, r.competition_id, r.round_order,
                                r.start_time, r.duplicate_suspect))
        dec("used", "ok")
    used.sort(key=lambda x: (x.run_date, x.key.as_str()))
    return used, decisions
