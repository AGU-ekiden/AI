"""特徴量の状態をまとめて変更する（画面のファクター一覧の「状態を変更」と同じ記録が残る）。

    python scripts/approve_features.py --phase2                 # 第2弾（中学・駅伝）11件を「計算可能」に
    python scripts/approve_features.py --adopt hs_best_3000_s@1  # 「研究で採用」に（評価値のセットに入る）
    python scripts/approve_features.py --list                    # 状態の一覧

判断は data/review_decisions.jsonl に理由・日時つきで残る。rkm（本番DB）には触れない。
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labo.catalog import phase2_definitions  # noqa: E402
from labo.definitions import SpecError  # noqa: E402
from labo.store import Store  # noqa: E402

ACTOR = "admin(コマンド)"


def change(store: Store, refs: list[str], to: str, reason: str) -> int:
    failed = 0
    for ref in refs:
        d = store.definition(ref)
        if d is None:
            print(f"  見つからない: {ref}")
            failed += 1
            continue
        if d.review_status == to or (to == "計算可能" and d.review_status == "研究で採用"):
            print(f"  すでに「{d.review_status}」: {d.display_name}")
            continue
        try:
            store.change_status(ref, to, reason, ACTOR)
            print(f"  {d.review_status} → {to}: {d.display_name}（{ref}）")
        except SpecError as e:
            print(f"  変更できない: {d.display_name}（{ref}）… {e}")
            failed += 1
    return failed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase2", action="store_true", help="第2弾の11件を「計算可能」にする")
    ap.add_argument("--approve", nargs="*", default=[], help="「計算可能」にする ref")
    ap.add_argument("--adopt", nargs="*", default=[], help="「研究で採用」にする ref（計算可能のものだけ）")
    ap.add_argument("--list", action="store_true", help="状態の一覧を表示")
    ap.add_argument("--reason", default="", help="判断理由（記録に残る）")
    ap.add_argument("--data-dir", default=os.environ.get("LABO_DATA_DIR", str(ROOT / "data")))
    args = ap.parse_args()
    store = Store(Path(args.data_dir))
    failed = 0
    approve = list(args.approve) + ([d.ref for d in phase2_definitions()] if args.phase2 else [])
    if approve:
        print("「計算可能」にする:")
        failed += change(store, approve, "計算可能", args.reason or "第2弾（中学・駅伝）を実データで計算する")
    if args.adopt:
        print("「研究で採用」にする:")
        failed += change(store, args.adopt, "研究で採用", args.reason or "研究評価で上積みを確認")
    if args.list or not (approve or args.adopt):
        for d in store.definitions():
            print(f"  {d.review_status:6}  {d.ref:42} {d.display_name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
