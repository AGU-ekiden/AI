# 特徴量ラボ（選手育成研究・非公開）

高校2年ごろまでの競技記録から、大学長距離・箱根駅伝につながる特徴を**継続研究するための**
特徴量の定義・計算・確認・版管理の基盤です。予測・ランキング・選抜判定は行いません。

> 現在は **段階1：合成データMVP** です。表示される選手・大会・値はすべて架空です。
> 実DB（Supabase の `rkm` スキーマ）には接続していません。

## できること（段階1）

- 初期15特徴量（5000m中心）の純粋な計算処理と、値ごとの件数・対象期間・使用行ID・欠損理由
- 行単位の品質判定（採用／除外／保留と理由）。原本は変更しない
- 観測締切（既定：**高2の8/31**、切替：高2の7/31・高2年度末）と時点制約。締切後の情報を使わない
- 版付きの特徴量定義（宣言的・許可済み演算のみ）、状態遷移と判断履歴
- 計算ジョブ（バックグラウンド・取消・再開・同一条件の再実行は重複しない）
- Web画面8種：**研究状況**（評価値・特徴量ごとの上積み・承認ボタン・実データで再計算・再評価）／研究トップ／ファクター一覧／特徴量作成／計算実行／結果確認／実験履歴／品質・保留
- CSVエクスポート（合成データである旨を先頭行に明記）
- チーム利用：個人別トークン、役割（管理者／研究担当／閲覧のみ）、操作者の記録、作成者以外による承認
- 成果ラベル定義 `hakone_leg_top@3`（往路区間5位以内／復路区間2位以内、学生連合は除く）のラベル付け部品。予測はしない

## セットアップ

依存パッケージはありません（Python 3.11 以上・標準ライブラリのみ。3.13.16 で確認）。

```bash
python3 -m unittest discover -s tests -t .   # テスト（101件）
python3 -m labo.server                        # http://127.0.0.1:8765/
python3 -m labo.users add --name 氏名 --role editor   # メンバー追加（トークンは一度だけ表示）
```

- 初回起動時に管理者が作られ、そのトークンが `data/.token`（権限600）に保存されます。ログイン後は削除して構いません。
- 役割：`admin`（管理者）／`editor`（研究担当：定義作成・判断記録・計算実行）／`viewer`（閲覧のみ）。
- 既定は `127.0.0.1` のみで待ち受けます。チームで使うときはチームPCで `LABO_HOST` に VPN のアドレスを指定します。インターネットへは公開しないでください。
- 実DBの監査（段階2）：`pip install -r requirements-db.txt` → `RKM_READONLY_DSN` を設定 → `python scripts/run_audit.py`。
- 箱根の記録欠けの補完：`python scripts/fill_hakone_supplement.py`（2025年は公式記録から自動記入）。その他の年は `make_hakone_supplement.py` で記入用一覧を作り手入力（rkm は変更しない）。
- 実データで特徴量を計算：`python scripts/run_real_features.py`（初期15特徴量＋画面で「計算可能」「研究で採用」にした利用者定義。集計 `data/real_summary.json` は氏名なし、`data/real_features.csv` は氏名あり・共有しない）。画面で見る場合は `LABO_DATA_SOURCE=rkm`。
- 研究評価：`python scripts/run_evaluation.py`（世代順の検証での PR-AUC と、5000mベストだけの基準との差。集計 `data/eval_summary.json` のみ・個人の値は出さない。docs/evaluation_plan.md）。
- スマホ用ダッシュボードの表：`python scripts/make_dashboard_csv.py`（`data/dashboard/` に集計CSV。氏名・IDなし）。
- 環境変数の見本は `.env.example`（秘密値は含みません）。`data/` は git 管理外です。

## 構成

| パス | 役割 |
|---|---|
| `labo/model.py` | 正規化後の入力モデル（状態・本人照合・取得状態を区別） |
| `labo/marks.py` | 記録表記→秒（原表記と精度を保持） |
| `labo/periods.py` | 年度・学年・観測締切・窓 |
| `labo/quality.py` | 行単位の採用／除外／保留 |
| `labo/definitions.py` | 版付き定義と宣言的スペックの検証（ホワイトリスト） |
| `labo/catalog.py` | 初期15特徴量 v1 |
| `labo/features.py` | 計算エンジン（純粋関数） |
| `labo/cohorts.py` | 母集団定義（締切時点で確認可能な条件のみ） |
| `labo/store.py` | ファイル保存・実行ID・再開・監査ログ |
| `labo/server.py`, `labo/web/` | ローカルWeb（認証必須） |
| `labo/ekiden.py` | 駅伝本人区間（フェーズ2の最小部品） |
| `labo/evaluation.py` | 評価用ラベル・分割の土台 |
| `labo/research_job.py`, `labo/research_view.py` | 実データの集計・研究評価の実行と、研究状況の表（スクリプトと画面の共通処理） |
| `labo/research_eval.py` | 研究評価（世代順の検証・PR-AUC・特徴量ごとの上積み。集計のみ） |
| `labo/outcomes.py` | 成果ラベル hakone_leg_top@3（特徴量・母集団には渡さない） |
| `labo/users.py` | チーム利用者の管理（CLI） |
| `labo/adapters/rkm_readonly.py` | rkm 読み取り専用監査（本番で実行済み） |
| `labo/adapters/rkm_mapping.py`, `rkm_loader.py` | rkm → 研究用モデルの対応ルールと読み込み |

## ドキュメント

- [docs/evaluation_plan.md](docs/evaluation_plan.md) — 研究評価の方法（評価値・基準・取り置き）
- [docs/next_steps.md](docs/next_steps.md) — 次回やること（利用者側／Claude側／確認待ち）
- [docs/mobile_access.md](docs/mobile_access.md) — スマホから見る方法（集計ダッシュボード／VPN経由で本体）
- [docs/check_guide.md](docs/check_guide.md) — 日付・学年・重複・箱根の確認方法
- [docs/real_runs.md](docs/real_runs.md) — 実データでの計算の記録（集計のみ）
- [docs/audit_baseline.md](docs/audit_baseline.md) — 実DB監査の記録（導入前の基準件数）
- [reference/README.md](reference/README.md) — 参照データ（2025年箱根の公式記録・検証方法）
- [docs/decisions.md](docs/decisions.md) — 利用者の決定事項（締切・チーム利用・推奨構成・成果定義）
- [docs/supabase_setup.sql](docs/supabase_setup.sql) — 推奨構成の接続用ロール（利用者が実行する案）
- [docs/plan.md](docs/plan.md) — 理解した目的・最小構成・データ品質の懸念・実装順序・確認事項・実スキーマ対応表
- [docs/features_v1.md](docs/features_v1.md) — 15特徴量の定義書（コードから自動生成）
- [docs/progress.md](docs/progress.md) — 提案のみ／承認済み／実装済み／実行確認済み の進捗表
- [docs/migration_proposal.sql](docs/migration_proposal.sql) — 研究用保存先の**承認用案**（未実行）
- [docs/handoff.md](docs/handoff.md) — 次のAI・開発者への引継ぎ
- [docs/test_results.txt](docs/test_results.txt) — テスト実行結果
