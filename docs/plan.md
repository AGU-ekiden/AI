# 実装計画（段階0の報告）

作成日：2026-10-18

## 1. 理解した目的

- 指導者が日本語の仮説（「高1→高2の伸び」「ベストより安定性」等）を、AIと相談しながら**再現可能な数式**にし、
  計算値・根拠・検証履歴を確認できる非公開の研究基盤を作る。
- 最初の成果物は「特徴量を定義・計算・確認・版管理する画面と計算基盤」。予測・順位付け・選抜判定は作らない。
- AIの提案／再現可能な計算／人による確認を分離する。特徴量を増やせば良くなるという前提に立たない。

## 2. 段階0で確認した環境

| 項目 | 状況 |
|---|---|
| リポジトリ | `AGU-ekiden/AI` は空（既存アプリなし） |
| DB接続 | 本環境に Supabase / Postgres の接続設定なし → **実DBは未確認**。仕様書の構造概要・2026-10-18時点の件数は参考値として扱い、実装に固定していない |
| 方針 | 仕様書【12】に従い合成データで段階1を実装。実DB接続・送信・変更・公開は確認後 |

## 3. 提案する最小構成

- **Python標準ライブラリのみ**（依存ゼロ・保守負担最小）。計算エンジンは純粋関数で、Webとは分離。
- 保存はローカルファイル（`data/`）。版付き定義・判断履歴・実行メタ・結果・監査ログ。
- Webは `127.0.0.1` 待受＋トークンログイン＋HttpOnly/SameSite=Strict セッション＋CSRFヘッダ＋厳格CSP。
- 段階2以降の候補（未決定・利用者と相談）：
  - A案：このローカルアプリのまま、読み取り専用ロールで rkm を読む（最小）
  - B案：Supabase に研究用スキーマ（例 `lab`）を承認後に作成し、RLS付きで複数人利用
  - サービス名・価格は固定しない。

## 4. データ品質上の懸念（実DBで要確認）

1. **選択バイアス**：元の1,001人全員に大学情報またはentry関連情報 → 大学進学・既知成果経由の集団。全高校生へ一般化不可。
2. **未来情報の混入**：対象者選定（高3で初の全国出場、進学先）が高2時点の集団に混ざる恐れ → 母集団を版管理し「締切時点で確認可能な条件」だけで作る（実装済み：`national_by_cutoff`）。
3. **日付**：`records.date` が複数日大会の初日である可能性 → 実施日未確認の結果は採用せず、締切をまたぐものは保留（実装済み）。
4. **record_id は全体一意ではない**：同じレースが複数選手に現れる → キーは常に (person_id, profile_id, record_id)（実装済み）。
5. **二重プロフィール**：同一本人結果の重複 → 証拠付き対応表でのみ統合。未解決なら件数・中央値系は null（最小値は影響しないため計算）。
6. **駅伝/チーム/リレー親レコード**の `mark_value` はチーム合計の可能性 → 個人特徴量から除外。本人区間は `ekiden_legs.is_self` の `leg_value` のみ、`pass_value` は不使用。
7. **3000mSC と 3000m の混同**、単位・計時精度・丸め → 種目コードで分離、秒に統一、原表記保持。
8. **raw_only**：除外理由にしない。一方、原本があるだけで採用もしない（行単位確認 `row_checked` が必要）。
9. **学年**：入学年度の根拠と確度が必要。年齢・生年月日・現所属から補完しない。`affiliations` の年度空欄行を確定年度にしない。
10. **FK未定義**：親なし子データをアプリ側で検査（監査クエリ案に含む）。
11. **公表時点**：公表日が不明なら「過去の競技日基準で再構成した分析」と表示（実装済み）。

## 5. 実スキーマ対応表（案・実DBで未確認）

| 正規化モデル（labo.model.Result） | rkm の列（候補） | 確認が必要なこと |
|---|---|---|
| key (person_id, profile_id, record_id) | records の複合主キー | — |
| event_code | records.event / event_kind / distance_m | 語彙一覧（監査クエリ `event_vocab`）。3000mSC の表記 |
| event_group | records.event_group | ekiden / team / relay の値 |
| competition_id / name | competition_id / competition_raw | 欠落率 |
| competition_start / end | records.date（初日？）／終了日は不明 | 終了日の取得元。detail_tables_json に日程があるか |
| performed_date | 不明 | ラウンド・日程の確認元 |
| status | records.status / mark_raw | DNS/DNF/DSQ/空欄の表記 |
| seconds / precision / timing | mark_value / mark_unit / mark_raw / timing | 単位、手動計時 |
| round_order / start_time | round_raw / heat_raw | 順序の根拠になるか |
| identity | profiles.identity_role | 本人確認の基準 |
| capture_validation_status | raw_captures.validation_status | raw_only の意味の再確認 |
| row_checked | （新規判断。研究側の確認記録） | 行単位確認の手順 |
| first_available_at / captured_at | なし / profiles.captured_at, raw_captures.captured_at | 公表日は通常不明 |
| Athlete.hs_entry_fiscal_year | affiliations（fiscal_year, affiliation_raw）、grade_raw | 入学年度の導出規則と確度 |
| Athlete.coverage | raw_captures.coverage | 値の意味 |
| EkidenLeg | ekiden_legs（is_self, leg_value, pass_value） | 年度別区間距離の出典 |
| DuplicateLink | （新規：研究側の対応表） | 統合の証拠基準 |

読み取り専用の監査クエリは `labo/adapters/rkm_readonly.py`（SELECTのみ・READ ONLYトランザクション・タイムアウト）。**未実行**。

## 6. 実装順序

1. 段階1（**実装済み**）：合成データMVP・15特徴量・テスト・画面。
2. 段階2（承認後）：読み取り専用接続 → 監査（件数・定義・差分を報告）→ 正規化アダプター → 数名の手計算突合。予測なし。
3. 段階3（承認後）：研究用保存基盤（`docs/migration_proposal.sql` の案）・RLS・複数人利用・既存データ不変の前後検証（`records_hash` 等）。
4. 段階4：AIによる定義案（宣言的定義への変換＋人の承認。実データ送信は既定で無効）。
5. 段階5（別途合意）：目的変数・評価計画を確定してから過去世代の集計レベル検証。

## 7. 確認が必要な事項

1. 初期の観測時点は**高2年度末**でよいか（夏＝高2の8/31 も切替可能に実装済み）。
2. 既存Webアプリに追加か、このリポジトリの新しい非公開アプリか。使える開発環境・ホスティング。
3. 利用者は本人のみか、チーム内の複数人か（認証・RLS設計が変わる）。
4. 読み取り専用接続の提供方法（読み取り専用ロールのDSNを安全な環境変数で）と研究用データの保存先。
5. 将来の「箱根で活躍」の具体的定義と追跡期間（未決なら予測機能は保留のまま）。
