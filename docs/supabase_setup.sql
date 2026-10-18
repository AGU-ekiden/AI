-- ============================================================================
-- 推奨構成：Supabase 接続用ロールの作成（利用者が Supabase の SQL Editor で実行する）
-- 状態：案。Claude は実行していない。パスワード・接続文字列をチャットやコードに貼らないこと。
--
-- 方針
--   lab_reader : rkm を「読むだけ」。書き込み・DDL 不可。読み取り専用トランザクション既定。
--   lab_writer : 研究用スキーマ lab だけを持つ。rkm には一切の権限なし。
--   ブラウザ（anon / authenticated）からは rkm・lab のどちらにも直接アクセスさせない。
--   アプリのサーバー側だけが、環境変数で受け取った接続文字列で接続する。
--
-- 実行前後の確認：labo/adapters/rkm_readonly.py の row_counts と records_hash を
--   実行前後で比較し、rkm が不変であることを記録する。
-- 取り消し方：DROP ROLE は lab スキーマ撤去後に（別途確認のうえ）。rkm には影響しない。
-- ============================================================================

-- 1) 読み取り専用ロール（パスワードは Supabase 側で強いものを生成して設定）
CREATE ROLE lab_reader LOGIN PASSWORD '<ここに生成したパスワード：チャットに貼らない>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE lab_reader SET default_transaction_read_only = on;
ALTER ROLE lab_reader SET statement_timeout = '15s';
GRANT USAGE ON SCHEMA rkm TO lab_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA rkm TO lab_reader;   -- ビュー（season_bests）を含む
-- rkm に将来追加される表は自動付与しない（追加時に改めて判断する）

-- 2) 研究用スキーマの書き込みロール（rkm への権限は付与しない）
CREATE ROLE lab_writer LOGIN PASSWORD '<ここに生成した別のパスワード>'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE lab_writer SET statement_timeout = '30s';
CREATE SCHEMA lab AUTHORIZATION lab_writer;
REVOKE ALL ON SCHEMA lab FROM PUBLIC;
-- 表の作成は docs/migration_proposal.sql（lab_writer で実行）。全表で RLS を有効化し、
-- anon / authenticated 向けのポリシーは作らない（＝ブラウザから直接は読めない）。

-- 3) 確認（どちらも false / 権限なし になること）
-- SELECT has_table_privilege('lab_reader', 'rkm.records', 'INSERT');   -- false
-- SELECT has_table_privilege('lab_writer', 'rkm.records', 'SELECT');   -- false
