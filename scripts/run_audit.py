"""rkm の読み取り専用監査を実行し、秘密を含まない報告を data/audit_report.json に保存する。

チームPCで実行：
    pip install -r requirements-db.txt
    （環境変数 RKM_READONLY_DSN に lab_reader の接続文字列を設定してから）
    python scripts/run_audit.py

接続文字列は表示・保存しない。氏名などの個人情報は取得しない（件数・列名・語彙のみ）。
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from labo.adapters.rkm_readonly import UnsafeConnection, run_audit  # noqa: E402


def main() -> int:
    try:
        report = run_audit()
    except UnsafeConnection as e:
        print("中止:", e)
        return 2
    except Exception as e:  # noqa: BLE001 - 接続文字列を出さないよう種類と1行目だけ表示
        print("失敗:", type(e).__name__, str(e).splitlines()[0] if str(e) else "")
        return 1
    report["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = ROOT / "data" / "audit_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    counts = dict(report["results"].get("row_counts", []))
    print("接続ユーザー:", report["safety"]["current_user"], "（rkm への書き込み権限なしを確認）")
    print("件数:", counts)
    print("失敗したクエリ:", list(report["errors"]) or "なし")
    print("保存先:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
