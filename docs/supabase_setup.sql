-- ============================================================================
-- 接続用ロールの作成（利用者が Supabase の SQL Editor で「全体を1回」実行する。編集不要）
-- 手順の説明は docs/next_steps.md「A」。パスワード・接続文字列はチャットやコードに貼らないこと。
--
--   lab_reader : rkm を「読むだけ」。書き込み・DDL 不可。読み取り専用トランザクションが既定。
--   lab_writer : 研究用スキーマ lab だけを持つ。rkm には一切の権限なし。
--   ブラウザ（anon / authenticated）からは rkm・lab のどちらにも直接アクセスさせない。
--
-- パスワードはこのスクリプトが乱数で作り、最後の結果に一度だけ表示する（どこにも保存されない）。
-- 結果の1行を見たら、2つのパスワードをすぐパスワード管理などに保存すること。
-- 2回目を実行すると「role already exists」で止まる（既存のロールは変更されない）。
-- ============================================================================

-- 0) rkm がこのプロジェクトにあるか確認（なければここで止まる。何も作られない）
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'rkm') THEN
    RAISE EXCEPTION 'このプロジェクトに rkm スキーマがありません。陸マガデータがあるプロジェクトで実行してください。';
  END IF;
END $$;

-- 1) パスワードを生成（英数字のみ。接続文字列にそのまま使える）
CREATE TEMP TABLE _lab_pw AS
  SELECT encode(extensions.gen_random_bytes(24), 'hex') AS lab_reader_pw,
         encode(extensions.gen_random_bytes(24), 'hex') AS lab_writer_pw;

-- 2) ロールとスキーマを作成
DO $$
DECLARE r text; w text;
BEGIN
  SELECT lab_reader_pw, lab_writer_pw INTO r, w FROM _lab_pw;
  EXECUTE format('CREATE ROLE lab_reader LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', r);
  EXECUTE format('CREATE ROLE lab_writer LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', w);
END $$;

ALTER ROLE lab_reader SET default_transaction_read_only = on;
ALTER ROLE lab_reader SET statement_timeout = '60s';
GRANT USAGE ON SCHEMA rkm TO lab_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA rkm TO lab_reader;   -- ビュー（season_bests）を含む
-- rkm に将来追加される表へは自動付与しない（追加時に改めて判断する）

ALTER ROLE lab_writer SET statement_timeout = '30s';
GRANT lab_writer TO postgres;                 -- 所有者指定のため（Supabase の postgres は非スーパーユーザー）
CREATE SCHEMA lab AUTHORIZATION lab_writer;
REVOKE ALL ON SCHEMA lab FROM PUBLIC;
-- lab 内の表は後日 docs/migration_proposal.sql（lab_writer で実行）。全表で RLS を有効化し、
-- anon / authenticated 向けのポリシーは作らない（＝ブラウザから直接は読めない）。

-- 3) 結果（この1行だけが表示される）：確認4項目とパスワード
SELECT
  NOT has_table_privilege('lab_reader', 'rkm.records', 'INSERT') AS reader_cannot_write_ok,
  has_table_privilege('lab_reader', 'rkm.records', 'SELECT')     AS reader_can_read_ok,
  NOT has_table_privilege('lab_writer', 'rkm.records', 'SELECT') AS writer_cannot_read_rkm_ok,
  (SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'lab') = 'lab_writer' AS lab_owner_ok,
  lab_reader_pw, lab_writer_pw
FROM _lab_pw;

-- 取り消し方（必要になった場合のみ・別途確認のうえ。rkm のデータには影響なし）：
--   DROP SCHEMA lab; REVOKE ALL ON ALL TABLES IN SCHEMA rkm FROM lab_reader;
--   REVOKE USAGE ON SCHEMA rkm FROM lab_reader; DROP ROLE lab_reader; DROP ROLE lab_writer;
