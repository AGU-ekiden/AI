"""将来フェーズ（研究評価）の土台。MVPでは実在選手への予測を行わない。

- 追跡期間が終わっていない世代を「不成功(0)」にしない。
- データが見つからないだけの人を確定不成功にしない。
- 同一人物の複数観測点が学習側と評価側に分かれないよう、人物単位・世代単位で分割する。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

LABEL_POSITIVE = "positive"
LABEL_NEGATIVE_CONFIRMED = "negative_confirmed"  # 追跡完了かつ不成功の根拠あり
LABEL_TRACKING = "tracking"                      # 追跡中（0扱いしない）
LABEL_UNKNOWN = "unknown"                        # 追跡完了だが根拠なし（0扱いしない）


def label_status(outcome_found: bool, tracking_end: date, as_of: date,
                 negative_evidence: bool = False) -> str:
    if outcome_found:
        return LABEL_POSITIVE
    if as_of <= tracking_end:
        return LABEL_TRACKING
    return LABEL_NEGATIVE_CONFIRMED if negative_evidence else LABEL_UNKNOWN


def trainable(label: str) -> Optional[int]:
    """学習に使える二値ラベル。追跡中・不明は None（学習から外す）。"""
    return {LABEL_POSITIVE: 1, LABEL_NEGATIVE_CONFIRMED: 0}.get(label)


def split_by_generation(person_generation: dict[str, int], train_until: int,
                        rows: list[tuple[str, object]]) -> tuple[list, list]:
    """古い世代で学習・新しい世代で検証。行は (person_id, payload)。人物単位で一方にのみ入る。"""
    train, test = [], []
    for pid, payload in rows:
        (train if person_generation[pid] <= train_until else test).append((pid, payload))
    assert not ({p for p, _ in train} & {p for p, _ in test})
    return train, test
