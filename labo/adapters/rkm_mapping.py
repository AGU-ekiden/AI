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
    m = re.match(r"^(?:高校?|H)?\s*([1-3])\s*(?:年生?)?\s*\+?$", s)
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


def is_high_school_row(affiliation_raw: Optional[str], category_raw: Optional[str] = None) -> bool:
    """所属名の末尾（○○高）か、年次ベストのカテゴリー「高校」で高校と判定。大学・中学の手がかりと矛盾すれば False。"""
    level = school_level(affiliation_raw)
    cat = (category_raw or "").strip()
    if level in ("univ", "junior") or cat in ("大学", "中学"):
        return False
    return level == "high" or cat == "高校"


ROUND_ORDER = {"prelim": 1, "semi": 2, "final": 3}


def round_order_of(raw: Optional[str]) -> Optional[int]:
    """同じ日の予選→準決勝→決勝の順序（別の大会どうしの順序は分からないので、同じ値になり曖昧のまま残る）。"""
    c = round_class(raw)
    return ROUND_ORDER.get(c) if c else None


def entry_year_candidates(rows) -> dict[int, int]:
    """高校所属のレースごとに出した入学年度の候補と件数（食い違いの診断用）。"""
    from ..periods import fiscal_year_of
    found: dict[int, int] = {}
    for row in rows:
        d, grade_raw, aff = row[:3]
        cat = row[3] if len(row) > 3 else None
        g = parse_grade(grade_raw)
        if d is None or g is None or not is_high_school_row(aff, cat):
            continue
        fy = fiscal_year_of(d) - (g - 1)
        found[fy] = found.get(fy, 0) + 1
    return found


def infer_hs_entry_fy(rows) -> tuple[Optional[int], str, int]:
    """rows: (race_date, grade_raw, affiliation_raw[, category_raw]) の並び。
    高校所属のレースの「年度 −（学年−1）」がすべて一致したときだけ入学年度とする。
    戻り値 (入学年度, 理由, 根拠件数)。食い違いは推測で選ばず None。"""
    from ..periods import fiscal_year_of
    found: dict[int, int] = {}
    for row in rows:
        d, grade_raw, aff = row[:3]
        cat = row[3] if len(row) > 3 else None
        g = parse_grade(grade_raw)
        if d is None or g is None or not is_high_school_row(aff, cat):
            continue
        fy = fiscal_year_of(d) - (g - 1)
        found[fy] = found.get(fy, 0) + 1
    if not found:
        return None, "no_high_school_grade", 0
    if len(found) > 1:
        return None, "conflicting_grades", sum(found.values())
    fy, n = next(iter(found.items()))
    return fy, "derived_from_grade", n


# ---- ラウンドの正規化（同じレースの別表示を見分けるため） ----
def round_class(raw: Optional[str]) -> Optional[str]:
    """'prelim'（予選）/ 'semi'（準決勝）/ 'final'（決勝・タイムレース等の1本のレース）/ None（不明・空）。
    「総合結果」「一覧」などの表示の違いは区別しない。"""
    import unicodedata
    if raw is None:
        return None
    s = unicodedata.normalize("NFKC", raw).replace("\n", "").replace(" ", "").strip().lower()
    for suffix in ("総合結果", "総合", "結果", "一覧"):
        s = s.replace(suffix, "")
    if s == "":
        return None
    if "準決" in s:
        return "semi"
    if "予" in s or s in ("h", "heat"):
        return "prelim"
    return "final"  # 決勝・タイムレース・レース・記録会・r・R1・Final など


def same_race_rounds(a: Optional[str], b: Optional[str]) -> bool:
    ca, cb = round_class(a), round_class(b)
    return ca is None or cb is None or ca == cb


# ---- 重複のまとめ ----
# (1) 複数プロフィール（利用者決定 2026-10-19）：同一人物・同日・同種目・同記録表記は1つにまとめる
# (2) 同じプロフィール内の二重表示（提案・確認待ち）：同じ大会・同日・同種目・同記録表記で、ラウンドが
#     同じレースの別表示（例「ﾀｲﾑﾚｰｽ」と「ﾀｲﾑﾚｰｽ総合結果」）なら1つにまとめる。予選と決勝は別レース。
def build_duplicate_links(results, merge_same_profile: bool = True) -> list:
    """代表は profile_id/record_id の辞書順で最小（決定的）。"""
    from ..model import DuplicateLink
    groups: dict[tuple, list] = {}
    for r in results:
        if r.status != STATUS_OK or not r.mark_raw or r.performed_date is None or r.event_code is None:
            continue
        groups.setdefault((r.key.person_id, r.performed_date, r.event_code, r.mark_raw.strip()), []).append(r)
    links = []
    for rows in groups.values():
        rows = sorted(rows, key=lambda r: (r.key.profile_id, r.key.record_id))
        kept: list = []
        for r in rows:
            target = None
            for k in kept:
                if k.key.profile_id != r.key.profile_id:
                    target, why = k, "同一人物・同日・同種目・同記録表記（複数プロフィール。利用者決定 2026-10-19）"
                    break
                if (merge_same_profile and k.competition_id is not None
                        and k.competition_id == r.competition_id and same_race_rounds(k.round_raw, r.round_raw)):
                    target, why = k, "同じ大会・同日・同種目・同記録表記で同じレースの別表示（同一プロフィール）"
                    break
            if target is None:
                kept.append(r)
            else:
                links.append(DuplicateLink(target.key, r.key, why, "rule"))
    return links


# ---- 箱根の学生連合（利用者決定 2026-10-19）：区間順位の扱いから除く ----
def is_student_alliance(affiliation_raw: Optional[str], place_raw: Optional[str] = None) -> bool:
    """所属名に「連合」、または順位の原文が OP（オープン参加）。
    rkm の駅伝の行は affiliation_raw が空のため、箱根本戦では place_raw の OP が主な手がかり（第3回監査で確認）。"""
    if affiliation_raw and "連合" in affiliation_raw:
        return True
    return bool(place_raw) and place_raw.strip().upper() == "OP"


# ---- 箱根のエントリー年・出走年（利用者確認 2026-10-19：athletes.entry_years / run_years は箱根駅伝） ----
def parse_years(raw: Optional[str]) -> Optional[list[int]]:
    """'["2021","2022"]' → [2021, 2022]。NULL は None（情報なし）、'[]' は空リスト（該当なし）。"""
    import json
    if raw is None:
        return None
    try:
        vals = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(vals, list):
        return None
    out = []
    for v in vals:
        try:
            out.append(int(str(v)))
        except ValueError:
            return None
    return sorted(set(out))


def hakone_year_to_edition_fy(year: int, calendar_year: bool = True) -> int:
    """出走年 → 大会の年度。箱根は1月開催のため、出走年が暦年（例 2022 = 2022年1月）なら年度は前年。
    暦年か年度かは第3回監査（run_years_alignment）で確認する。既定は暦年。"""
    return year - 1 if calendar_year else year


def person_complete_editions(edition_fys: list[int], run_years: Optional[list[int]],
                             ranked_record_fys: set[int], calendar_year: bool = True) -> set[int]:
    """その人について「結果がそろっている」大会年度の集合（outcomes.label_person の complete_editions に渡す）。
    - Notion の出走年に無い年度：走っていないことが分かっているので、そろっている扱い
    - 出走年にある年度：区間順位（または学生連合 OP）の記録が DB にある場合だけ、そろっている扱い
    run_years が無い（NULL）人は何も分からないので空集合。"""
    if run_years is None:
        return set()
    ran = {hakone_year_to_edition_fy(y, calendar_year) for y in run_years}
    return {fy for fy in edition_fys if fy not in ran or fy in ranked_record_fys}


def linkage_checked(entry_years_raw: Optional[str], run_years_raw: Optional[str]) -> bool:
    """利用者の Notion 選手一覧で箱根のエントリー・出走が整理されている人（値が NULL でない）を照合済みとみなす。"""
    return parse_years(entry_years_raw) is not None and parse_years(run_years_raw) is not None
