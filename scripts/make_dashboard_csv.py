"""real_summary.json（集計のみ）から、スマホ用ダッシュボードのCSVを作る。

    python scripts/make_dashboard_csv.py [real_summary.json] [出力フォルダ]

既定は data/real_summary.json → data/dashboard/。出力は集計だけで、氏名・IDは含まない。
同じフォルダに eval_summary.json（scripts/run_evaluation.py の出力）があれば研究評価の表も作る。
特徴量の行は summary に入っている定義すべて（画面で承認した利用者定義を含む）。
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labo.research_view import build, build_eval  # noqa: E402


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


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
