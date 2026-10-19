"""成果ラベル（研究評価用）。特徴量計算・母集団選定には一切渡さない。

利用者決定（2026-10-18）：箱根駅伝で「往路（1〜5区）区間5位以内」または
「復路（6〜10区）区間2位以内」を1回以上。二つの構成要素は別々にも保持し、独自の合成点は作らない。
利用者決定（2026-10-19）：追跡期間は既定どおり。学生連合（オープン参加）も含める → v2。
利用者決定（2026-10-19・後）：分かりにくいため、区間順位の扱いから学生連合を除く → v3。
  学生連合としての区間記録は達成に数えず、それしかない人は「不明」（未達成と確定しない）。

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
    version: int = 3
    outbound_legs: tuple[int, ...] = (1, 2, 3, 4, 5)
    outbound_max_rank: int = 5
    return_legs: tuple[int, ...] = (6, 7, 8, 9, 10)
    return_max_rank: int = 2
    # 追跡期間：高校入学年度E → 大学1年相当の年度 E+3 から max_editions 大会分（既定4回）
    first_edition_offset_fy: int = 3
    max_editions: int = 4
    # 学生連合など参考記録の走者を含めるか（v1・v3=含めない、v2=相当順位で含める）
    include_reference: bool = False
    # 含めない場合、参考記録しかない人を「不明」にするか（v3=する、v1=しない＝未達成扱い）
    reference_makes_unknown: bool = True
    decided_by: str = "利用者（2026-10-18・10-19 チャットで決定）"
    note: str = ("区間順位は公式順位のみ。学生連合（参考記録）の区間は扱いから除き、"
                 "それしかない人は不明とする（v3）。"
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
    reference_only: bool = False  # 学生連合などオープン参加の参考記録
    reference_rank: Optional[int] = None  # 参考記録の相当順位（公式順位表に当てはめた順位）
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

    def rank_of(lg: HakoneLegResult) -> Optional[int]:
        if lg.reference_only:
            return lg.reference_rank if definition.include_reference else None
        return lg.official_rank

    def hit(lg: HakoneLegResult) -> Optional[str]:
        rank = rank_of(lg)
        if lg.identity != IDENTITY_CONFIRMED or rank is None:
            return None
        if lg.leg in definition.outbound_legs and rank <= definition.outbound_max_rank:
            return "outbound"
        if lg.leg in definition.return_legs and rank <= definition.return_max_rank:
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
    if definition.include_reference:
        no_rank = [lg.source_ref for lg in mine if lg.reference_only and lg.reference_rank is None]
        if no_rank:
            return OutcomeLabel(person_id, ref, UNKNOWN, None, None, no_rank, editions,
                                "学生連合等の区間記録の相当順位が未確認")
    missing = [fy for fy in editions if fy not in complete_editions]
    if reference and not definition.include_reference and definition.reference_makes_unknown:
        return OutcomeLabel(person_id, ref, UNKNOWN, None, None, reference, editions,
                            "学生連合（参考記録）の区間のみ。区間順位の扱いから除外")
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
