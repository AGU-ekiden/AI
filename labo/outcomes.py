"""成果ラベル（研究評価用）。特徴量計算・母集団選定には一切渡さない。

利用者決定（2026-10-18）：箱根駅伝で「往路（1〜5区）区間5位以内」または
「復路（6〜10区）区間2位以内」を1回以上。二つの構成要素は別々にも保持し、独自の合成点は作らない。

実在選手への予測は行わない。このモジュールは過去世代のラベル付け（集計レベルの検証用）のみ。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional

from .model import IDENTITY_CONFIRMED

POSITIVE = "positive"
NEGATIVE_CONFIRMED = "negative_confirmed"
TRACKING = "tracking"
UNKNOWN = "unknown"
LABEL_TEXT = {
    POSITIVE: "達成", NEGATIVE_CONFIRMED: "追跡完了・未達成（根拠あり）",
    TRACKING: "追跡中（0扱いしない）", UNKNOWN: "不明（データ未確認。0扱いしない）",
}


@dataclass(frozen=True)
class OutcomeDefinition:
    outcome_id: str = "hakone_leg_top"
    version: int = 1
    outbound_legs: tuple[int, ...] = (1, 2, 3, 4, 5)
    outbound_max_rank: int = 5
    return_legs: tuple[int, ...] = (6, 7, 8, 9, 10)
    return_max_rank: int = 2
    # 追跡期間：高校入学年度E → 大学1年相当の年度 E+3 から max_editions 大会分（既定4回）
    first_edition_offset_fy: int = 3
    max_editions: int = 4
    decided_by: str = "利用者（2026-10-18 チャットで決定）"
    note: str = ("区間順位は公式順位のみ。オープン参加等の参考記録は達成に数えず別記。"
                 "浪人・休学等で在学時期がずれる人は追跡期間外になりうる（要確認事項）。"
                 "学校の出場資格・選手起用・進学先の影響を受けるため、未達成は能力不足を意味しない。")

    @property
    def ref(self) -> str:
        return f"{self.outcome_id}@{self.version}"

    def edition_fys(self, hs_entry_fy: int) -> list[int]:
        """追跡対象の大会の年度（1月開催の大会は前年4月始まりの年度に属する）。"""
        start = hs_entry_fy + self.first_edition_offset_fy
        return list(range(start, start + self.max_editions))


@dataclass(frozen=True)
class HakoneLegResult:
    person_id: str
    edition_fy: int            # 大会が属する年度（例：2026年1月開催 → 2025年度）
    race_date: date
    leg: int                   # 1〜10
    official_rank: Optional[int]  # 公式区間順位。参考記録・不明は None
    reference_only: bool = False  # オープン参加等の参考記録
    identity: str = IDENTITY_CONFIRMED
    source_ref: str = ""


@dataclass
class OutcomeLabel:
    person_id: str
    outcome_ref: str
    label: str
    outbound_top: Optional[bool]
    return_top: Optional[bool]
    evidence: list[str] = field(default_factory=list)
    tracking_editions: list[int] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self) | {"label_text": LABEL_TEXT[self.label]}


def label_person(
    person_id: str, hs_entry_fy: Optional[int], legs: list[HakoneLegResult], *,
    definition: OutcomeDefinition, as_of: date, complete_editions: set[int],
    linkage_checked: bool,
) -> OutcomeLabel:
    """
    complete_editions: 公式区間順位が全区間・全走者そろって取り込み済みの大会年度
    linkage_checked: この人物と箱根の結果の照合（出場の有無を含む）を人が確認済みか
    """
    ref = definition.ref
    if hs_entry_fy is None:
        return OutcomeLabel(person_id, ref, UNKNOWN, None, None, reason="hs_entry_year_unknown")
    editions = definition.edition_fys(hs_entry_fy)
    mine = [lg for lg in legs if lg.person_id == person_id and lg.edition_fy in editions
            and lg.race_date <= as_of]

    def hit(lg: HakoneLegResult) -> Optional[str]:
        if lg.identity != IDENTITY_CONFIRMED or lg.reference_only or lg.official_rank is None:
            return None
        if lg.leg in definition.outbound_legs and lg.official_rank <= definition.outbound_max_rank:
            return "outbound"
        if lg.leg in definition.return_legs and lg.official_rank <= definition.return_max_rank:
            return "return"
        return None

    hits = [(lg, hit(lg)) for lg in mine]
    outbound = any(k == "outbound" for _, k in hits)
    ret = any(k == "return" for _, k in hits)
    evidence = [lg.source_ref for lg, k in hits if k]
    if outbound or ret:
        return OutcomeLabel(person_id, ref, POSITIVE, outbound, ret, evidence, editions)

    # 最終対象大会が as_of 時点で未開催（またはその年度が終わっていない）なら追跡中
    last_fy = editions[-1]
    if as_of <= date(last_fy + 1, 3, 31):
        return OutcomeLabel(person_id, ref, TRACKING, None, None, [], editions,
                            "追跡期間が終わっていない")
    pending = [lg.source_ref for lg in mine if lg.identity != IDENTITY_CONFIRMED]
    reference = [lg.source_ref for lg in mine if lg.reference_only]
    missing = [fy for fy in editions if fy not in complete_editions]
    if pending:
        return OutcomeLabel(person_id, ref, UNKNOWN, None, None, pending, editions, "本人未確認の区間記録がある")
    if missing:
        return OutcomeLabel(person_id, ref, UNKNOWN, None, None, [], editions,
                            f"区間順位が未取り込みの大会年度: {missing}")
    if not linkage_checked:
        return OutcomeLabel(person_id, ref, UNKNOWN, None, None, [], editions,
                            "人物と箱根結果の照合が未確認（見つからないだけでは未達成にしない）")
    return OutcomeLabel(person_id, ref, NEGATIVE_CONFIRMED, False, False, reference, editions,
                        "参考記録のみあり" if reference else "")
