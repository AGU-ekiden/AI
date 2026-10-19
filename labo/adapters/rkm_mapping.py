"""rkm の値 → 研究用モデル（labo.model）への対応。確定したものだけをここに置く。

確定の根拠は docs/decisions.md と docs/audit_baseline.md。
"""
from __future__ import annotations

from typing import Optional

from ..model import (
    STATUS_BLANK, STATUS_DNF, STATUS_DNS, STATUS_DSQ, STATUS_NO_MARK, STATUS_OK, STATUS_UNCONFIRMED,
)

# records.status の対応（2026-10-19 監査第1回の語彙。NM/NI/DNE は利用者決定で「記録なし」）
STATUS_MAP: dict[Optional[str], str] = {
    None: STATUS_OK,          # 状態なし＝記録あり（mark_value の妥当性は別途判定）
    "DNS": STATUS_DNS,
    "DNF": STATUS_DNF,
    "DQ": STATUS_DSQ,
    "DSQ": STATUS_DSQ,
    "NM": STATUS_NO_MARK,
    "NI": STATUS_NO_MARK,
    "DNE": STATUS_NO_MARK,
}


def map_status(raw: Optional[str]) -> str:
    """未知の状態（例：「競走中止」）は推測で DNF 等にせず、確認待ちとして返す。"""
    if raw is not None and raw.strip() == "":
        return STATUS_BLANK
    return STATUS_MAP.get(raw, STATUS_UNCONFIRMED)


# 個人の5000m：種目名とトラック区分で判定（distance_m では 5km ロード・5000m 競歩が混ざるため使わない）
EVENT_MAP: dict[tuple[str, str], str] = {
    ("5000m", "track"): "5000m",
    ("1500m", "track"): "1500m",
    ("3000m", "track"): "3000m",
    ("3000mSC(91.4cm)", "track"): "3000mSC",
}


def map_event(event: Optional[str], event_group: Optional[str]) -> Optional[str]:
    return EVENT_MAP.get((event or "", event_group or ""))
