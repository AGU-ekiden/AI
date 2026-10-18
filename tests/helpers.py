from __future__ import annotations

from datetime import date
from typing import Optional

from labo.catalog import builtin_definitions
from labo.definitions import FeatureDefinition, validate_spec
from labo.features import compute_person
from labo.model import (
    COVERAGE_FETCHED, IDENTITY_CONFIRMED, STATUS_OK, Athlete, Dataset, Result, ResultKey,
)
from labo.periods import CUTOFF_PRESETS

G2 = CUTOFF_PRESETS["g2_end"]
ENTRY = 2020  # 高1=2020年度、締切(高2年度末)=2022-03-31
CUTOFF = date(2022, 3, 31)

_seq = [0]


def res(pid: str, d: Optional[date], sec: Optional[float], *, event="5000m", group="individual",
        status=STATUS_OK, comp: Optional[str] = None, start=None, end=None, rid=None,
        identity=IDENTITY_CONFIRMED, row_checked=True, round_order=None, start_time=None,
        dup=False, vstatus="validated", profile="P1", first_available_at=None,
        performed=None) -> Result:
    _seq[0] += 1
    rid = rid or f"R{_seq[0]:05d}"
    s = start if start is not None else d
    e = end if end is not None else (d if start is None else None)
    return Result(ResultKey(pid, profile, rid), event, group, comp or f"C{_seq[0]}", "テスト大会",
                  s, e, d if start is None else performed, status, str(sec), sec, 2, "electric",
                  identity, round_order, start_time, first_available_at, None, vstatus,
                  row_checked, dup, "test")


def ds_of(results, entry: Optional[int] = ENTRY, coverage=COVERAGE_FETCHED, **kw) -> Dataset:
    pids = sorted({r.key.person_id for r in results}) or ["A"]
    ath = {p: Athlete(p, p, entry, "test", "confirmed", coverage, True) for p in pids}
    return Dataset(ath, list(results), kw.get("links", []), kw.get("national", set()), True, "test")


def defs_by_id() -> dict[str, FeatureDefinition]:
    return {d.feature_id: d for d in builtin_definitions()}


def values(ds: Dataset, pid: str = "A", rule=G2, defs=None, options=None) -> dict:
    from labo.quality import Options
    defs = defs or builtin_definitions()
    vals = compute_person(ds, ds.athletes[pid], defs, rule, options or Options())
    return {v.feature_ref.split("@")[0]: v for v in vals}


def custom(fid: str, spec: dict) -> FeatureDefinition:
    base = defs_by_id()["best_5000_s"]
    d = FeatureDefinition.from_dict(base.to_dict())
    d.feature_id, d.spec = fid, validate_spec(spec)
    return d
