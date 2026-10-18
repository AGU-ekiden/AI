"""docs/features_v1.md を catalog.py から生成する（定義書と実装の食い違いを防ぐ）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from labo.catalog import builtin_definitions  # noqa: E402

out = ["# 初期15特徴量 定義書 v1（自動生成：scripts/gen_feature_doc.py）", "",
       "候補定義であり、予測力が実証済みという意味ではない。状態はすべて「計算可能」（研究で採用ではない）。", ""]
for i, d in enumerate(builtin_definitions(), 1):
    out += [f"## {i:02d} {d.feature_id}（{d.display_name}）", "",
            f"- 版: v{d.version} / カテゴリ: {d.category} / 単位: {d.unit} / 向き: {d.direction}",
            f"- 仮説: {d.hypothesis}", f"- 数式: {d.formula}", f"- 窓: {d.window}",
            f"- 必要件数: {d.min_n}", f"- 欠損処理: {d.missing_policy}",
            f"- 注意: {d.caution or '—'}",
            f"- モデル入力: {'可' if d.model_input_allowed else '不可（品質表示専用）'}",
            f"- テスト: {', '.join(d.tests) or '（tests/test_features.py の共通テスト）'}",
            f"- 宣言的定義: `{json.dumps(d.spec, ensure_ascii=False)}`", ""]
out += ["## 共通条件", "", builtin_definitions()[0].exclusion, "", builtin_definitions()[0].time_constraint, ""]
Path(__file__).resolve().parents[1].joinpath("docs/features_v1.md").write_text("\n".join(out), encoding="utf-8")
