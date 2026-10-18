# 次にやること（2026-10-19 更新）

ブランチ：`claude/new-session-pnnp13`
現状：段階1（合成データMVP）完了。実DB（rkm）には未接続。

## A. 利用者側の作業（この順に）

### A-0. プロジェクトの確認（1分）
- Supabase のプロジェクトが **Healthy**（「Coming up…」が消えた状態）になっていること。
- そのプロジェクトに **陸マガデータ（rkm）があること**。左メニューの Table Editor（表のアイコン）で、
  上部のスキーマ選択に `rkm` が出るか確認。出なければ別のプロジェクトです（下のSQLも手順0で止まります）。

### A-1. 接続用ロールを作る（5分・編集不要）
1. 左メニューの **SQL Editor**（`>_` のアイコン）→ 新しいクエリ。
2. `docs/supabase_setup.sql` の**最新版**の中身をそのまま全部貼り付けて Run。
3. 結果に1行表示される：
   - `reader_cannot_write_ok` `reader_can_read_ok` `writer_cannot_read_rkm_ok` `lab_owner_ok` `roles_not_privileged_ok` が **5つとも true** なら成功。
   - `lab_reader_pw` `lab_writer_pw` の2つのパスワードは**この時しか表示されない**ので、すぐパスワード管理などに保存。
     （英数字のみで接続文字列にそのまま使えます。チャットには貼らないでください）
4. 「rkm スキーマがありません」と出たら別のプロジェクトです（何も作られていません）。
5. **何度実行してもかまいません**。既にロールがあれば権限を正しい状態に直し、パスワードを新しくします。
   再実行すると前のパスワードは使えなくなるので、最後に表示された2つを保存してください。
   （2026-10-19：旧版を2回実行すると「role "lab_reader" already exists」で止まる問題を修正）

### A-2. 接続文字列を作る（3分）
1. 画面上部の **Connect** → 「Session pooler」の接続文字列（URI）をコピー。
   （無料プランの Direct connection は IPv6 専用のため、一般的な回線では Session pooler を使う）
2. 文字列の中のユーザー名 `postgres.okmhs…` の **`postgres` を `lab_reader` に**、
   `[YOUR-PASSWORD]` を lab_reader のパスワードに置き換える。
   例：`postgresql://lab_reader.<プロジェクトID>:<パスワード>@<ホスト>:5432/postgres`
3. 同様に `lab_writer` 用も作る（研究用保存は後日。今日は lab_reader だけで可）。

### A-2.5. rkm の RLS に lab_reader の読み取り許可を追加（2026-10-19 判明）
- rkm の全表で RLS が有効・ポリシー0件のため、lab_reader からは0件に見えた（postgres では records 209,323 件）。
- `docs/rkm_read_policy.sql` を SQL Editor で全体を1回実行（何度実行してもよい）。
  lab_reader だけが SELECT できるポリシーを各表に追加する。データ・他ロールの見え方は変わらない。
- 結果の `lab_reader_policy` がすべて true、`writable_policy` がすべて 0 なら成功。

### A-3. チームPCで監査を実行（10分）
1. Python 3.11 以上と Git を入れ、リポジトリを取得してブランチ `claude/new-session-pnnp13` に切り替える。
2. PowerShell で：
   ```powershell
   pip install -r requirements-db.txt
   $env:RKM_READONLY_DSN = "（A-2で作った lab_reader の接続文字列）"   # このウィンドウだけ有効
   python scripts/run_audit.py
   ```
3. 「rkm への書き込み権限なしを確認」と件数が表示されれば成功。`data/audit_report.json` ができる。
   - 「中止：…書き込めます」と出たら `postgres` のままです。A-2の2を確認。
4. `data/audit_report.json` の中身を次回チャットに貼る（件数・列名・語彙のみで、氏名・パスワードは含まない）。

> クラウド側（この Claude のセッション）は HTTPS 以外の通信が制限されているため、
> DB へは接続できない想定です。監査はチームPCで実行し、結果ファイルを共有する方式にします。

## B. 次回 Claude が行うこと（A-3 の結果を受けて）
1. 監査結果の報告：参考値（athletes 1,113／profiles 1,133／records 209,323）との差、語彙、親なし行、
   別人共有の record_id、season_bests の定義。不変確認用の件数とハッシュを「前」として記録。
2. 実スキーマ対応表の確定（3000mSC 表記、event_group、`records.date` が大会初日か、入学年度の根拠）。
3. rkm → 研究用モデルの変換を実装し、数名を手計算と突き合わせる（予測はしない）。
4. 箱根の区間成績が rkm にあるか（学生連合の相当順位を含む）を確認し、成果ラベル取り込みを設計。
5. 研究用保存先（lab スキーマの表）の作成案を最終確認のうえ適用し、rkm 不変を再確認。

## C. 決定済み（詳細は docs/decisions.md）
- 観測締切：高2の8/31（7/31・高2年度末も選択可）
- 新しい非公開アプリ／チームPC＋VPNで運用／利用者は最大2人（登録は後日）
- 推奨構成（lab_reader / lab_writer、ブラウザから直接DBへつながない）
- 成果 hakone_leg_top@2：往路区間5位以内 または 復路区間2位以内、学生連合は相当順位で含める、
  追跡期間は高校入学年度+3年度から4大会
