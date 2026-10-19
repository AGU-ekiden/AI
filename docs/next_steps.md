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

## C. Claude 側（real_summary.json を受け取った後）
1. 欠損理由・保留理由の内訳を確認し、想定外の多さがあれば原因を特定してルールを見直す。
2. 研究用の保存先（lab スキーマ）の作成案を最終確認 → 適用 → rkm の件数・ハッシュが不変か確認。
3. 評価計画（仕様書【10】）の確認に進むかを相談（予測はまだ行わない）。
