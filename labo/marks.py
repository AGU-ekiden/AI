"""記録表記の解釈。内部は秒に統一し、原表記と精度を残す。"""
from __future__ import annotations

import re
from typing import Optional

_PATTERNS = [
    # 14:32.15 / 1:04:32.1 / 14:32
    re.compile(r"^(?:(?P<h>\d+):)?(?P<m>\d{1,2}):(?P<s>\d{2})(?:\.(?P<f>\d{1,3}))?$"),
    # 14'32"15 / 14'32"1
    re.compile(r"^(?P<m>\d{1,3})'(?P<s>\d{2})\"(?P<f>\d{1,3})?$"),
    # 秒のみ 872.15
    re.compile(r"^(?P<s>\d+)(?:\.(?P<f>\d{1,3}))?$"),
]


def parse_time_mark(raw: str) -> tuple[Optional[float], Optional[int], str]:
    """戻り値 (秒, 小数桁数, 理由)。解釈できなければ (None, None, 理由)。

    0や負は「真の0」ではなく不正タイムとして理由付きで返す。
    """
    if raw is None:
        return None, None, "blank"
    s = raw.strip()
    if s == "":
        return None, None, "blank"
    upper = s.upper()
    for token in ("DNS", "DNF", "DSQ", "DQ"):
        if upper == token:
            return None, None, "DSQ" if token == "DQ" else token
    for pat in _PATTERNS:
        m = pat.match(s)
        if not m:
            continue
        gd = m.groupdict()
        h = int(gd.get("h") or 0)
        mi = int(gd.get("m") or 0)
        sec = int(gd["s"])
        frac = gd.get("f") or ""
        if "m" in gd and gd.get("m") is not None and sec >= 60:
            return None, None, "format_unknown"
        value = h * 3600 + mi * 60 + sec + (int(frac) / (10 ** len(frac)) if frac else 0.0)
        value = round(value, 3)
        if value <= 0:
            return None, None, "nonpositive_time"
        return value, len(frac), "ok"
    return None, None, "format_unknown"
