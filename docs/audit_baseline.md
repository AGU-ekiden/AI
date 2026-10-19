# rkm 監査の記録（読み取り専用・lab_reader）

## 2026-10-19 第1回（チームPCで scripts/run_audit.py を実行）

接続ユーザー：lab_reader（rkm への書き込み権限なしを確認）／失敗したクエリ：なし

| 表 | 件数 | 参考値（2026-10-18 検証） | 差 |
|---|---:|---:|---:|
| athletes | 1,113 | 1,113 | 0 |
| profiles | 1,133 | 1,133 | 0 |
| records | 209,323 | 209,323 | 0 |
| affiliations | 6,590 | — | — |
| ekiden_legs | 147,155 | — | — |
| splits | 45,776 | — | — |
| raw_sources | 112 | 112人分の原本保存 | 一致 |
| raw_captures | 112 | 同上 | 一致 |

- この件数を「導入前」の基準とする（研究用保存先の作成後に同じ件数・records_hash であることを確認する）。
- 経緯：rkm の全表で RLS が有効・ポリシー0件だったため、初回は0件に見えた。
  `docs/rkm_read_policy.sql` で lab_reader 専用の SELECT ポリシーを全10表に追加後、上記を確認。
- records_hash（導入前の基準）：`356d362ba236f44f13a3122cfe011d53`（2026-10-19 00:02 UTC 取得）

### 第1回で分かったこと

**良い点**
- 親なし行：records→profiles 0件、profiles→athletes 0件。
- 件数は参考値と完全一致。lab_reader は書き込み不可・読み取り専用トランザクションを確認。

**種目の対応（重要）**
- 個人5000mは `event = '5000m'` かつ `event_group = 'track'`（53,971行）だけを使う。
  **distance_m=5000 で選ぶと誤り**：`5km`（ロード 4,802行）と `5000mW`（競歩 35行）が混ざる。
- 3000mSC は `3000mSC(91.4cm)`（4,925行）と `3000mSC(76.2cm)`（1行）。どちらも distance_m=3000 のため、
  距離では 3000m と区別できない。種目名で区別する。
- 駅伝 `駅伝`（ekiden 19,837行）、チーム（team）、リレー（relay）は個人特徴量から除外（既存の方針どおり）。
- 表記の揺れ：`10マイル（ロード）` は distance_m が 16093.44 の行と null の行がある。
  `クロスカントリーリレー` は event_group が xc と relay に分かれている。
  `ジャベリックスロー（300g）` は event_kind=time・track に分類されている（投てき種目のはず）。いずれも5000m特徴量には影響しない。

**記録の状態（status）**
- null 174,695／NM 18,611／DNS 14,490／DNF 1,413／NI 73／DQ 36／DSQ 2／DNE 2／競走中止 1。
- NM・NI・DNE の意味は未確認（第2回で column_docs と原表記を確認）。DQ と DSQ は同じ扱い（失格）にする予定。
  「競走中止」は自動で DNF と同一視せず、確認まで保留扱い。

**本人・重複**
- 別人どうしで共有されている record_id：4,425個（同じレースが複数選手に現れる。キーは常に person_id+profile_id+record_id）。
- raw_captures は112件（旧形式110・rebuilt-1形式2）で、**すべて validation_status = raw_only**。
  元の1,001人には raw_captures の行がないため、「行単位の確認済み」の根拠は raw_captures 以外に求める必要がある。

**既存ビュー season_bests**
- `status IS NULL`・ekiden/team/relay 除外で年度別最小値を出す単純な集計。本人確認（identity_role）を見ず、
  同一人物の複数プロフィール由来の重複も数えるため、**特徴量の計算には使わない**（参考表示のみ）。

**注意：constraints が空だった件**
- 第1回の制約一覧は information_schema を使っており、SELECT 権限しかないロールには制約が表示されない。
  「主キーがない」という意味ではない。第2回は pg_constraint で確認する。

### 第2回で確認すること（scripts/run_audit.py に追加済み・氏名は取得しない）
日付の書式と年度との整合、大会IDごとの日付の数（初日だけか）、5000m の記録表記と値の範囲、
NM/NI/DNE の原表記、ラウンド・組・計時・学年・区分の語彙、identity_role、プロフィール数の分布、
複数プロフィール間の重複候補数、同日複数出走、detail_tables_json の形、箱根駅伝の行（区間・区間順位の有無）、
駅伝区間の本人フラグ、途中計時のラベル書式、column_docs（列の説明）、meta、制約（pg_constraint）。
