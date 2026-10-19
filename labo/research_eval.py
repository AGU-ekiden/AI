"""研究評価：特徴量の組み合わせが、箱根の成果（世代単位の集団）をどれだけ説明できるかを測る。

評価値は「世代順の検証での平均適合率（PR-AUC）」。
- 入学年度Yの人を評価するときは、Y より前の世代だけで学習する（未来の世代を使わない）。
- 全年度の評価結果を集めて1つの値にする。基準モデル（5000mベストのみ）との差＝特徴量の上積み。
- 学習・評価に使うのは「達成」と「未達成（確定）」だけ。追跡中・不明は使わない（0扱いしない）。
- 最新の世代は「最終確認用」に取り置き、特徴量を試す日常の評価では使わない（使い回しによる過大評価を防ぐ）。

出力は集計（評価値・係数・年度別人数・較正の区間別人数）だけ。個人ごとのスコア・確率・順位は
返さない・保存しない（仕様書：実在選手の成功確率・ランキングを作らない）。標準ライブラリのみ。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from statistics import median
from typing import Optional

from .evaluation import trainable


@dataclass
class EvalRow:
    entry_fy: int
    label: str                       # positive / negative_confirmed / tracking / unknown
    values: dict[str, Optional[float]]


@dataclass
class EvalConfig:
    baseline: list[str]
    candidates: list[str]
    first_test_fy: int = 2010        # これより前の世代は学習専用
    min_train_positives: int = 15    # 学習側の達成者がこれ未満の年度は評価しない
    holdout_from_fy: Optional[int] = 2018  # この年度以降は最終確認用（include_holdout で使う）
    include_holdout: bool = False
    l2: float = 5.0
    bootstrap: int = 500
    seed: int = 20261019
    calibration_bins: int = 5


# ---- 前処理（学習側だけで決める） ----
@dataclass
class Prep:
    refs: list[str]
    med: dict[str, float]
    add_missing: dict[str, bool]
    mean: list[float] = field(default_factory=list)
    sd: list[float] = field(default_factory=list)

    def raw(self, row: EvalRow) -> list[float]:
        x = []
        for r in self.refs:
            v = row.values.get(r)
            x.append(self.med[r] if v is None else float(v))
            if self.add_missing[r]:
                x.append(1.0 if v is None else 0.0)
        return x

    def vec(self, row: EvalRow) -> list[float]:
        return [(v - m) / s for v, m, s in zip(self.raw(row), self.mean, self.sd)]

    def names(self) -> list[str]:
        out = []
        for r in self.refs:
            out.append(r)
            if self.add_missing[r]:
                out.append(f"{r}:欠損")
        return out


def make_prep(train: list[EvalRow], refs: list[str]) -> Prep:
    med, add_missing = {}, {}
    for r in refs:
        vals = [float(row.values[r]) for row in train if row.values.get(r) is not None]
        med[r] = median(vals) if vals else 0.0
        add_missing[r] = 0 < len(vals) < len(train)
    p = Prep(refs, med, add_missing)
    cols = list(zip(*[p.raw(row) for row in train])) if train else []
    for c in cols:
        m = sum(c) / len(c)
        sd = math.sqrt(sum((v - m) ** 2 for v in c) / len(c))
        p.mean.append(m)
        p.sd.append(sd if sd > 1e-12 else 1.0)
    return p


# ---- L2 付きロジスティック回帰（ニュートン法） ----
def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[piv] = m[piv], m[c]
        if abs(m[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                if f:
                    m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] if abs(m[i][i]) > 1e-12 else 0.0 for i in range(n)]


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def fit_logistic(X: list[list[float]], y: list[int], l2: float = 1.0, iters: int = 50) -> list[float]:
    """係数 [切片, w1, ...]。切片には罰則をかけない。"""
    k = len(X[0]) + 1 if X else 1
    w = [0.0] * k
    rows = [[1.0] + x for x in X]
    for _ in range(iters):
        g = [0.0] * k
        h = [[0.0] * k for _ in range(k)]
        for x, t in zip(rows, y):
            p = _sigmoid(sum(a * b for a, b in zip(w, x)))
            d, q = p - t, p * (1 - p)
            for i in range(k):
                g[i] += d * x[i]
                hi = h[i]
                for j in range(i, k):
                    hi[j] += q * x[i] * x[j]
        for i in range(k):
            for j in range(i):
                h[i][j] = h[j][i]
            if i:
                g[i] += l2 * w[i]
                h[i][i] += l2
            h[i][i] += 1e-9
        step = _solve(h, g)
        w = [a - b for a, b in zip(w, step)]
        if max(abs(s) for s in step) < 1e-8:
            break
    return w


def predict(w: list[float], x: list[float]) -> float:
    return _sigmoid(w[0] + sum(a * b for a, b in zip(w[1:], x)))


# ---- 指標 ----
def average_precision(y: list[int], s: list[float]) -> Optional[float]:
    pos = sum(y)
    if pos == 0:
        return None
    pairs = sorted(zip(s, y), key=lambda t: -t[0])
    ap, tp, i = 0.0, 0, 0
    while i < len(pairs):  # 同点はまとめて扱う
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        grp = [t for _, t in pairs[i:j]]
        tp_new = tp + sum(grp)
        if sum(grp):
            ap += (tp_new - tp) / pos * (tp_new / j)
        tp, i = tp_new, j
    return ap


def roc_auc(y: list[int], s: list[float]) -> Optional[float]:
    pos = [v for v, t in zip(s, y) if t]
    neg = [v for v, t in zip(s, y) if not t]
    if not pos or not neg:
        return None
    ranked = sorted(s)
    rank: dict[float, float] = {}
    i = 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j] == ranked[i]:
            j += 1
        rank[ranked[i]] = (i + j + 1) / 2
        i = j
    return (sum(rank[v] for v in pos) - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def log_loss(y: list[int], p: list[float]) -> float:
    e = 1e-12
    return -sum(t * math.log(max(v, e)) + (1 - t) * math.log(max(1 - v, e)) for t, v in zip(y, p)) / len(y)


def brier(y: list[int], p: list[float]) -> float:
    return sum((v - t) ** 2 for t, v in zip(y, p)) / len(y)


# ---- 世代順の検証 ----
def labeled(rows: list[EvalRow], cfg: EvalConfig) -> list[tuple[EvalRow, int]]:
    out = []
    for r in rows:
        t = trainable(r.label)
        if t is None:
            continue
        if not cfg.include_holdout and cfg.holdout_from_fy is not None and r.entry_fy >= cfg.holdout_from_fy:
            continue
        out.append((r, t))
    return out


def forward_chain(data: list[tuple[EvalRow, int]], refs: list[str], cfg: EvalConfig):
    """年度ごとに「それより前の世代」で学習して当てはめた (年度, 正解, 予測) を返す（メモリ内のみ）。"""
    years = sorted({r.entry_fy for r, _ in data})
    out = []
    for yr in years:
        if yr < cfg.first_test_fy:
            continue
        train = [(r, t) for r, t in data if r.entry_fy < yr]
        test = [(r, t) for r, t in data if r.entry_fy == yr]
        if sum(t for _, t in train) < cfg.min_train_positives or not test:
            continue
        prep = make_prep([r for r, _ in train], refs)
        w = fit_logistic([prep.vec(r) for r, _ in train], [t for _, t in train], cfg.l2)
        out.extend((yr, t, predict(w, prep.vec(r))) for r, t in test)
    return out


def _metrics(pred) -> dict:
    y = [t for _, t, _ in pred]
    p = [v for _, _, v in pred]
    if not y:
        return {"n": 0}
    return {"n": len(y), "positives": sum(y), "pr_auc": average_precision(y, p), "roc_auc": roc_auc(y, p),
            "log_loss": log_loss(y, p), "brier": brier(y, p), "prevalence": sum(y) / len(y)}


def bootstrap_delta(pred_a, pred_b, n: int, seed: int) -> Optional[dict]:
    """同じ人を入れ替えずに組で再抽出し、PR-AUC の差（b − a）の95%区間を出す。"""
    if not pred_a or n <= 0:
        return None
    assert [(yr, t) for yr, t, _ in pred_a] == [(yr, t) for yr, t, _ in pred_b], "評価対象の人がそろっていない"
    rng = random.Random(seed)
    idx = list(range(len(pred_a)))
    diffs = []
    for _ in range(n):
        smp = [rng.choice(idx) for _ in idx]
        y = [pred_a[i][1] for i in smp]
        if not sum(y):
            continue
        da = average_precision(y, [pred_a[i][2] for i in smp])
        db = average_precision(y, [pred_b[i][2] for i in smp])
        diffs.append(db - da)
    if not diffs:
        return None
    diffs.sort()
    q = lambda f: diffs[min(len(diffs) - 1, int(f * len(diffs)))]  # noqa: E731
    return {"low": q(0.025), "high": q(0.975), "share_positive": sum(d > 0 for d in diffs) / len(diffs)}


def calibration(pred, bins: int) -> list[dict]:
    """予測の小さい順に等人数で区切った区間ごとの、平均予測と実際の達成割合（人数つき）。"""
    s = sorted(pred, key=lambda t: t[2])
    out = []
    for b in range(bins):
        part = s[b * len(s) // bins:(b + 1) * len(s) // bins]
        if part:
            out.append({"bin": b + 1, "n": len(part), "mean_pred": sum(v for _, _, v in part) / len(part),
                        "observed": sum(t for _, t, _ in part) / len(part)})
    return out


def evaluate(rows: list[EvalRow], cfg: EvalConfig, feature_info: Optional[dict] = None) -> dict:
    data = labeled(rows, cfg)
    full = list(dict.fromkeys(cfg.baseline + cfg.candidates))
    base_pred = forward_chain(data, cfg.baseline, cfg)
    full_pred = forward_chain(data, full, cfg)
    base_m, full_m = _metrics(base_pred), _metrics(full_pred)

    def delta(pred):
        m = _metrics(pred)
        if m.get("pr_auc") is None or base_m.get("pr_auc") is None:
            return None
        return m["pr_auc"] - base_m["pr_auc"]

    per_feature = []
    for ref in cfg.candidates:
        if ref in cfg.baseline:
            continue
        add = forward_chain(data, cfg.baseline + [ref], cfg)
        drop = forward_chain(data, [r for r in full if r != ref], cfg)
        dm = _metrics(drop)
        per_feature.append({
            "ref": ref, **(feature_info or {}).get(ref, {}),
            "add_to_baseline": delta(add),
            "add_ci": bootstrap_delta(base_pred, add, cfg.bootstrap // 5, cfg.seed),
            "drop_from_full": (full_m["pr_auc"] - dm["pr_auc"]) if dm.get("pr_auc") is not None and full_m.get("pr_auc") is not None else None,
            "coverage": sum(r.values.get(ref) is not None for r, _ in data) / len(data) if data else None,
        })
    per_feature.sort(key=lambda d: -(d["add_to_baseline"] or -1e9))

    coef = []
    if data and sum(t for _, t in data):
        prep = make_prep([r for r, _ in data], full)
        w = fit_logistic([prep.vec(r) for r, _ in data], [t for _, t in data], cfg.l2)
        coef = [{"term": n, "coef_per_sd": c} for n, c in zip(prep.names(), w[1:])]

    years = {}
    for r, t in data:
        y = years.setdefault(r.entry_fy, {"n": 0, "positives": 0})
        y["n"] += 1
        y["positives"] += t
    tested = sorted({yr for yr, _, _ in full_pred})
    return {
        "score_name": "世代順の検証での平均適合率（PR-AUC）",
        "score": full_m.get("pr_auc"),
        "baseline_score": base_m.get("pr_auc"),
        "gain_over_baseline": (full_m["pr_auc"] - base_m["pr_auc"]) if full_m.get("pr_auc") is not None and base_m.get("pr_auc") is not None else None,
        "gain_ci": bootstrap_delta(base_pred, full_pred, cfg.bootstrap, cfg.seed),
        "baseline": base_m, "full": full_m,
        "features_used": full, "baseline_features": cfg.baseline,
        "per_feature": per_feature,
        "coefficients_all_dev_years": coef,
        "calibration": calibration(full_pred, cfg.calibration_bins),
        "years": {str(k): v for k, v in sorted(years.items())},
        "tested_years": tested,
        "config": {"first_test_fy": cfg.first_test_fy, "min_train_positives": cfg.min_train_positives,
                   "holdout_from_fy": cfg.holdout_from_fy, "include_holdout": cfg.include_holdout,
                   "l2": cfg.l2, "bootstrap": cfg.bootstrap, "seed": cfg.seed},
        "excluded_labels": sum(1 for r in rows if trainable(r.label) is None),
    }
