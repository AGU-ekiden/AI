# 進捗表（2026-10-18）

凡例：**提案のみ**＝設計・案だけ／**承認済み**＝利用者が承認／**実装済み**＝コードあり／**実行確認済み**＝テストまたは画面で動作確認

| 項目 | 状態 | 根拠 |
|---|---|---|
| 15特徴量の計算（合成データ） | 実行確認済み | tests/test_features.py |
| 行単位の品質判定（採用/除外/保留） | 実行確認済み | 同上 |
| 締切・学年・窓（既定 高2の8/31／高2の7/31／高2年度末） | 承認済み・実行確認済み | tests/test_decisions.py（8/31は利用者決定） |
| チーム利用（個人トークン・役割・相互確認・操作者記録） | 実行確認済み | test_roles_and_disabled_users, test_second_member_must_approve_user_definitions |
| 成果ラベル hakone_leg_top@1 | 承認済み（定義）・実装済み（部品） | tests/test_decisions.py。実データ・予測には未使用 |
| 成果の追跡期間・参考記録の扱い | 提案のみ | docs/decisions.md「未確定」 |
| 推奨構成（lab_reader / lab_writer） | 承認済み（方針）・**未実行** | docs/supabase_setup.sql を利用者が実行する |
| 母集団の版管理（締切時点情報のみ） | 実行確認済み | test_cohort_*, test_cohort_plan_* |
| 版付き定義・状態遷移・判断履歴 | 実行確認済み | test_store_server.py |
| 計算ジョブ（取消・再開・重複なし） | 実行確認済み | test_rerun_and_resume_do_not_duplicate |
| Web 7画面・CSV出力・認証 | 実行確認済み | ServerTests ＋ Chromium で操作確認（PC/スマホ幅・JSエラーなし） |
| 駅伝本人区間・区間ペース | 実装済み（部品のみ） | test_ekiden_self_leg_vs_pass_time。特徴量としては未定義 |
| 将来評価用ラベル・世代分割 | 実装済み（土台のみ） | test_future_labels_*。予測モデルはなし |
| AIによる定義案 | 提案のみ（段階4） | 画面に「未実装」と表示 |
| rkm 読み取り専用監査 | 実装済み・**未実行** | 接続情報なし。SQLの読み取り専用性のみテスト |
| rkm → 正規化アダプター | 提案のみ | docs/plan.md の対応表（未確認） |
| 研究用DBスキーマ | 方針は承認済み・**未実行** | docs/migration_proposal.sql（lab_writer で実行する案） |
| 既存rkmの不変確認（前後ハッシュ） | 提案のみ | 監査クエリ `records_hash` を用意。DB未接続のため未実施 |
| フェーズ2特徴量（1500m/3000m/SC/ペース比/splits） | 未実装・保留 | 種目・日時・本人・単位の検証後 |
