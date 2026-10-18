"""最初の15特徴量（5000m中心）の候補定義 v1。予測力が実証済みという意味ではない。"""
from __future__ import annotations

from .definitions import FeatureDefinition, validate_spec

_COMMON_EXCL = ("本人照合済み・正常完走・正の数値タイム・5000m個人走・締切以前の実施日が確認できる結果のみ。"
                "駅伝/チーム/リレーの親レコード、3000mSC等の別種目、DNS/DNF/DSQ、未確認行は除外または保留。")
_COMMON_TIME = "観測締切C（既定：高2の8/31終了時点・日本時間）以前の実施日のみ。公表日不明時は競技日基準の再構成。"
_COMMON_COLS = ["records.event/event_group/distance_m", "records.date", "records.mark_raw/mark_value",
                "records.status", "profiles（本人照合）", "高校入学年度（根拠付き）"]
_H = {"kind": "hs"}


def _d(fid, name, cat, hyp, formula, window, min_n, unit, direction, spec, missing,
       model_input=True, caution="", tests=()):
    return FeatureDefinition(
        feature_id=fid, version=1, display_name=name, category=cat, hypothesis=hyp,
        event="5000m", formula=formula, window=window, min_n=min_n, unit=unit,
        direction=direction, required_columns=list(_COMMON_COLS), missing_policy=missing,
        exclusion=_COMMON_EXCL, time_constraint=_COMMON_TIME,
        source="依頼仕様書【6】の定義案", author="system(初期定義)",
        created_at="2026-10-18T00:00:00+09:00", review_status="計算可能",
        tests=list(tests), spec=validate_spec(spec, None), model_input_allowed=model_input,
        caution=caution, builtin=True,
    )


def builtin_definitions() -> list[FeatureDefinition]:
    defs = [
        _d("runs_5000_count", "観測できた有効5000m出走数", "観測量（品質表示）",
           "出走の観測量。掲載量・収集方式を反映するため品質表示専用。",
           "count(H内の有効5000m本人出走)", "H", "0件可", "件", "不明",
           {"op": "count", "event": "5000m", "window": _H},
           "取得済みで該当なし=0、対象人物の取得状態が不明ならnull",
           model_input=False, caution="出走機会や完全な年間出走数を意味しない",
           tests=["test_count_zero_vs_unknown"]),
        _d("observed_5000_span_days", "5000m観測期間（暦日）", "観測量（品質表示）",
           "記録が観測できる期間の長さ。", "最後の有効出走日 − 最初の有効出走日", "H", "1件以上",
           "日", "不明", {"op": "span_days", "event": "5000m", "window": _H},
           "0出走ならnull。1出走なら0", model_input=False, caution="競技歴ではない"),
        _d("days_since_last_5000", "最終5000m観測からの日数", "観測量（品質表示）",
           "直近の観測の有無。", "C − H内の最後の有効出走日", "H", "1件以上", "日", "不明",
           {"op": "days_since_last", "event": "5000m", "window": _H},
           "0出走ならnull。当日なら0", model_input=False,
           caution="故障・競技中断の推測に使わない"),
        _d("best_5000_s", "H内5000m最良記録", "記録水準", "高校観測期間の最良記録。",
           "min(秒)", "H", "1件以上", "秒", "小さいほど速い",
           {"op": "min", "event": "5000m", "window": _H, "min_n": 1},
           "0出走ならnull", caution="生涯ベストとは呼ばない", tests=["test_sc_not_in_3000_best"]),
        _d("best_5000_365d_s", "直近365日5000m最良", "記録水準", "直近1年の記録水準。",
           "min(秒)", "[C−364, C]∩H", "1件以上", "秒", "小さいほど速い",
           {"op": "min", "event": "5000m", "window": {"kind": "recent_days", "days": 365}, "min_n": 1},
           "窓内0出走ならnull", tests=["test_window_edges"]),
        _d("best_5000_180d_s", "直近180日5000m最良", "記録水準", "直近半年の記録水準。",
           "min(秒)", "[C−179, C]∩H", "1件以上", "秒", "小さいほど速い",
           {"op": "min", "event": "5000m", "window": {"kind": "recent_days", "days": 180}, "min_n": 1},
           "窓内0出走ならnull", tests=["test_window_edges"]),
        _d("grade1_best_5000_s", "高1年度5000m最良", "伸び", "高1時点の水準。",
           "min(秒)", "高1の4/1〜翌3/31 ∩ H", "1件以上", "秒", "小さいほど速い",
           {"op": "min", "event": "5000m", "window": {"kind": "grade", "grade": 1}, "min_n": 1},
           "学年の基準年度不明・0出走ならnull", tests=["test_grade_boundary"]),
        _d("grade2_best_5000_s", "高2年度（締切まで）5000m最良", "伸び", "高2時点の水準。",
           "min(秒)", "高2の4/1〜C", "1件以上", "秒", "小さいほど速い",
           {"op": "min", "event": "5000m", "window": {"kind": "grade", "grade": 2}, "min_n": 1},
           "0出走ならnull。締切（既定 高2の8/31）より後は含めない", tests=["test_grade_boundary"]),
        _d("grade1_to_grade2_improvement_s", "高1→高2の短縮（秒）", "伸び",
           "高1から高2への伸びが後の伸びと関係するか。", "07 − 08（正なら短縮）", "07/08に従う",
           "07・08が計算可能", "秒", "大きいほど短縮",
           {"op": "diff", "inputs": ["grade1_best_5000_s@1", "grade2_best_5000_s@1"]},
           "どちらかがnullならnull", caution="比較期間の観測件数と終了日を併記。8/31締切では高1=12か月・高2=5か月で期間長が異なる"),
        _d("grade1_to_grade2_improvement_pct", "高1→高2の短縮率", "伸び",
           "記録水準の違いを割合で比較。", "100×(07−08)/07", "07/08に従う",
           "07・08が計算可能かつ07>0", "%", "大きいほど短縮",
           {"op": "pct_change", "inputs": ["grade1_best_5000_s@1", "grade2_best_5000_s@1"]},
           "どちらかがnull、または07≦0ならnull", tests=["test_five_percent_example"]),
        _d("latest3_5000_median_s", "直近3出走の中央値", "安定性・直近",
           "自己ベストだけでなく直近の典型的水準。", "median(直近3出走の秒)", "H内の直近3出走",
           "3件以上", "秒", "小さいほど速い",
           {"op": "median_latest_n", "event": "5000m", "window": _H, "n": 3},
           "3出走未満null。境界が同日で順序不明ならambiguous_orderでnull",
           caution="最近の一定日数内の値ではない", tests=["test_latest_n", "test_ambiguous_order"]),
        _d("latest5_5000_median_s", "直近5出走の中央値", "安定性・直近",
           "直近の典型的水準（より多い件数）。", "median(直近5出走の秒)", "H内の直近5出走",
           "5件以上", "秒", "小さいほど速い",
           {"op": "median_latest_n", "event": "5000m", "window": _H, "n": 5},
           "5出走未満null。境界が同日で順序不明ならnull", tests=["test_latest_n"]),
        _d("iqr_5000_365d_s", "直近365日の記録のばらつき（IQR）", "安定性・直近",
           "記録の安定性。", "Q75−Q25（(n−1)×q 線形補間）", "[C−364, C]∩H",
           "4件以上かつ2大会以上", "秒", "不明",
           {"op": "iqr", "event": "5000m", "window": {"kind": "recent_days", "days": 365},
            "min_n": 4, "min_competitions": 2},
           "条件未満・大会ID欠落ならnull", caution="安定性の記述であって精神力ではない",
           tests=["test_iqr"]),
        _d("observed_5000_pb_updates_365d_count", "直近365日の観測最良更新日数", "伸び",
           "直近1年に記録を更新し続けているか。",
           "H全体で観測最小値を厳密に短縮した日のうち窓内の日数", "[C−364, C]∩H（基準はH全体）",
           "H内1件以上", "日", "不明",
           {"op": "pb_updates", "event": "5000m", "window": {"kind": "recent_days", "days": 365}},
           "H内0出走ならnull、窓内更新なしは0",
           caution="真の生涯PB更新回数ではない。同タイムは更新ではない", tests=["test_pb_updates"]),
        _d("median_5000_race_gap_365d_days", "直近365日の5000m出走日間隔の中央値", "観測量（品質表示）",
           "5000m観測出走日の間隔。", "窓内の異なる出走日の隣接差の中央値", "[C−364, C]∩H",
           "異なる日付3日以上", "日", "不明",
           {"op": "median_gap", "event": "5000m", "window": {"kind": "recent_days", "days": 365},
            "min_dates": 3},
           "異なる日付3日未満はnull", model_input=False,
           caution="大会間隔・練習頻度ではない", tests=["test_gap_median"]),
    ]
    return defs
