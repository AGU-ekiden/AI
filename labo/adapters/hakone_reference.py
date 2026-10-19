"""公開の公式記録（reference/hakone_*_official.tsv）と選手を照合し、箱根の補完行を作る。

照合は「同じ出走年」「氏名が一致（異体字を寄せて比較）」「大学が一致」の3条件がそろい、候補が1人だけのときのみ。
それ以外（候補なし・複数・大学不一致）は自動で埋めず、利用者の確認に回す。rkm は変更しない。
"""
from __future__ import annotations

import csv
import unicodedata
from pathlib import Path
from typing import Optional

_VARIANTS = str.maketrans({"﨑": "崎", "嵜": "崎", "濵": "浜", "濱": "浜", "澤": "沢", "邊": "辺", "邉": "辺",
                           "髙": "高", "齊": "斉", "齋": "斉", "國": "国", "學": "学", "廣": "広", "德": "徳",
                           "瀨": "瀬", "槇": "槙", "冨": "富", "櫻": "桜", "藏": "蔵", "惠": "恵", "眞": "真"})


def norm_name(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKC", s or "").translate(_VARIANTS)
    return "".join(ch for ch in s if not ch.isspace() and ch not in "・･")


def norm_univ(s: Optional[str]) -> str:
    s = norm_name(s)
    for suffix in ("大学院", "大学", "大"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s


def univ_match(a: Optional[str], b: Optional[str]) -> bool:
    x, y = norm_univ(a), norm_univ(b)
    return bool(x) and bool(y) and (x == y or x in y or y in x)


def load_reference(paths) -> list[dict]:
    rows = []
    for p in paths:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                r["run_year"] = int(r["run_year"])
                rows.append(r)
    return rows


def default_reference_paths(root: Path) -> list[Path]:
    return sorted((root / "reference").glob("hakone_*_official.tsv"))


def match(name: str, university: Optional[str], run_year: int, ref: list[dict]) -> tuple[Optional[dict], str]:
    """(一致した行, 理由)。理由：matched / matched_partial_name / no_reference_year / name_not_found /
    ambiguous_name / university_mismatch"""
    year_rows = [r for r in ref if r["run_year"] == run_year]
    if not year_rows:
        return None, "no_reference_year"
    cands = [r for r in year_rows if norm_name(r["name"]) == norm_name(name)]
    if not cands:
        # 公式記録では留学生などを名前の一部だけで載せることがある（例「ダンカン マイナ」→「マイナ」）。
        # 一方が他方を含み、大学も一致して1人に決まるときだけ採用する。
        me = norm_name(name)
        partial = [r for r in year_rows if len(norm_name(r["name"])) >= 2 and me
                   and (norm_name(r["name"]) in me or me in norm_name(r["name"]))
                   and univ_match(university, r["university"])]
        if len(partial) == 1:
            return partial[0], "matched_partial_name"
        return None, "ambiguous_name" if len(partial) > 1 else "name_not_found"
    by_univ = [r for r in cands if univ_match(university, r["university"])]
    if len(by_univ) == 1:
        return by_univ[0], "matched"
    if len(cands) > 1 or len(by_univ) > 1:
        return None, "ambiguous_name"
    return None, "university_mismatch"


def to_supplement_row(person_id: str, name: str, university: str, ref_row: dict) -> dict:
    alliance = str(ref_row.get("is_student_alliance", "0")) == "1"
    return {"person_id": person_id, "name": name, "university": university, "run_year": ref_row["run_year"],
            "leg": ref_row["leg"], "leg_rank": "" if alliance else ref_row["leg_rank"],
            "is_student_alliance": "1" if alliance else "",
            "source_note": f"第{ref_row['run_year'] - 1924}回 往復総合公式記録（関東学連）"}
