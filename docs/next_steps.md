# 次にやること（2026-10-19 更新）

## いまの状態
- 実データ（rkm）を読み取り専用で読み、15特徴量を計算するところまで実装済み（模擬DBで全経路を確認）。
- 対応ルール（日付・学年・重複・種目・状態・箱根）はすべて決定済み（docs/decisions.md）。

## A. 利用者側：チームPCで実データの計算を実行
1. ZIP をダウンロードし直して展開し、そのフォルダでターミナルを開く。
2. 実行：
   ```powershell
   $env:RKM_READONLY_DSN = "（lab_reader の接続文字列）"
   python scripts/run_real_features.py
   ```
3. できるファイル：
   - `data\real_summary.json` … 集計のみ（氏名・IDなし）。**これを Claude に共有**。
   - `data\real_features.csv` … 氏名入り。**チームPCの外に出さない**。
4. 手計算との突き合わせ（数名）：
   ```powershell
   python scripts/run_real_features.py --person <person_id>
   ```
   表示された 5000m の採用・除外の一覧と特徴量の値を、陸マガの選手ページと見比べる。

## B. 画面で実データを見る（任意）
```powershell
$env:LABO_DATA_SOURCE = "rkm"
python -m labo.server
```
初回は data\.token のトークンでログイン。VPN 内のメンバーに見せる場合は LABO_HOST に VPN のアドレスを指定。
スマホから見る手順（集計ダッシュボード・VPN経由）は docs/mobile_access.md。

## B2. 箱根の記録欠けを補う
2025年（第101回）は公式記録を reference/ に取り込み済み。自動で埋める：
```powershell
python scripts/fill_hakone_supplement.py      # 氏名・大学・出走年が一致した行を自動記入、残りは「要確認」と表示
python scripts/run_real_features.py           # 取り込んで再計算
```
自動で決まらなかった行や、2025年以外の年は、下の手順で手入力する。

### 手入力の手順
```powershell
python scripts/make_hakone_supplement.py     # data\hakone_supplement.csv（氏名入り・共有しない）ができる
```
Excel で開き、各行の leg（区間 1〜10）と leg_rank（区間順位）を公式結果から記入。学生連合なら is_student_alliance に 1
（leg_rank は空でよい）。source_note に出典。保存（CSV UTF-8）後に `python scripts/run_real_features.py` を実行すると取り込まれる。

## B3. 特徴量を増やすときの流れ
1. 画面（特徴量作成）で定義を作る → 定義確認 → テスト済み → もう1人が「計算可能」にする
   （1人で使う間は `LABO_REQUIRE_SECOND_REVIEWER=false`）。
2. チームPCで `python scripts/run_real_features.py` を再実行。承認済みの利用者定義も自動で入る
   （未承認・廃止は入らず、画面に「対象外」と表示）。既存の特徴量の定義・過去の結果は変わらない。
3. `data\real_summary.json` を Claude に渡す → スマホ用ダッシュボードの表を更新
   （Claude 側は `scripts/make_dashboard_csv.py` で作る）。

## B4. 研究評価（評価値を出す）
```powershell
python scripts/run_evaluation.py
```
評価値（PR-AUC）と、5000mベストだけの基準との差、特徴量ごとの上積みが表示される。`data\eval_summary.json`（集計のみ）を Claude に共有。
特徴量を増やしたら B3 → これを再実行。方法は docs/evaluation_plan.md。

## C. Claude 側（real_summary.json を受け取った後）
1. 欠損理由・保留理由の内訳を確認し、想定外の多さがあれば原因を特定してルールを見直す。
2. 研究用の保存先（lab スキーマ）の作成案を最終確認 → 適用 → rkm の件数・ハッシュが不変か確認。
3. 評価計画（仕様書【10】）の確認に進むかを相談（予測はまだ行わない）。
