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


HINTS = [
    ("does not exist", "接続文字列の最後が「:5432/postgres」になっているか確認してください（データベース名は postgres）。"),
    ("password authentication failed", "パスワードが違います。supabase_setup.sql を最後に実行したときの lab_reader_pw を使ってください。"),
    ("Tenant or user not found", "ユーザー名が「lab_reader.<プロジェクトID>」の形か、Connect 画面の文字列を使っているか確認してください。"),
    ("timeout", "ネットワークで5432番ポートが遮断されている可能性があります。別の回線で試してください。"),
]


def main() -> int:
    try:
        report = run_audit()
    except UnsafeConnection as e:
        print("中止:", e)
        return 2
    except Exception as e:  # noqa: BLE001 - 接続文字列を出さないよう種類と1行目だけ表示
        msg = str(e)
        print("失敗:", type(e).__name__, msg.splitlines()[0] if msg else "")
        for key, hint in HINTS:
            if key in msg:
                print("ヒント:", hint)
        return 1
    report["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = ROOT / "data" / "audit_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    counts = dict(report["results"].get("row_counts", []))
    print("接続ユーザー:", report["safety"]["current_user"], "（rkm への書き込み権限なしを確認）")
    print("件数:", counts)
    print("失敗したクエリ:", list(report["errors"]) or "なし")
    rls = report["results"].get("rls_status", [])
    hidden = [r[0] for r in rls if r[1] and counts.get(r[0], 0) == 0]
    if hidden:
        print("注意: 次の表は RLS（行レベルセキュリティ）が有効で、lab_reader 用のポリシーがないため"
              "0件に見えている可能性があります:", ", ".join(hidden))
        print("      推定行数（統計）:", {r[0]: r[3] for r in rls if r[0] in hidden})
    elif counts and not any(counts.values()):
        print("注意: すべて0件です。陸マガデータがこのプロジェクトに入っているか確認してください。")
    print("保存先:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
