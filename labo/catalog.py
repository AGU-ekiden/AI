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


# ---- 第2弾：中学の記録・高校の他種目・駅伝（2026-10-19 利用者の提案）----
# 状態は「テスト済み」。画面のファクター一覧で「計算可能」にすると実データの計算・研究評価に入る。
_J = {"kind": "junior"}
_EK_COLS = ["records.event_group='ekiden'・competition_raw（大会区分）", "records.ekiden_leg/ekiden_leg_rank",
            "ekiden_legs.is_self/leg/leg_rank（records に区間が無い場合）", "高校入学年度（根拠付き）"]


def _p2(fid, name, cat, hyp, formula, window, min_n, unit, direction, spec, missing,
        model_input=True, caution="", event=None, cols=None):
    d = _d(fid, name, cat, hyp, formula, window, min_n, unit, direction, spec, missing,
           model_input=model_input, caution=caution)
    d.event = event or spec.get("event", "駅伝")
    d.source = "利用者の提案（中学・駅伝の影響）2026-10-19"
    d.created_at = "2026-10-19T00:00:00+09:00"
    d.review_status = "テスト済み"
    if cols:
        d.required_columns = list(cols)
    if spec["op"] in ("ekiden_count", "ekiden_best_rank"):
        d.exclusion = ("本人照合済みプロフィールの本人区間のみ。記録なし・棄権は除外。区間が複数で本人区間が"
                       "決まらない行は区間順位なし。プロフィール間の同じ区間は1つにまとめる。")
    return d


def phase2_definitions() -> list[FeatureDefinition]:
    jcaution = "中学の記録は掲載が少なく、記録が無い＝遅いではない（欠損は「掲載なし」）"
    rcaution = "区間ごとに距離・出場校数が違い、出場自体が学校・地域の強さに左右される"
    return [
        _p2("junior_best_3000_s", "中学3000m最良", "中学", "中学時代の3000mの水準が大学での活躍と関係する。",
            "min(J内の有効3000m)", "J（中1の4/1〜中3の3/31）", "1件以上", "秒", "小さいほど速い",
            {"op": "min", "event": "3000m", "window": _J}, "J内0件ならnull", caution=jcaution),
        _p2("junior3_best_3000_s", "中3年度3000m最良", "中学", "中3時点の3000mの水準。",
            "min(中3年度の有効3000m)", "中3の4/1〜3/31", "1件以上", "秒", "小さいほど速い",
            {"op": "min", "event": "3000m", "window": {"kind": "junior_grade", "grade": 3}},
            "中3年度0件ならnull", caution=jcaution),
        _p2("junior_best_1500_s", "中学1500m最良", "中学", "中学時代の1500mの水準（スピード）。",
            "min(J内の有効1500m)", "J", "1件以上", "秒", "小さいほど速い",
            {"op": "min", "event": "1500m", "window": _J}, "J内0件ならnull", caution=jcaution),
        _p2("hs_best_3000_s", "H内3000m最良", "記録水準（他種目）", "高校での3000mの水準。",
            "min(H内の有効3000m)", "H", "1件以上", "秒", "小さいほど速い",
            {"op": "min", "event": "3000m", "window": _H}, "H内0件ならnull",
            caution="高校で3000mを走る機会は限られる"),
        _p2("hs_best_1500_s", "H内1500m最良", "記録水準（他種目）", "高校での1500mの水準（スピード）。",
            "min(H内の有効1500m)", "H", "1件以上", "秒", "小さいほど速い",
            {"op": "min", "event": "1500m", "window": _H}, "H内0件ならnull"),
        _p2("national_hs_ekiden_best_rank", "全国高校駅伝の最高区間順位", "駅伝",
            "全国高校駅伝で区間上位に入る力が大学駅伝につながる。",
            "min(H内の全国高校駅伝の本人区間の区間順位)", "H（締切までに走れるのは高1の大会）", "1区間以上",
            "位", "小さいほど上位", {"op": "ekiden_best_rank", "race": "national_hs", "window": _H},
            "出場なし・未掲載はnull（区別しない）", caution=rcaution, cols=_EK_COLS),
        _p2("national_hs_ekiden_legs", "全国高校駅伝の出走区間数", "駅伝", "全国高校駅伝の出場経験。",
            "count(H内の全国高校駅伝の本人区間)", "H", "0件可", "区間", "不明",
            {"op": "ekiden_count", "race": "national_hs", "window": _H},
            "取得済みで該当なし=0", caution=rcaution + "。0は出場していないか未掲載", cols=_EK_COLS),
        _p2("todofuken_hs_best_rank", "都道府県駅伝（高校）の最高区間順位", "駅伝",
            "都道府県代表として区間上位に入る力。", "min(H内の全国都道府県対抗男子駅伝の本人区間の区間順位)",
            "H", "1区間以上", "位", "小さいほど上位",
            {"op": "ekiden_best_rank", "race": "todofuken", "window": _H},
            "出場なし・未掲載はnull", caution=rcaution, cols=_EK_COLS),
        _p2("todofuken_junior_best_rank", "都道府県駅伝（中学）の最高区間順位", "駅伝",
            "中学生区間で区間上位に入る力。", "min(J内の全国都道府県対抗男子駅伝の本人区間の区間順位)",
            "J", "1区間以上", "位", "小さいほど上位",
            {"op": "ekiden_best_rank", "race": "todofuken", "window": _J},
            "出場なし・未掲載はnull", caution=rcaution + "。" + jcaution, cols=_EK_COLS),
        _p2("ina_ekiden_best_rank", "春の高校伊那駅伝の最高区間順位", "駅伝",
            "全国から多くの学校が出る春の伊那駅伝で区間上位に入る力。",
            "min(H内の春の高校伊那駅伝の本人区間の区間順位)", "H（締切までに走れるのは高1の3月の大会）",
            "1区間以上", "位", "小さいほど上位", {"op": "ekiden_best_rank", "race": "ina", "window": _H},
            "出場なし・未掲載はnull", caution=rcaution, cols=_EK_COLS),
        _p2("regional_hs_ekiden_best_rank", "県・地区高校駅伝の最高区間順位", "駅伝",
            "県・地区の高校駅伝での区間順位。", "min(H内の都道府県・地区の高校駅伝の本人区間の区間順位)",
            "H", "1区間以上", "位", "小さいほど上位",
            {"op": "ekiden_best_rank", "race": "regional_hs", "window": _H},
            "出場なし・未掲載はnull", caution=rcaution + "。大会ごとに出場校数が大きく違う", cols=_EK_COLS),
    ]
