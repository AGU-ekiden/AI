"""real_summary.json（集計のみ）から、スマホ用ダッシュボードのCSVを作る。

    python scripts/make_dashboard_csv.py [real_summary.json] [出力フォルダ]

既定は data/real_summary.json → data/dashboard/。出力は集計だけで、氏名・IDは含まない。
同じフォルダに eval_summary.json（scripts/run_evaluation.py の出力）があれば研究評価の表も作る。
特徴量の行は summary に入っている定義すべて（画面で承認した利用者定義を含む）。
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labo.catalog import builtin_definitions  # noqa: E402
from labo.features import MISSING_LABELS  # noqa: E402
from labo.quality import REASON_LABELS  # noqa: E402

DECISION_TEXT = {"used": "採用", "excluded": "除外", "held": "保留"}
STATUS_TEXT = {"DNS": "DNS（出走せず）", "DNF": "DNF（途中棄権）", "DSQ": "DSQ（失格）", "DQ": "DQ（失格）"}
OUTCOME_TEXT = {"positive": "達成", "negative_confirmed": "未達成（確定）", "tracking": "追跡中", "unknown": "不明"}
ENTRY_REASON_TEXT = {"derived_from_grade": "入学年度：学年から算出", "majority_of_grades": "入学年度：多数決"}


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _num(v):
    return "" if v is None else v


def build(summary: dict) -> dict[str, tuple[list[str], list[list]]]:
    total = summary["cohort"]["included"]
    load = summary["load"]
    overview = [["対象人数", total], ["入学年度不明で除外", sum(summary["cohort"]["excluded"].values())]]
    overview += [[ENTRY_REASON_TEXT[k], load["entry_year_reasons"].get(k, 0)] for k in ENTRY_REASON_TEXT]
    overview += [["5000m 採用行", summary["decisions_5000m"].get("used:ok", 0)],
                 ["重複としてまとめた行", load["duplicate_links"]],
                 ["箱根の補完（取り込み）", load["hakone_supplement"]["used"]],
                 ["特徴量の数", len(summary["features"])]]

    builtin = {d.ref: d for d in builtin_definitions()}
    features = []
    for ref, f in summary["features"].items():
        d = builtin.get(ref)  # 第4回以前の summary は名前などを持たないので初期定義から補う
        name = f.get("name") or (d.display_name if d else ref)
        category = f.get("category") or (d.category if d else "")
        unit = f.get("unit") or (d.unit if d else "")
        mi = f.get("model_input", d.model_input_allowed if d else True)
        miss = Counter({k: v for k, v in f["reasons"].items() if k != "ok"}).most_common(1)
        q = f.get("quantiles") or {}
        features.append([ref.split("@")[0], name, category, unit, "可" if mi else "品質表示専用",
                         f["non_null"], total,
                         MISSING_LABELS.get(miss[0][0], miss[0][0]) if miss else "", miss[0][1] if miss else "",
                         _num(q.get("p10")), _num(q.get("p50")), _num(q.get("p90"))])

    outcomes = []
    for k, v in summary["outcome_labels_by_entry_fy"].items():
        fy, label = k.split(":", 1)
        if fy.isdigit():
            outcomes.append([fy, OUTCOME_TEXT.get(label, label), v])

    decisions = []
    for k, v in summary["decisions_5000m"].items():
        dec, reason = k.split(":", 1)
        decisions.append([DECISION_TEXT.get(dec, dec), REASON_LABELS.get(reason, STATUS_TEXT.get(reason, reason)), v])

    gaps = [k.split(":", 1) + [v] for k, v in summary["hakone_gaps_by_run_year"].items()]
    return {
        "overview.csv": (["metric", "value"], overview),
        "features.csv": (["feature_id", "name", "category", "unit", "model_input", "non_null", "total",
                          "top_missing_reason", "top_missing_count", "p10", "p50", "p90"], features),
        "outcomes.csv": (["entry_fy", "label", "count"], outcomes),
        "decisions_5000m.csv": (["decision", "reason", "count"], decisions),
        "hakone_gaps.csv": (["run_year", "kind", "count"], gaps),
    }


def build_eval(ev: dict, history: list[dict]) -> dict[str, tuple[list[str], list[list]]]:
    """研究評価（eval_summary.json・eval_history.jsonl）の表。集計のみ。"""
    ci = ev.get("gain_ci") or {}
    score = [["評価値（PR-AUC）", _num(ev.get("score"))], ["基準（5000mベストのみ）", _num(ev.get("baseline_score"))],
             ["上積み", _num(ev.get("gain_over_baseline"))], ["上積み95%区間・下", _num(ci.get("low"))],
             ["上積み95%区間・上", _num(ci.get("high"))], ["達成の割合（偶然の水準）", _num(ev["full"].get("prevalence"))],
             ["評価した人数", _num(ev["full"].get("n"))], ["うち達成", _num(ev["full"].get("positives"))],
             ["使った特徴量の数", len(ev.get("features_used", []))]]
    used = set(ev.get("features_used", []))
    feats = []
    for p in ev.get("per_feature", []):
        in_set = p.get("in_set", p["ref"] in used)
        set_ci = p.get("add_to_set_ci") or {}
        feats.append([p["ref"].split("@")[0], p.get("name", p["ref"]), "セット内" if in_set else "候補",
                      _num(p.get("add_to_baseline")), _num((p.get("add_ci") or {}).get("low")),
                      _num((p.get("add_ci") or {}).get("high")), _num(p.get("add_to_set")),
                      _num(set_ci.get("low")), _num(set_ci.get("high")), _num(p.get("drop_from_full")),
                      _num(p.get("coverage"))])
    hist = [[h["generated_at"], h.get("n_features"), _num(h.get("score")), _num(h.get("baseline_score")),
             "最終確認" if h.get("final_check") else "通常", h.get("note", "")] for h in history]
    return {
        "eval_score.csv": (["metric", "value"], score),
        "eval_features.csv": (["feature_id", "name", "role", "add_to_baseline", "add_low", "add_high",
                               "add_to_set", "set_low", "set_high", "drop_from_full", "coverage"], feats),
        "eval_history.csv": (["at", "n_features", "score", "baseline_score", "kind", "note"], hist),
    }


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "real_summary.json"
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "dashboard"
    out.mkdir(parents=True, exist_ok=True)
    tables = build(json.loads(src.read_text(encoding="utf-8")))
    ev_path = src.parent / "eval_summary.json"
    if ev_path.exists():
        hp = src.parent / "eval_history.jsonl"
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
        history = ([json.loads(x) for x in hp.read_text(encoding="utf-8").splitlines() if x.strip()] if hp.exists()
                   else [{**ev, "n_features": len(ev.get("features_used", []))}])
        tables.update(build_eval(ev, history))
    for name, (header, rows) in tables.items():
        _write(out / name, header, rows)
        print(f"{out / name}（{len(rows)}行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
