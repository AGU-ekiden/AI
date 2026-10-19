"""箱根の区間記録が DB に無い「出走年」の一覧を作る（チームPCで実行）。

    python scripts/make_hakone_supplement.py

出力：data/hakone_supplement.csv（氏名入り・チームPCの外に出さない）
各行の leg（区間 1〜10）と leg_rank（区間順位）を、公式結果を見て記入する。学生連合なら
is_student_alliance に 1 を入れ、leg_rank は空でよい。source_note に出典（例：関東学連 公式記録）を書く。
記入後に scripts/run_real_features.py を実行すると自動で取り込まれる（rkm は変更しない）。
既に同名のファイルがある場合は上書きせず、別名で保存する。
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from labo.adapters.rkm_loader import SUPPLEMENT_COLUMNS, load_from_db  # noqa: E402


def main() -> int:
    ds, hakone, _ = load_from_db(supplement_path="__none__")
    have = {}
    for lg in hakone.legs:
        have.setdefault(lg.person_id, {})[lg.edition_fy] = lg
    rows = []
    for pid in sorted(ds.athletes):
        for y in hakone.run_years.get(pid) or []:
            lg = have.get(pid, {}).get(y - 1)
            if lg is None or (lg.official_rank is None and not lg.reference_only):
                rows.append({"person_id": pid, "name": ds.athletes[pid].name,
                             "university": hakone.universities.get(pid, ""), "run_year": y, "leg": "", "leg_rank": "",
                             "is_student_alliance": "", "source_note": ""})
    out = ROOT / "data" / "hakone_supplement.csv"
    if out.exists():
        out = ROOT / "data" / "hakone_supplement_new.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=SUPPLEMENT_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    by_year = {}
    for r in rows:
        by_year[r["run_year"]] = by_year.get(r["run_year"], 0) + 1
    print(f"記入が必要な行：{len(rows)}（出走年別 {dict(sorted(by_year.items()))}）")
    print(f"保存先（氏名入り・共有しない）：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
