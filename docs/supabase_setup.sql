-- ============================================================================
-- 接続用ロールの作成・修復（Supabase の SQL Editor で「全体を1回」実行する。編集不要）
-- 手順の説明は docs/next_steps.md「A」。パスワード・接続文字列はチャットやコードに貼らないこと。
--
--   lab_reader : rkm を「読むだけ」。書き込み・DDL 不可。読み取り専用トランザクションが既定。
--   lab_writer : 研究用スキーマ lab だけを持つ。rkm には一切の権限なし。
--   ブラウザ（anon / authenticated）からは rkm・lab のどちらにも直接アクセスさせない。
--
-- 何度実行してもよい：ロールが無ければ作り、あれば権限を正しい状態に直す。
-- パスワードは毎回新しく乱数で作り直し、最後の結果に一度だけ表示する（どこにも保存されない）。
--   → 再実行すると前のパスワードは使えなくなる。結果の2つをすぐパスワード管理などに保存すること。
-- rkm のデータは変更しない（権限の付与・取り消しのみ）。
-- ============================================================================

-- 0) rkm がこのプロジェクトにあるか確認（なければここで止まる。何も作られない）
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'rkm') THEN
    RAISE EXCEPTION 'このプロジェクトに rkm スキーマがありません。陸マガデータがあるプロジェクトで実行してください。';
  END IF;
END $$;

-- 1) パスワードを生成（英数字のみ。接続文字列にそのまま使える）
CREATE TEMP TABLE IF NOT EXISTS _lab_pw (lab_reader_pw text, lab_writer_pw text);
TRUNCATE _lab_pw;   -- この実行で作った一時表だけが対象（rkm とは無関係）
INSERT INTO _lab_pw SELECT encode(extensions.gen_random_bytes(24), 'hex'),
                           encode(extensions.gen_random_bytes(24), 'hex');

-- 2) ロールを作成、または既存ロールのパスワードを新しくする
--    （Supabase の postgres は非スーパーユーザーのため、既存ロールの SUPERUSER 等の属性は変更できない。
--      結果の roles_not_privileged_ok が false なら Claude に相談すること）
DO $$
DECLARE r text; w text;
BEGIN
  SELECT lab_reader_pw, lab_writer_pw INTO r, w FROM _lab_pw;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lab_reader') THEN
    EXECUTE format('ALTER ROLE lab_reader WITH LOGIN PASSWORD %L', r);  -- 属性は結果の roles_not_privileged_ok で確認
  ELSE
    EXECUTE format('CREATE ROLE lab_reader LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', r);
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lab_writer') THEN
    EXECUTE format('ALTER ROLE lab_writer WITH LOGIN PASSWORD %L', w);  -- 属性は結果の roles_not_privileged_ok で確認
  ELSE
    EXECUTE format('CREATE ROLE lab_writer LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', w);
  END IF;
END $$;

-- 3) lab_reader：rkm を読むだけ（書き込み系の権限があれば取り消す）
ALTER ROLE lab_reader SET default_transaction_read_only = on;
ALTER ROLE lab_reader SET statement_timeout = '60s';
GRANT USAGE ON SCHEMA rkm TO lab_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA rkm TO lab_reader;   -- ビュー（season_bests）を含む
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA rkm FROM lab_reader;
REVOKE CREATE ON SCHEMA rkm FROM lab_reader;

-- 4) lab_writer：lab スキーマだけ。rkm の権限はすべて取り消す
ALTER ROLE lab_writer SET statement_timeout = '30s';
REVOKE ALL ON ALL TABLES IN SCHEMA rkm FROM lab_writer;
REVOKE ALL ON SCHEMA rkm FROM lab_writer;
GRANT lab_writer TO postgres;                 -- 所有者指定のため（Supabase の postgres は非スーパーユーザー）
CREATE SCHEMA IF NOT EXISTS lab AUTHORIZATION lab_writer;
REVOKE ALL ON SCHEMA lab FROM PUBLIC;
-- lab 内の表は後日 docs/migration_proposal.sql（lab_writer で実行）。全表で RLS を有効化し、
-- anon / authenticated 向けのポリシーは作らない（＝ブラウザから直接は読めない）。

-- 5) 結果（この1行だけが表示される）：確認5項目と新しいパスワード
SELECT
  NOT EXISTS (
    SELECT 1 FROM pg_tables t WHERE t.schemaname = 'rkm' AND (
      has_table_privilege('lab_reader', format('%I.%I', t.schemaname, t.tablename), 'INSERT') OR
      has_table_privilege('lab_reader', format('%I.%I', t.schemaname, t.tablename), 'UPDATE') OR
      has_table_privilege('lab_reader', format('%I.%I', t.schemaname, t.tablename), 'DELETE') OR
      has_table_privilege('lab_reader', format('%I.%I', t.schemaname, t.tablename), 'TRUNCATE'))
  ) AS reader_cannot_write_ok,
  NOT EXISTS (
    SELECT 1 FROM pg_tables t WHERE t.schemaname = 'rkm'
      AND NOT has_table_privilege('lab_reader', format('%I.%I', t.schemaname, t.tablename), 'SELECT')
  ) AS reader_can_read_ok,
  NOT EXISTS (
    SELECT 1 FROM pg_tables t WHERE t.schemaname = 'rkm'
      AND has_table_privilege('lab_writer', format('%I.%I', t.schemaname, t.tablename), 'SELECT')
  ) AS writer_cannot_read_rkm_ok,
  (SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'lab') = 'lab_writer' AS lab_owner_ok,
  NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('lab_reader', 'lab_writer')
              AND (rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls)) AS roles_not_privileged_ok,
  lab_reader_pw, lab_writer_pw
FROM _lab_pw;

-- 取り消し方（必要になった場合のみ・別途確認のうえ。rkm のデータには影響なし）：
--   DROP SCHEMA lab; REVOKE ALL ON ALL TABLES IN SCHEMA rkm FROM lab_reader;
--   REVOKE USAGE ON SCHEMA rkm FROM lab_reader; DROP ROLE lab_reader; DROP ROLE lab_writer;
