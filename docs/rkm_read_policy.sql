-- ============================================================================
-- lab_reader に rkm の「読み取りだけ」を許可する RLS ポリシーの追加
-- （Supabase の SQL Editor で全体を1回実行。何度実行してもよい）
--
-- 背景（2026-10-19 確認）：rkm の全表で RLS が有効・ポリシー0件のため、lab_reader からは
--   0件に見えていた（postgres では records 209,323 件）。
-- 変更内容：rkm の各表に「lab_reader だけが SELECT できる」ポリシーを1つずつ追加する。
--   ・データ（行）は一切変更しない。
--   ・anon / authenticated（ブラウザ側）など他のロールの見え方は変わらない。
--   ・書き込み（INSERT/UPDATE/DELETE）を許すポリシーは作らない。
-- 取り消し方：末尾のコメント参照（ポリシーを削除すると元の状態に戻る）。
-- ============================================================================

DO $$
DECLARE t record;
BEGIN
  FOR t IN
    SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'rkm' AND c.relkind IN ('r', 'p') AND c.relrowsecurity
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_policies
                   WHERE schemaname = 'rkm' AND tablename = t.relname AND policyname = 'lab_reader_select') THEN
      EXECUTE format('CREATE POLICY lab_reader_select ON rkm.%I FOR SELECT TO lab_reader USING (true)', t.relname);
    END IF;
  END LOOP;
END $$;

-- 結果：表ごとの確認（lab_reader_policy がすべて true、writable_policy がすべて 0 なら成功）
SELECT c.relname AS 表,
       EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = 'rkm' AND p.tablename = c.relname
               AND p.policyname = 'lab_reader_select' AND p.cmd = 'SELECT'
               AND p.roles = '{lab_reader}') AS lab_reader_policy,
       (SELECT count(*) FROM pg_policies p WHERE p.schemaname = 'rkm' AND p.tablename = c.relname
               AND p.cmd <> 'SELECT') AS writable_policy
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'rkm' AND c.relkind IN ('r', 'p') AND c.relrowsecurity
ORDER BY 1;

-- 取り消し方（必要な場合のみ）：
-- DO $$ DECLARE t record; BEGIN
--   FOR t IN SELECT tablename FROM pg_policies WHERE schemaname = 'rkm' AND policyname = 'lab_reader_select'
--   LOOP EXECUTE format('DROP POLICY lab_reader_select ON rkm.%I', t.tablename); END LOOP;
-- END $$;
