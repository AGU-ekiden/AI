"""年度・学年・観測締切。日本の年度は4月1日始まり。日付はすべて日本時間の暦日。

学年は「高校入学年度」からのみ導く。年齢・生年月日・現在の所属からは補完しない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


def fiscal_year_of(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def fiscal_year_start(fy: int) -> date:
    return date(fy, 4, 1)


def fiscal_year_end(fy: int) -> date:
    return date(fy + 1, 3, 31)


@dataclass(frozen=True)
class CutoffRule:
    """観測締切の規則。grade=2, month=3, day=31 なら「高2の年度末」。

    月日は高校の当該学年年度の中の日付として解釈する（4〜12月は年度の年、1〜3月は翌年）。
    """
    grade: int = 2
    month: int = 3
    day: int = 31
    label: str = "高2年度末（3月31日終了時点・日本時間）"

    def resolve(self, hs_entry_fy: int) -> date:
        fy = hs_entry_fy + (self.grade - 1)
        year = fy if self.month >= 4 else fy + 1
        return date(year, self.month, self.day)


CUTOFF_PRESETS = {
    "g2_aug31": CutoffRule(2, 8, 31, "高2の8月31日終了時点（日本時間）"),
    "g2_jul31": CutoffRule(2, 7, 31, "高2の7月31日終了時点（日本時間）"),
    "g2_end": CutoffRule(2, 3, 31, "高2年度末（3月31日終了時点・日本時間）"),
}
# 利用者決定（2026-10-18）：主観測点は高2の8月31日終了時点（インターハイを含めるため）
DEFAULT_CUTOFF = "g2_aug31"


@dataclass(frozen=True)
class Window:
    start: date
    end: date

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    def intersect(self, other: "Window") -> Optional["Window"]:
        s, e = max(self.start, other.start), min(self.end, other.end)
        return Window(s, e) if s <= e else None


def hs_window(hs_entry_fy: int, cutoff: date) -> Optional[Window]:
    """H：高1の4月1日から締切日まで。"""
    s = fiscal_year_start(hs_entry_fy)
    return Window(s, cutoff) if s <= cutoff else None


def recent_window(cutoff: date, days: int) -> Window:
    """直近N日窓：C-(N-1)日 から C まで（両端含む）。"""
    return Window(cutoff - timedelta(days=days - 1), cutoff)


def grade_window(hs_entry_fy: int, grade: int) -> Window:
    fy = hs_entry_fy + grade - 1
    return Window(fiscal_year_start(fy), fiscal_year_end(fy))


def junior_window(hs_entry_fy: int) -> Window:
    """J：中1の4月1日〜中3の3月31日（高校入学年度の前の3年度）。浪人・飛び級は想定しない。"""
    return Window(fiscal_year_start(hs_entry_fy - 3), fiscal_year_end(hs_entry_fy - 1))


def junior_grade_window(hs_entry_fy: int, grade: int) -> Window:
    fy = hs_entry_fy - 4 + grade
    return Window(fiscal_year_start(fy), fiscal_year_end(fy))
