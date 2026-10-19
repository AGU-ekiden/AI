"""公開の公式記録（reference/）から、箱根の補完ファイルを自動で埋める（チームPCで実行）。

    python scripts/fill_hakone_supplement.py

- DB に区間記録が無い「出走年」のうち、公式記録がある年（現在は2025年）を対象に照合する。
- 氏名・大学・出走年がそろって1人に決まる行だけ埋める。それ以外は空欄のまま残し、理由を表示する。
- data/hakone_supplement.csv が既にあれば、記入済みの行は変更しない（空欄の行だけ埋める）。
- 出力は氏名入り（チームPCの外に出さない）。rkm は変更しない。
"""
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from labo.adapters.hakone_reference import default_reference_paths, load_reference, match, to_supplement_row  # noqa: E402
from labo.adapters.rkm_loader import SUPPLEMENT_COLUMNS, load_from_db, read_supplement_csv  # noqa: E402


def main() -> int:
    ref = load_reference(default_reference_paths(ROOT))
    ref_years = {r["run_year"] for r in ref}
    out = ROOT / "data" / "hakone_supplement.csv"
    existing = {(r["person_id"], str(r["run_year"])): r for r in read_supplement_csv(out)}
    ds, hakone, _ = load_from_db(supplement_path="__none__")
    have = {(lg.person_id, lg.edition_fy): lg for lg in hakone.legs}
    rows, stats, review = [], Counter(), []
    for pid in sorted(ds.athletes):
        for y in hakone.run_years.get(pid) or []:
            lg = have.get((pid, y - 1))
            if lg is not None and (lg.official_rank is not None or lg.reference_only):
                continue  # DB にある
            name, univ = ds.athletes[pid].name, hakone.universities.get(pid, "")
            prev = existing.get((pid, str(y)))
            if prev and (prev.get("leg") or prev.get("leg_rank")):
                rows.append(prev); stats["記入済み（変更せず）"] += 1; continue
            blank = {"person_id": pid, "name": name, "university": univ, "run_year": y, "leg": "",
                     "leg_rank": "", "is_student_alliance": "", "source_note": ""}
            if y not in ref_years:
                rows.append(blank); stats[f"公式記録なしの年（{y}）"] += 1; continue
            hit, why = match(name, univ, y, ref)
            if hit:
                rows.append(to_supplement_row(pid, name, univ, hit)); stats["自動で記入"] += 1
            else:
                rows.append(blank); stats[f"要確認：{why}"] += 1; review.append((y, name, univ, why))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=SUPPLEMENT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print("結果:", dict(stats))
    for y, name, univ, why in review:
        print(f"  要確認 {y} {name}（{univ}）: {why}")
    print(f"保存先（氏名入り・共有しない）: {out}")
    print("続けて python scripts/run_real_features.py を実行すると取り込まれます。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
