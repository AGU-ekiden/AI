"""合成データ（架空）。実在選手・実大会とは無関係。決定的（同じseedなら同じ出力）。

検証用の特殊ケース（3000mSC、駅伝親レコード、DNS/DNF、二重掲載、締切またぎ大会、
同日予選決勝、行未確認、raw_only、同じrecord_idを持つ別人など）を意図的に含む。
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from .model import (
    COVERAGE_FETCHED, COVERAGE_UNKNOWN, IDENTITY_CONFIRMED, IDENTITY_UNCONFIRMED,
    STATUS_DNF, STATUS_DNS, STATUS_OK, Athlete, Dataset, DuplicateLink, Result, ResultKey,
)

SYNTHETIC_LABEL = "合成データ（架空の選手・大会。実データではありません）"


@dataclass(frozen=True)
class Comp:
    cid: str
    name: str
    start: date
    days: int
    national: bool = False
    ekiden: bool = False

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.days - 1)


def _fmt(sec: float) -> str:
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:05.2f}"


def _comps_for_fy(y: int) -> list[Comp]:
    return [
        Comp(f"SYN-{y}-K1", f"架空記録会A {y}", date(y, 4, 20), 1),
        Comp(f"SYN-{y}-K2", f"架空記録会B {y}", date(y, 5, 18), 1),
        Comp(f"SYN-{y}-PREF", f"架空県選手権 {y}", date(y, 6, 1), 3),
        Comp(f"SYN-{y}-IH", f"架空全国高校総体 {y}", date(y, 7, 28), 5, national=True),
        Comp(f"SYN-{y}-K3", f"架空記録会C {y}", date(y, 9, 21), 1),
        Comp(f"SYN-{y}-K4", f"架空記録会D {y}", date(y, 10, 19), 1),
        Comp(f"SYN-{y}-K5", f"架空記録会E {y}", date(y, 11, 23), 1),
        Comp(f"SYN-{y}-EKI", f"架空全国高校駅伝 {y}", date(y, 12, 21), 1, national=True, ekiden=True),
        Comp(f"SYN-{y}-K6", f"架空記録会F {y}", date(y + 1, 2, 23), 1),
        Comp(f"SYN-{y}-SPR", f"架空春季大会 {y}", date(y + 1, 3, 30), 3),  # 年度末をまたぐ
    ]


def generate(seed: int = 20261018, n_athletes: int = 36) -> Dataset:
    rng = random.Random(seed)
    athletes: dict[str, Athlete] = {}
    results: list[Result] = []
    national: set[str] = set()
    comps_by_fy = {y: _comps_for_fy(y) for y in range(2017, 2027)}
    for cs in comps_by_fy.values():
        national |= {c.cid for c in cs if c.national}

    def add(pid: str, comp: Comp, event: str, sec: Optional[float], *, group="individual",
            status=STATUS_OK, performed: Optional[date] = None, identity=IDENTITY_CONFIRMED,
            row_checked=True, round_order=None, start_time=None, suffix="", dup=False,
            vstatus="validated", profile="P1", mark_raw=None) -> Result:
        rid = f"{comp.cid}-{event}{suffix}"  # 同じレースは別人でも同じrecord_id
        r = Result(
            key=ResultKey(pid, f"{pid}-{profile}", rid), event_code=event, event_group=group,
            competition_id=comp.cid, competition_name=comp.name, competition_start=comp.start,
            competition_end=comp.end, performed_date=performed, status=status,
            mark_raw=mark_raw if mark_raw is not None else (_fmt(sec) if sec else status),
            seconds=sec if status == STATUS_OK else None, precision_digits=2 if sec else None,
            timing="electric", identity=identity, round_order=round_order,
            start_time=start_time, captured_at=date(2026, 10, 1),
            capture_validation_status=vstatus, row_checked=row_checked,
            duplicate_suspect=dup, source_ref=f"synthetic:{pid}:{rid}",
        )
        results.append(r)
        return r

    for i in range(1, n_athletes + 1):
        pid = f"SYN{i:04d}"
        entry = 2019 + (i % 5)
        athletes[pid] = Athlete(pid, f"架空選手 {i:03d}", entry, "合成：入学年度を設定",
                                "confirmed", COVERAGE_FETCHED, True)
        base = rng.uniform(930, 1010)  # 高1春の5000m（15:30〜16:50）
        for g in (1, 2, 3):
            fy = entry + g - 1
            for c in comps_by_fy[fy]:
                if c.ekiden:
                    if rng.random() < 0.5:
                        add(pid, c, "ekiden", rng.uniform(7000, 7500), group="ekiden",
                            performed=c.start)
                    continue
                if rng.random() < 0.45:
                    continue
                months = (c.start - date(entry, 4, 1)).days / 30.4
                sec = round(base - months * rng.uniform(0.9, 1.6) + rng.gauss(0, 6), 2)
                performed = c.start if c.days == 1 else (
                    c.start + timedelta(days=rng.randrange(c.days)) if rng.random() < 0.75 else None)
                event = "5000m" if rng.random() < 0.75 else rng.choice(["1500m", "3000mSC"])
                if event == "1500m":
                    sec = round(sec * 0.27, 2)
                elif event == "3000mSC":
                    sec = round(sec * 0.62, 2)
                status = STATUS_OK
                roll = rng.random()
                if roll < 0.03:
                    status = STATUS_DNS
                elif roll < 0.05:
                    status = STATUS_DNF
                add(pid, c, event, sec, status=status, performed=performed,
                    vstatus="raw_only" if rng.random() < 0.3 else "validated",
                    row_checked=rng.random() > 0.05)

    _add_edge_cases(athletes, results, comps_by_fy, add)
    links = [DuplicateLink(
        canonical=ResultKey("SYN9003", "SYN9003-P1", "SYN-2020-K3-5000m"),
        duplicate=ResultKey("SYN9003", "SYN9003-P2", "SYN-2020-K3-5000m"),
        evidence="合成：同一大会・同一記録・同一所属の二重プロフィール", decided_by="合成データ")]
    return Dataset(athletes, results, links, national, True, SYNTHETIC_LABEL)


def _add_edge_cases(athletes, results, comps_by_fy, add) -> None:
    # 入学年度不明（年齢等から補完しない）
    athletes["SYN9001"] = Athlete("SYN9001", "架空選手 入学年度不明", None, "根拠なし", "unknown",
                                  COVERAGE_FETCHED, True)
    add("SYN9001", comps_by_fy[2021][0], "5000m", 960.0, performed=date(2021, 4, 20))
    # 取得状態不明
    athletes["SYN9002"] = Athlete("SYN9002", "架空選手 取得状態不明", 2021, "合成", "confirmed",
                                  COVERAGE_UNKNOWN, True)
    add("SYN9002", comps_by_fy[2021][1], "5000m", 950.0)
    # 二重プロフィール（証拠で統合済み）と未解決の二重掲載疑い
    athletes["SYN9003"] = Athlete("SYN9003", "架空選手 二重掲載", 2020, "合成", "confirmed",
                                  COVERAGE_FETCHED, True)
    for c, s in ((comps_by_fy[2020][0], 940.0), (comps_by_fy[2020][4], 930.0),
                 (comps_by_fy[2021][0], 915.0), (comps_by_fy[2021][4], 905.0)):
        add("SYN9003", c, "5000m", s)
    add("SYN9003", comps_by_fy[2020][4], "5000m", 930.0, profile="P2")  # 統合対象
    add("SYN9003", comps_by_fy[2021][6], "5000m", 900.0, dup=True)     # 未解決の疑い
    # 締切をまたぐ春季大会（実施日不明）・同日予選決勝（順序不明）・本人未確認
    athletes["SYN9004"] = Athlete("SYN9004", "架空選手 日付境界", 2020, "合成", "confirmed",
                                  COVERAGE_FETCHED, True)
    for c, s in ((comps_by_fy[2020][1], 950.0), (comps_by_fy[2021][1], 930.0),
                 (comps_by_fy[2021][4], 925.0)):
        add("SYN9004", c, "5000m", s)
    pref = comps_by_fy[2021][2]
    add("SYN9004", pref, "5000m", 920.0, performed=date(2021, 6, 2), suffix="-H")
    add("SYN9004", pref, "5000m", 915.0, performed=date(2021, 6, 2), suffix="-F")
    add("SYN9004", comps_by_fy[2021][9], "5000m", 910.0, performed=None)  # 3/30〜4/1
    add("SYN9004", comps_by_fy[2021][5], "5000m", 900.0, identity=IDENTITY_UNCONFIRMED)
    add("SYN9004", comps_by_fy[2021][6], "5000m", 9.0, mark_raw="9.00")  # 単位異常の疑い
    # 高3で初めて全国大会に出場（高2締切の全国経験集団に入らない）
    athletes["SYN9005"] = Athlete("SYN9005", "架空選手 高3初全国", 2020, "合成", "confirmed",
                                  COVERAGE_FETCHED, True)
    add("SYN9005", comps_by_fy[2021][0], "5000m", 945.0)
    add("SYN9005", comps_by_fy[2022][3], "5000m", 880.0, performed=date(2022, 7, 30))
