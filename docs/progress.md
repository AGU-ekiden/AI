# 進捗表（2026-10-19）

凡例：**提案のみ**＝設計・案だけ／**承認済み**＝利用者が承認／**実装済み**＝コードあり／**実行確認済み**＝テストまたは画面で動作確認

| 項目 | 状態 | 根拠 |
|---|---|---|
| 15特徴量の計算（合成データ） | 実行確認済み | tests/test_features.py |
| 行単位の品質判定（採用/除外/保留） | 実行確認済み | 同上 |
| 締切・学年・窓（既定 高2の8/31／高2の7/31／高2年度末） | 承認済み・実行確認済み | tests/test_decisions.py（8/31は利用者決定） |
| チーム利用（個人トークン・役割・相互確認・操作者記録） | 実行確認済み | test_roles_and_disabled_users, test_second_member_must_approve_user_definitions |
| 成果ラベル hakone_leg_top@3（学生連合は区間順位の扱いから除く） | 承認済み（定義）・実装済み（部品） | tests/test_decisions.py。実データ・予測には未使用 |
| 成果の追跡期間 | 承認済み | 高校入学年度+3年度から4大会 |
| 日付・学年・重複・箱根の対応ルール | 承認済み・実装済み（テスト） | labo/adapters/rkm_mapping.py、tests/test_decisions.py |
| 推奨構成（lab_reader / lab_writer） | 承認済み・SQLは再実行可能（作成・修復）で**模擬DBで4状態を検証済み**・**本番で作成済み（2026-10-19 利用者実行）** | docs/supabase_setup.sql（Postgres 16・非スーパーユーザーで確認） |
| 監査スクリプト（書き込み可能な接続なら中止） | 実装済み・模擬DBで確認 | scripts/run_audit.py。本番データでは未実行 |
| 運用：チームPC＋VPN | 承認済み | docs/decisions.md 2026-10-19 |
| 母集団の版管理（締切時点情報のみ） | 実行確認済み | test_cohort_*, test_cohort_plan_* |
| 版付き定義・状態遷移・判断履歴 | 実行確認済み | test_store_server.py |
| 計算ジョブ（取消・再開・重複なし） | 実行確認済み | test_rerun_and_resume_do_not_duplicate |
| Web 7画面・CSV出力・認証 | 実行確認済み | ServerTests ＋ Chromium で操作確認（PC/スマホ幅・JSエラーなし） |
| 駅伝本人区間・区間ペース | 実装済み（部品のみ） | test_ekiden_self_leg_vs_pass_time。特徴量としては未定義 |
| 将来評価用ラベル・世代分割 | 実装済み（土台のみ） | test_future_labels_* |
| 研究評価（世代順の検証・PR-AUC・基準比較・特徴量ごとの上積み） | 承認済み・実装済み（合成データでテスト）・**実データでは未実行** | labo/research_eval.py、scripts/run_evaluation.py、tests/test_research_eval.py。個人ごとの値は出さない |
| AIによる定義案 | 提案のみ（段階4） | 画面に「未実装」と表示 |
| rkm 読み取り専用監査 | 実装済み・本番で接続成功。lab_reader 用読み取りポリシーを全10表に追加済み（2026-10-19 利用者実行）・**監査実行済み（件数は参考値と完全一致：docs/audit_baseline.md）** | 利用者がチームPCで実行（docs/next_steps.md A-3） |
| rkm → 研究用モデルの読み込み | **実データで実行確認済み（2026-10-19 第1・2回）** | labo/adapters/rkm_loader.py、tests/test_rkm_loader.py |
| 実データでの15特徴量計算・集計 | **実行確認済み（第1〜4回 2026-10-19、docs/real_runs.md）** |
| 箱根の記録欠けの補完 | 実装済み・2025年分を実データで取り込み確認（90件） | reference/hakone_2025_official.tsv、scripts/fill_hakone_supplement.py | scripts/run_real_features.py（集計は氏名・IDなし） |
| Web画面の実データ表示 | 実装済み（LABO_DATA_SOURCE=rkm） | 模擬DBで起動・表示を確認 |
| 研究用DBスキーマ | 方針は承認済み・**未実行** | docs/migration_proposal.sql（lab_writer で実行する案） |
| 既存rkmの不変確認（前後ハッシュ） | 「前」を記録済み（records_hash 356d362b…） | docs/audit_baseline.md。研究用保存先の作成後に「後」を確認 |
| 第2弾の特徴量（中学3000m/1500m・高校3000m/1500m・駅伝の区間順位 11件） | 実装済み（テスト・模擬DBで確認）・状態「テスト済み」＝**利用者が「計算可能」にすると実データで計算** | labo/catalog.py phase2_definitions、tests/test_phase2.py |
| ペース比・splits・3000mSC | 未実装・保留 | 種目・日時・本人・単位の検証後 |
