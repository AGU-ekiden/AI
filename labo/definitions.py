"""版付きの特徴量定義と、許可済み演算だけからなる宣言的スペックの検証。

自由な文章・SQL・Pythonは受け付けない。spec は下記のホワイトリストに合致する辞書のみ。
新しい演算が必要な場合はコード側の開発レビューで追加する。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

STATUSES = ["提案", "定義確認", "テスト済み", "計算可能", "研究で採用", "保留", "廃止"]
# 計算実行に使える状態（未承認の定義は実行しない）
RUNNABLE_STATUSES = {"計算可能", "研究で採用"}
# 合成データでのプレビューが許される状態（利用者が定義を確認済み）
PREVIEWABLE_STATUSES = {"定義確認", "テスト済み", "計算可能", "研究で採用"}
TRANSITIONS = {
    "提案": {"定義確認", "保留", "廃止"},
    "定義確認": {"テスト済み", "提案", "保留", "廃止"},
    "テスト済み": {"計算可能", "定義確認", "保留", "廃止"},
    "計算可能": {"研究で採用", "保留", "廃止"},
    "研究で採用": {"保留", "廃止"},
    "保留": {"提案", "定義確認", "廃止"},
    "廃止": set(),
}

ALLOWED_EVENTS = ["1500m", "3000m", "3000mSC", "5000m"]
ALLOWED_OPS = {
    "count", "span_days", "days_since_last", "min", "median_latest_n", "iqr",
    "pb_updates", "median_gap", "diff", "pct_change",
}
# 重複未解決の行が範囲内にあると null にする演算（件数・分布に依存）
DUP_SENSITIVE_OPS = {"count", "median_latest_n", "iqr", "median_gap"}
_INT_PARAMS = {
    "n": (2, 10), "min_n": (1, 20), "min_competitions": (1, 10), "min_dates": (2, 20),
}


class SpecError(ValueError):
    pass


def _check_window(w: Any) -> None:
    if not isinstance(w, dict) or "kind" not in w:
        raise SpecError("window は {kind: ...} の形式が必要です")
    kind = w["kind"]
    if kind == "hs":
        if set(w) != {"kind"}:
            raise SpecError("window(hs) に余分な項目があります")
    elif kind == "recent_days":
        if set(w) != {"kind", "days"} or type(w["days"]) is not int or not 1 <= w["days"] <= 1095:
            raise SpecError("window(recent_days) の days は 1〜1095 の整数")
    elif kind == "grade":
        if set(w) != {"kind", "grade"} or w["grade"] not in (1, 2):
            raise SpecError("window(grade) の grade は 1 または 2")
    else:
        raise SpecError(f"許可されていない窓: {kind!r}")


def validate_spec(spec: Any, known_refs: Optional[set[str]] = None) -> dict:
    """宣言的スペックを検証して正規化したコピーを返す。不正なら SpecError。"""
    if not isinstance(spec, dict):
        raise SpecError("spec は辞書である必要があります")
    op = spec.get("op")
    if op not in ALLOWED_OPS:
        raise SpecError(f"許可されていない演算: {op!r}")
    if op in ("diff", "pct_change"):
        if set(spec) != {"op", "inputs"}:
            raise SpecError(f"{op} は op と inputs のみ指定できます")
        inputs = spec["inputs"]
        if (not isinstance(inputs, list) or len(inputs) != 2
                or not all(isinstance(x, str) and "@" in x for x in inputs)):
            raise SpecError("inputs は 'feature_id@version' 形式の2要素リスト")
        if known_refs is not None:
            for ref in inputs:
                if ref not in known_refs:
                    raise SpecError(f"参照先の定義がありません: {ref}")
        return {"op": op, "inputs": list(inputs)}
    allowed_keys = {"op", "event", "window"} | set(_INT_PARAMS)
    extra = set(spec) - allowed_keys
    if extra:
        raise SpecError(f"許可されていない項目: {sorted(extra)}")
    if spec.get("event") not in ALLOWED_EVENTS:
        raise SpecError(f"許可されていない種目: {spec.get('event')!r}")
    _check_window(spec.get("window"))
    out = {"op": op, "event": spec["event"], "window": dict(spec["window"])}
    for k, (lo, hi) in _INT_PARAMS.items():
        if k in spec:
            v = spec[k]
            if type(v) is not int or not lo <= v <= hi:
                raise SpecError(f"{k} は {lo}〜{hi} の整数")
            out[k] = v
    if op == "median_latest_n" and "n" not in out:
        raise SpecError("median_latest_n には n が必要です")
    return out


@dataclass
class FeatureDefinition:
    feature_id: str
    version: int
    display_name: str
    category: str
    hypothesis: str
    event: str
    formula: str
    window: str
    min_n: str
    unit: str
    direction: str  # "小さいほど速い" / "大きいほど良い可能性" / "不明"
    required_columns: list[str]
    missing_policy: str
    exclusion: str
    time_constraint: str
    source: str
    author: str
    created_at: str
    review_status: str
    tests: list[str]
    spec: dict
    model_input_allowed: bool = True  # 品質表示専用（掲載量を反映）なら False
    caution: str = ""
    deprecation_reason: str = ""
    builtin: bool = False
    review_history: list[dict] = field(default_factory=list)

    @property
    def ref(self) -> str:
        return f"{self.feature_id}@{self.version}"

    def spec_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.spec, sort_keys=True).encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ref"] = self.ref
        d["spec_hash"] = self.spec_hash()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FeatureDefinition":
        fields_ = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**fields_)
