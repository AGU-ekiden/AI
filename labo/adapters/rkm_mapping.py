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


# ---- 日付（利用者決定 2026-10-19）：records.date は「その種目を実際に走った日」 ----
def parse_date(raw: Optional[str]):
    """'2021-07-30' '2021/7/30' '2021.07.30' を date に。解釈できなければ None（推測しない）。"""
    import re
    from datetime import date
    if not raw:
        return None
    m = re.match(r"^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\s*$", raw)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---- 学年（利用者決定 2026-10-19）：grade_raw はレース時点の学年。「2+」は2年 ----
def parse_grade(raw: Optional[str]) -> Optional[int]:
    import re
    import unicodedata
    if not raw:
        return None
    s = unicodedata.normalize("NFKC", raw).strip()
    m = re.match(r"^(?:高校?)?\s*([1-3])\s*(?:年生?)?\s*\+?$", s)
    return int(m.group(1)) if m else None


def school_level(affiliation_raw: Optional[str]) -> Optional[str]:
    """所属名から学校段階を判定（陸マガの略称「○○高」「○○大」を想定）。不明は None。
    第2回監査の語彙で確認するまでは暫定。"""
    import re
    if not affiliation_raw:
        return None
    s = affiliation_raw.strip()
    if re.search(r"(高等学校|高校|高)$", s):
        return "high"
    if re.search(r"(大学|大)$", s):
        return "univ"
    if re.search(r"(中学校|中学|中)$", s):
        return "junior"
    return None


def infer_hs_entry_fy(rows) -> tuple[Optional[int], str, int]:
    """rows: (race_date, grade_raw, affiliation_raw) の並び。
    高校所属のレースの「年度 −（学年−1）」がすべて一致したときだけ入学年度とする。
    戻り値 (入学年度, 理由, 根拠件数)。食い違いは推測で選ばず None。"""
    from ..periods import fiscal_year_of
    found: dict[int, int] = {}
    for d, grade_raw, aff in rows:
        g = parse_grade(grade_raw)
        if d is None or g is None or school_level(aff) != "high":
            continue
        fy = fiscal_year_of(d) - (g - 1)
        found[fy] = found.get(fy, 0) + 1
    if not found:
        return None, "no_high_school_grade", 0
    if len(found) > 1:
        return None, "conflicting_grades", sum(found.values())
    fy, n = next(iter(found.items()))
    return fy, "derived_from_grade", n


# ---- 複数プロフィールの重複（利用者決定 2026-10-19）：同一人物・同日・同種目・同記録表記は1つにまとめる ----
def build_duplicate_links(results) -> list:
    """labo.model.Result の並びから DuplicateLink を作る。代表は profile_id/record_id の辞書順で最小（決定的）。
    同じプロフィール内の同日同記録（予選・決勝が同タイム等）はまとめない。"""
    from ..model import DuplicateLink
    groups: dict[tuple, list] = {}
    for r in results:
        if r.status != STATUS_OK or not r.mark_raw or r.performed_date is None or r.event_code is None:
            continue
        groups.setdefault((r.key.person_id, r.performed_date, r.event_code, r.mark_raw.strip()), []).append(r)
    links = []
    for rows in groups.values():
        if len({r.key.profile_id for r in rows}) < 2:
            continue
        rows = sorted(rows, key=lambda r: (r.key.profile_id, r.key.record_id))
        canonical = rows[0]
        for r in rows[1:]:
            if r.key.profile_id == canonical.key.profile_id:
                continue
            links.append(DuplicateLink(canonical.key, r.key,
                                       "同一人物・同日・同種目・同記録表記（利用者決定 2026-10-19）", "rule"))
    return links


# ---- 箱根の学生連合（利用者決定 2026-10-19）：区間順位の扱いから除く ----
def is_student_alliance(affiliation_raw: Optional[str]) -> bool:
    return bool(affiliation_raw) and "連合" in affiliation_raw
