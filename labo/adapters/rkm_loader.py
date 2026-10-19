"""rkm（読み取り専用）→ 研究用モデル（labo.model.Dataset）の読み込み。

対応ルールは rkm_mapping.py（根拠は docs/decisions.md・docs/audit_baseline.md）。
- SQL は下記の固定 SELECT のみ。利用者入力は使わない。接続は READ ONLY・タイムアウト付き。
- 書き込み可能な接続（lab_reader 以外）なら読み込みを中止する。
- 成果（箱根）は特徴量の Dataset とは別に返し、特徴量・母集団には渡さない。
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

from ..model import (
    COVERAGE_FETCHED, IDENTITY_CONFIRMED, STATUS_OK, Athlete, Dataset, EkidenRun, Result, ResultKey,
)
from ..outcomes import HakoneLegResult, OutcomeDefinition, OutcomeLabel, label_person
from .rkm_mapping import (
    build_duplicate_links, ekiden_race_class, entry_year_candidates, infer_hs_entry_fy, is_student_alliance,
    map_event,
    map_status, parse_date, person_complete_editions, parse_years, round_order_of,
)
from .rkm_readonly import SAFETY_QUERIES, UnsafeConnection, assert_readonly_sql

REAL_DATA_LABEL = "実データ（rkm・読み取り専用。非公開）"
_HS_EKIDEN = ("r.event_group = 'ekiden' AND (r.competition_raw LIKE '%高校駅伝%' OR r.competition_raw LIKE '%高等学校駅伝%' OR r.competition_raw LIKE '%都道府県%駅伝%') AND r.competition_raw NOT LIKE '%女子%'")

# 全国大会（母集団 national_by_cutoff 用）。研究上の選択であり暫定（大会名の部分一致）
NATIONAL_PATTERNS = ("全国高校総合体育大会", "全国高等学校総合体育大会", "インターハイ",
                     "全国高等学校駅伝", "全国高校駅伝", "都道府県対抗男子駅伝", "国民体育大会",
                     "国民スポーツ大会", "日本ジュニア", "U20日本選手権", "U18日本選手権")

Q = {
    "athletes": "SELECT person_id, name, entry_years, run_years FROM rkm.athletes",
    "athlete_universities": "SELECT person_id, university_raw FROM rkm.athletes",
    "profiles": "SELECT person_id, profile_id, identity_role FROM rkm.profiles",
    "comp_range": (
        "SELECT competition_id, min(date), max(date), count(DISTINCT date), max(competition_raw) "
        "FROM rkm.records WHERE competition_id IS NOT NULL GROUP BY 1"),
    "grades": (
        "SELECT person_id, date, grade_raw, affiliation_raw, category_raw FROM rkm.records "
        "WHERE grade_raw IS NOT NULL"),
    "results": (
        "SELECT person_id, profile_id, record_id, date, competition_id, competition_raw, event, "
        "event_group, round_raw, mark_raw, mark_value, mark_unit, timing, status FROM rkm.records "
        "WHERE event IN ('5000m', '1500m', '3000m', '3000mSC(91.4cm)')"),
    "national_results": (
        "SELECT person_id, profile_id, record_id, date, competition_id, competition_raw, event, "
        "event_group, status FROM rkm.records WHERE competition_raw LIKE ANY (ARRAY["
        + ", ".join("'%" + p + "%'" for p in NATIONAL_PATTERNS) + "])"),
    "hakone": (
        "SELECT person_id, profile_id, record_id, date, fiscal_year, ekiden_leg, ekiden_leg_rank, "
        "place_raw, affiliation_raw FROM rkm.records WHERE event_group = 'ekiden' "
        "AND competition_raw LIKE '%箱根%' AND competition_raw NOT LIKE '%予選%'"),
    "hakone_self_legs": (
        "SELECT l.person_id, l.profile_id, l.record_id, l.leg, l.leg_rank FROM rkm.ekiden_legs l "
        "JOIN rkm.records r USING (person_id, profile_id, record_id) WHERE l.is_self = 1 "
        "AND r.event_group = 'ekiden' AND r.competition_raw LIKE '%箱根%' AND r.competition_raw NOT LIKE '%予選%'"),
    "counts": "SELECT (SELECT count(*) FROM rkm.records), (SELECT count(*) FROM rkm.athletes)",
    # 高校・都道府県駅伝の本人区間（特徴量用）。区間・区間順位が records に無ければ ekiden_legs の本人区間で補う
    "hs_ekiden": (
        "SELECT r.person_id, r.profile_id, r.record_id, r.date, r.competition_raw, r.ekiden_leg, "
        "r.ekiden_leg_value, r.ekiden_leg_rank, r.status FROM rkm.records r WHERE " + _HS_EKIDEN),
    "hs_ekiden_self_legs": (
        "SELECT l.person_id, l.profile_id, l.record_id, l.leg, l.leg_rank, l.leg_value FROM rkm.ekiden_legs l "
        "JOIN rkm.records r USING (person_id, profile_id, record_id) WHERE l.is_self = 1 AND " + _HS_EKIDEN),
}


@dataclass
class HakoneData:
    legs: list[HakoneLegResult] = field(default_factory=list)
    run_years: dict[str, Optional[list[int]]] = field(default_factory=dict)
    entry_years: dict[str, Optional[list[int]]] = field(default_factory=dict)
    ambiguous_records: int = 0
    universities: dict[str, str] = field(default_factory=dict)
    supplement_used: int = 0
    supplement_rejected: dict[str, int] = field(default_factory=dict)


def outcome_labels(ds: Dataset, hakone: HakoneData, definition: OutcomeDefinition,
                   as_of: date) -> dict[str, OutcomeLabel]:
    """全員の成果ラベル。結果がそろった大会・照合済みかは Notion の出走年・エントリー年から判断する。"""
    by_person: dict[str, list[HakoneLegResult]] = defaultdict(list)
    for lg in hakone.legs:
        by_person[lg.person_id].append(lg)
    out = {}
    for pid, ath in ds.athletes.items():
        mine = by_person.get(pid, [])
        if ath.hs_entry_fiscal_year is None:
            out[pid] = label_person(pid, None, mine, definition=definition, as_of=as_of,
                                    complete_editions=set(), linkage_checked=False)
            continue
        window = definition.edition_fys(ath.hs_entry_fiscal_year)
        ranked = {lg.edition_fy for lg in mine if lg.official_rank is not None or lg.reference_only}
        out[pid] = label_person(
            pid, ath.hs_entry_fiscal_year, mine, definition=definition, as_of=as_of,
            complete_editions=person_complete_editions(window, hakone.run_years.get(pid), ranked),
            linkage_checked=hakone.run_years.get(pid) is not None and hakone.entry_years.get(pid) is not None)
    return out


@dataclass
class LoadReport:
    persons: int = 0
    results: int = 0
    entry_year: dict[str, int] = field(default_factory=dict)  # 理由別人数
    duplicate_links: int = 0
    date_maybe_first_day: int = 0
    excluded_rows: dict[str, int] = field(default_factory=dict)
    # 学年の食い違いの診断（人数）：最多候補の割合・候補の幅・多数決なら救える人数
    entry_conflicts: dict[str, dict] = field(default_factory=dict)
    ekiden: dict[str, int] = field(default_factory=dict)  # 高校・都道府県駅伝の取り込み内訳（行数）
    ekiden_names: dict[str, dict] = field(default_factory=dict)  # 大会区分ごとの大会名（回数を除く）の件数


def _to_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, date):
        return v
    return parse_date(str(v))


def _bump(d: dict, key: str) -> None:
    d[key] = d.get(key, 0) + 1


def _diagnose_conflict(rep: LoadReport, cand: dict[int, int]) -> None:
    total = sum(cand.values())
    top = max(cand.values())
    share = top / total
    bucket = "90%以上" if share >= 0.9 else "80〜90%" if share >= 0.8 else "60〜80%" if share >= 0.6 else "60%未満"
    spread = max(cand) - min(cand)
    c = rep.entry_conflicts
    _bump(c.setdefault("最多候補の割合", {}), bucket)
    _bump(c.setdefault("候補の幅（年）", {}), str(spread) if spread < 3 else "3以上")
    _bump(c.setdefault("根拠の件数", {}), "1〜2件" if total <= 2 else "3〜5件" if total <= 5 else "6件以上")
    if share >= 0.8 and top >= 3 and list(cand.values()).count(top) == 1:
        _bump(c.setdefault("多数決（80%以上かつ3件以上）なら決まる", {}), "人数")


def build_dataset(rows: dict[str, Iterable[tuple]]) -> tuple[Dataset, HakoneData, LoadReport]:
    """クエリ結果（Q と同じキー）から Dataset を作る。DB に依存しないのでテスト可能。"""
    rep = LoadReport()
    comp_range: dict[str, tuple] = {}
    national: set[str] = set()
    for cid, d0, d1, n_dates, name in rows["comp_range"]:
        comp_range[cid] = (_to_date(d0), _to_date(d1), n_dates)
        if name and any(p in name for p in NATIONAL_PATTERNS):
            national.add(cid)

    grades: dict[str, list] = defaultdict(list)
    for pid, d, g, aff, cat in rows["grades"]:
        grades[pid].append((_to_date(d), g, aff, cat))

    athletes: dict[str, Athlete] = {}
    hakone = HakoneData()
    for pid, name, entry_raw, run_raw in rows["athletes"]:
        fy, why, n = infer_hs_entry_fy(grades.get(pid, []))
        rep.entry_year[why] = rep.entry_year.get(why, 0) + 1
        if why == "conflicting_grades":
            _diagnose_conflict(rep, entry_year_candidates(grades.get(pid, [])))
        athletes[pid] = Athlete(
            pid, name or pid, fy,
            (f"学年表記から算出（{n}件一致）" if why == "derived_from_grade"
             else f"学年表記の多数決（{n}件・8割以上が一致）" if fy is not None else f"算出不可：{why}"),
            "derived" if fy is not None else "unknown", COVERAGE_FETCHED, False)
        hakone.run_years[pid] = parse_years(run_raw)
        hakone.entry_years[pid] = parse_years(entry_raw)
    mapped_profiles = {(pid, prof) for pid, prof, _role in rows["profiles"]}
    for pid, univ in rows.get("athlete_universities", []):
        hakone.universities[pid] = univ or ""

    results: list[Result] = []
    for (pid, prof, rid, d, cid, cname, event, group, rnd, mark_raw, mark_value, unit, timing,
         status) in rows["results"]:
        code = map_event(event, group)
        if code is None or pid not in athletes:
            rep.excluded_rows["unmapped_event_or_person"] = rep.excluded_rows.get("unmapped_event_or_person", 0) + 1
            continue
        st = map_status(status)
        day = _to_date(d)
        c0, c1, n_dates = comp_range.get(cid, (day, day, 1))
        maybe_first = bool(day is not None and n_dates and n_dates > 1 and day == c0)
        rep.date_maybe_first_day += maybe_first
        seconds = float(mark_value) if (st == STATUS_OK and mark_value is not None and unit == "s") else None
        checked = (st == STATUS_OK and seconds is not None and day is not None
                   and (pid, prof) in mapped_profiles)
        results.append(Result(
            key=ResultKey(pid, prof, rid), event_code=code, event_group="individual",
            competition_id=cid, competition_name=cname or "", competition_start=c0 or day,
            competition_end=c1 or day, performed_date=day, status=st, mark_raw=mark_raw or "",
            seconds=seconds, precision_digits={"electronic": 2, "hand": 1, "whole_seconds": 0}.get(timing),
            timing=timing, identity=IDENTITY_CONFIRMED if (pid, prof) in mapped_profiles else "unconfirmed",
            row_checked=checked, source_ref=f"rkm.records:{pid}/{prof}/{rid}",
            round_raw=rnd or "", date_maybe_first_day=maybe_first, round_order=round_order_of(rnd),
        ))
    # 全国大会の結果（母集団の判定用。個人走以外の駅伝も含む。特徴量の種目には使わない）
    for pid, prof, rid, d, cid, cname, event, group, status in rows.get("national_results", []):
        if pid not in athletes or cid not in national or map_event(event, group) is not None:
            continue
        day = _to_date(d)
        c0, c1, _n = comp_range.get(cid, (day, day, 1))
        results.append(Result(
            key=ResultKey(pid, prof, rid), event_code=None, event_group=group, competition_id=cid,
            competition_name=cname or "", competition_start=c0 or day, competition_end=c1 or day,
            performed_date=day, status=map_status(status), mark_raw="", seconds=None,
            precision_digits=None, timing=None, identity=IDENTITY_CONFIRMED, row_checked=False,
            source_ref=f"rkm.records:{pid}/{prof}/{rid}"))

    links = build_duplicate_links(results)
    rep.duplicate_links = len(links)
    rep.persons, rep.results = len(athletes), len(results)

    # 箱根（成果用）：同じ人・同じ年度・同じ区間はプロフィールが違っても1つにまとめる
    self_legs: dict[tuple, list] = defaultdict(list)
    for pid, prof, rid, leg, rank in rows["hakone_self_legs"]:
        self_legs[(pid, prof, rid)].append((leg, rank))
    seen: set[tuple] = set()
    for pid, prof, rid, d, fy, leg, leg_rank, place_raw, aff in rows["hakone"]:
        if pid not in athletes or fy is None:
            continue
        candidates = self_legs.get((pid, prof, rid), [])
        if leg is None and len(candidates) > 1:
            hakone.ambiguous_records += 1  # 本人が複数区間：自動で選ばない
            continue
        if leg is None and candidates:
            leg = candidates[0][0]
        if leg_rank is None:
            leg_rank = next((r for lg, r in candidates if lg == leg and r is not None), None)
        if leg is None or (pid, fy, leg) in seen:
            continue
        seen.add((pid, fy, leg))
        alliance = is_student_alliance(aff, place_raw)
        hakone.legs.append(HakoneLegResult(
            person_id=pid, edition_fy=int(fy), race_date=_to_date(d) or date(int(fy) + 1, 1, 3),
            leg=int(leg), official_rank=None if alliance else (int(leg_rank) if leg_rank is not None else None),
            reference_only=alliance, source_ref=f"rkm.records:{pid}/{prof}/{rid}"))

    _apply_hakone_supplement(rows.get("supplement", []), athletes, hakone)
    ds = Dataset(athletes, results, links, national, False, REAL_DATA_LABEL,
                 ekiden_runs=_hs_ekiden(rows, athletes, mapped_profiles, rep))
    return ds, hakone, rep


def _hs_ekiden(rows: dict, athletes: dict, mapped_profiles: set, rep: "LoadReport") -> list[EkidenRun]:
    """高校・都道府県駅伝の本人区間。同じ人・同じ日・同じ大会区分・同じ区間はプロフィールをまたいで1つにまとめる。"""
    self_legs: dict[tuple, list] = defaultdict(list)
    for pid, prof, rid, leg, rank, value in rows.get("hs_ekiden_self_legs", []):
        self_legs[(pid, prof, rid)].append((leg, rank, value))
    out: list[EkidenRun] = []
    seen: set[tuple] = set()
    for pid, prof, rid, d, cname, leg, value, rank, status in sorted(rows.get("hs_ekiden", []), key=lambda t: t[:3]):
        cls = ekiden_race_class(cname)
        day = _to_date(d)
        if pid not in athletes or cls is None or day is None or (pid, prof) not in mapped_profiles:
            _bump(rep.ekiden, "対象外（人物・大会名・日付・プロフィール）")
            continue
        if map_status(status) != STATUS_OK:
            _bump(rep.ekiden, "記録なし・棄権など")
            continue
        if leg is None:
            cand = self_legs.get((pid, prof, rid), [])
            if len(cand) == 1:
                leg, rank, value = cand[0]
            elif len(cand) > 1:
                _bump(rep.ekiden, "本人区間が複数（曖昧）")
                leg = rank = value = None
        key = (pid, day, cls, leg)
        if key in seen:
            _bump(rep.ekiden, "重複としてまとめた")
            continue
        seen.add(key)
        _bump(rep.ekiden, f"採用:{cls}" + ("" if rank is not None else "（区間順位なし）"))
        _bump(rep.ekiden_names.setdefault(cls, {}), re.sub(r"^第[0-9０-９]+回", "", cname or ""))
        out.append(EkidenRun(ResultKey(pid, prof, rid), day, cls, int(leg) if leg is not None else None,
                             int(rank) if rank is not None else None,
                             float(value) if value is not None else None))
    return out


SUPPLEMENT_COLUMNS = ["person_id", "name", "university", "run_year", "leg", "leg_rank",
                      "is_student_alliance", "source_note"]


def _apply_hakone_supplement(rows: Iterable[dict], athletes: dict, hakone: HakoneData) -> None:
    """補完ファイル（公式結果から利用者が記入）の箱根区間を追加する。rkm は変更しない。
    DB に同じ人・同じ大会年度の記録があれば DB を優先し、補完は使わない。"""
    def reject(why: str) -> None:
        hakone.supplement_rejected[why] = hakone.supplement_rejected.get(why, 0) + 1
    have = {(lg.person_id, lg.edition_fy) for lg in hakone.legs}
    for row in rows:
        pid = (row.get("person_id") or "").strip()
        leg_s, rank_s = (row.get("leg") or "").strip(), (row.get("leg_rank") or "").strip()
        alliance = (row.get("is_student_alliance") or "").strip() in ("1", "true", "True", "はい", "○")
        if not leg_s and not rank_s:
            continue  # 未記入の行
        if pid not in athletes:
            reject("person_id が見つからない"); continue
        try:
            year = int(row.get("run_year") or "")
            leg = int(leg_s)
            rank = int(rank_s) if rank_s else None
        except ValueError:
            reject("数値として読めない"); continue
        if not 1 <= leg <= 10 or (rank is not None and rank < 1):
            reject("区間・順位の範囲外"); continue
        if rank is None and not alliance:
            reject("区間順位が空（学生連合でもない）"); continue
        if year not in (hakone.run_years.get(pid) or []):
            reject("Notion の出走年に無い年"); continue
        fy = year - 1  # 出走年は暦年（1月の大会）→ 年度は前年
        if (pid, fy) in have:
            reject("DB に記録あり（DB を優先）"); continue
        have.add((pid, fy))
        hakone.legs.append(HakoneLegResult(
            person_id=pid, edition_fy=fy, race_date=date(year, 1, 2 if leg <= 5 else 3), leg=leg,
            official_rank=None if alliance else rank, reference_only=alliance,
            source_ref=f"supplement:{(row.get('source_note') or '').strip()[:100]}"))
        hakone.supplement_used += 1


def read_supplement_csv(path) -> list[dict]:
    """補完ファイル（UTF-8 / Excel の UTF-8 BOM 付き どちらも可）を読む。無ければ空。"""
    import csv
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f)]


def load_from_db(dsn_env: str = "RKM_READONLY_DSN",
                 supplement_path: Optional[str] = None) -> tuple[Dataset, HakoneData, LoadReport]:  # pragma: no cover
    dsn = os.environ.get(dsn_env)
    if not dsn:
        raise RuntimeError(f"環境変数 {dsn_env} が未設定です")
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    if not conninfo_to_dict(dsn).get("dbname"):
        dsn = make_conninfo(dsn, dbname="postgres")
    timeout = int(os.environ.get("RKM_STATEMENT_TIMEOUT_MS", "120000"))
    out: dict[str, list] = {}
    with psycopg.connect(dsn, connect_timeout=15) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('statement_timeout', %s, false)", (str(timeout),))
            cur.execute(SAFETY_QUERIES["can_write_rkm"])
            if cur.fetchone()[0] != 0:
                raise UnsafeConnection("この接続は rkm に書き込めます。lab_reader で接続してください")
            for name, sql in Q.items():
                assert_readonly_sql(sql)
                cur.execute(sql)
                out[name] = cur.fetchall()
        conn.rollback()
    path = supplement_path or os.environ.get("LABO_HAKONE_SUPPLEMENT", "data/hakone_supplement.csv")
    out["supplement"] = read_supplement_csv(path)
    return build_dataset(out)
