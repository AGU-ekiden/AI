"""駅伝の本人区間（フェーズ2候補の最小実装）。

本人タイムは is_self が確認できた区間の leg_value のみ。pass_value（通過の累積時間）は使わない。
同一人物が同一レコードの複数区間に現れる場合は一つを選ばず曖昧として返す。
"""
from __future__ import annotations

from typing import Optional

from .model import EkidenLeg, ResultKey


def self_leg(legs: list[EkidenLeg], key: ResultKey) -> tuple[Optional[EkidenLeg], str]:
    mine = [lg for lg in legs if lg.key == key and lg.is_self is True]
    if not mine:
        unknown = [lg for lg in legs if lg.key == key and lg.is_self is None]
        return None, "self_leg_unknown" if unknown else "no_self_leg"
    if len(mine) > 1:
        return None, "ambiguous_multiple_self_legs"
    if mine[0].leg_value is None or mine[0].leg_value <= 0:
        return None, "leg_time_missing"
    return mine[0], "ok"


def leg_pace_s_per_km(leg: EkidenLeg) -> tuple[Optional[float], str]:
    if leg.leg_distance_m is None or leg.leg_distance_m <= 0:
        return None, "leg_distance_unknown"
    if leg.leg_value is None or leg.leg_value <= 0:
        return None, "leg_time_missing"
    return round(leg.leg_value / (leg.leg_distance_m / 1000.0), 3), "ok"
