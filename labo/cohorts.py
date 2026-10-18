"""研究用母集団の定義（版管理）。

選定条件は観測締切時点で確認可能だった情報のみ。進学先・箱根結果・高3の全国出場など
締切後の情報を使う条件はホワイトリストに存在しない。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .model import IDENTITY_CONFIRMED, NON_INDIVIDUAL_GROUPS, STATUS_OK, Athlete, Dataset
from .periods import CutoffRule

ALLOWED_CRITERIA = {"hs_entry_fy_range", "national_by_cutoff"}


@dataclass
class CohortDefinition:
    cohort_id: str
    version: int
    label: str
    description: str
    criteria: dict = field(default_factory=dict)
    generalization_note: str = ("全国大会出場者等を経由して収集された集団での研究。"
                                "全高校生へ一般化しない。")

    @property
    def ref(self) -> str:
        return f"{self.cohort_id}@{self.version}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ref"] = self.ref
        return d


def validate_criteria(criteria: dict) -> dict:
    extra = set(criteria) - ALLOWED_CRITERIA
    if extra:
        raise ValueError(f"許可されていない選定条件: {sorted(extra)}（締切後情報は使えません）")
    out = {}
    if "hs_entry_fy_range" in criteria:
        lo, hi = criteria["hs_entry_fy_range"]
        if not (type(lo) is int and type(hi) is int and 1990 <= lo <= hi <= 2100):
            raise ValueError("hs_entry_fy_range は [開始年度, 終了年度]")
        out["hs_entry_fy_range"] = [lo, hi]
    if "national_by_cutoff" in criteria:
        if criteria["national_by_cutoff"] is not True:
            raise ValueError("national_by_cutoff は true のみ")
        out["national_by_cutoff"] = True
    return out


def builtin_cohorts() -> list[CohortDefinition]:
    return [
        CohortDefinition("all_with_entry_year", 1, "収集済み全員（入学年度判明者）",
                         "入学年度の根拠がある人物。収集経路による選択バイアスを含む。", {}),
        CohortDefinition("national_by_cutoff", 1, "締切までに全国大会出場が確認できた集団",
                         "観測締切以前に実施が確認できる全国大会結果がある人物のみ。"
                         "高3で初出場した人は高2時点の集団に入らない。",
                         {"national_by_cutoff": True}),
    ]


def evaluate(cohort: CohortDefinition, ds: Dataset, athlete: Athlete,
             rule: CutoffRule) -> tuple[bool, str]:
    """(対象か, 除外理由)。"""
    if athlete.hs_entry_fiscal_year is None:
        return False, "hs_entry_year_unknown"
    c = cohort.criteria
    if "hs_entry_fy_range" in c:
        lo, hi = c["hs_entry_fy_range"]
        if not lo <= athlete.hs_entry_fiscal_year <= hi:
            return False, "hs_entry_fy_out_of_range"
    if c.get("national_by_cutoff"):
        cutoff = rule.resolve(athlete.hs_entry_fiscal_year)
        ok = False
        for r in ds.results_of(athlete.person_id):
            if r.competition_id not in ds.competitions_national:
                continue
            if r.identity != IDENTITY_CONFIRMED or r.status != STATUS_OK:
                continue
            d = r.performed_date or (r.competition_start if r.competition_start
                                     and r.competition_end == r.competition_start else None)
            if d is None and r.event_group in NON_INDIVIDUAL_GROUPS:
                # 駅伝は大会期間全体が締切以前なら出場確認として扱える
                if r.competition_end and r.competition_end <= cutoff:
                    d = r.competition_end
            if d is not None and d <= cutoff:
                ok = True
                break
        if not ok:
            return False, "no_national_by_cutoff"
    return True, ""
