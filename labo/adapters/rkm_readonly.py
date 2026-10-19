"""rkm スキーマの読み取り専用アダプター（段階2用・未接続・未検証）。

状態：提案のみ。実DBへの接続は利用者の承認と読み取り専用ロールの提供後に行う。
- SQLは下記の固定 SELECT のみ。利用者入力はSQL文字列に組み込まず、値はパラメーターで渡す。
- 接続直後に READ ONLY トランザクション・statement_timeout を設定する。
- 列の意味（event_kind / event_group / distance_m / date が初日か等）は実DBで確認するまで
  確定しない。正規化（Result への変換）は確認後に別ファイルで実装する。
"""
from __future__ import annotations

import os
import re

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|copy|merge|call|do|"
    r"vacuum|comment|security|set\s+role|lock)\b", re.IGNORECASE)

# 監査用の固定クエリ（読み取りのみ）
AUDIT_QUERIES: dict[str, str] = {
    "tables": (
        "SELECT table_name, table_type FROM information_schema.tables "
        "WHERE table_schema = 'rkm' ORDER BY table_name"),
    "columns": (
        "SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = 'rkm' ORDER BY table_name, ordinal_position"),
    # information_schema は SELECT のみのロールには制約を見せないため pg_constraint を使う
    "constraints": (
        "SELECT conrelid::regclass::text, contype, pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE connamespace = 'rkm'::regnamespace ORDER BY 1, 2"),
    "row_counts": (
        "SELECT 'athletes' t, count(*) FROM rkm.athletes UNION ALL "
        "SELECT 'profiles', count(*) FROM rkm.profiles UNION ALL "
        "SELECT 'records', count(*) FROM rkm.records UNION ALL "
        "SELECT 'affiliations', count(*) FROM rkm.affiliations UNION ALL "
        "SELECT 'ekiden_legs', count(*) FROM rkm.ekiden_legs UNION ALL "
        "SELECT 'splits', count(*) FROM rkm.splits UNION ALL "
        "SELECT 'raw_sources', count(*) FROM rkm.raw_sources UNION ALL "
        "SELECT 'raw_captures', count(*) FROM rkm.raw_captures"),
    "validation_status": (
        "SELECT schema_version, validation_status, count(*) FROM rkm.raw_captures "
        "GROUP BY 1, 2 ORDER BY 1, 2"),
    "event_vocab": (
        "SELECT event, event_kind, event_group, distance_m, count(*) FROM rkm.records "
        "GROUP BY 1, 2, 3, 4 ORDER BY 5 DESC LIMIT 500"),
    "status_vocab": (
        "SELECT status, count(*) FROM rkm.records GROUP BY 1 ORDER BY 2 DESC LIMIT 200"),
    "orphan_records": (
        "SELECT count(*) FROM rkm.records r LEFT JOIN rkm.profiles p "
        "ON p.person_id = r.person_id AND p.profile_id = r.profile_id WHERE p.person_id IS NULL"),
    "orphan_profiles": (
        "SELECT count(*) FROM rkm.profiles p LEFT JOIN rkm.athletes a "
        "ON a.person_id = p.person_id WHERE a.person_id IS NULL"),
    "shared_record_ids": (
        "SELECT count(*) FROM (SELECT record_id FROM rkm.records GROUP BY record_id "
        "HAVING count(DISTINCT person_id) > 1) s"),
    # RLS の有無と統計上の推定行数（RLS で行が見えなくても統計は見える）
    "rls_status": (
        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, c.reltuples::bigint, "
        "(SELECT count(*) FROM pg_policies p WHERE p.schemaname = 'rkm' AND p.tablename = c.relname) "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'rkm' AND c.relkind IN ('r', 'p') ORDER BY 1"),
    "season_bests_def": (
        "SELECT pg_get_viewdef('rkm.season_bests'::regclass, true)"),
    # ---- 第2回（2026-10-19 追加）：対応表の確定用。氏名は取得せず、数字は 9 に置き換えた書式のみ ----
    "column_docs": "SELECT table_name, column_name, description FROM rkm.column_docs ORDER BY 1, 2",
    "meta_keys": "SELECT key, left(value, 200) FROM rkm.meta ORDER BY 1",
    "date_patterns": (
        "SELECT regexp_replace(coalesce(date, '<NULL>'), '[0-9]', '9', 'g'), count(*) "
        "FROM rkm.records GROUP BY 1 ORDER BY 2 DESC LIMIT 50"),
    "fiscal_year_vs_date": (
        "SELECT count(*) FILTER (WHERE date ~ '^[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}'), "
        "count(*) FILTER (WHERE date ~ '^[0-9]{4}[-/.][0-9]{1,2}[-/.][0-9]{1,2}' AND fiscal_year IS DISTINCT FROM "
        "(CASE WHEN split_part(regexp_replace(date, '[/.]', '-', 'g'), '-', 2)::int >= 4 "
        "THEN left(date, 4)::int ELSE left(date, 4)::int - 1 END)), "
        "count(*) FILTER (WHERE fiscal_year IS NULL), count(*) FILTER (WHERE date IS NULL) FROM rkm.records"),
    "competition_dates": (
        "SELECT count(*), count(*) FILTER (WHERE n_dates > 1), max(n_dates) FROM ("
        "SELECT competition_id, count(DISTINCT date) n_dates FROM rkm.records "
        "WHERE competition_id IS NOT NULL GROUP BY 1) s"),
    "competition_id_null": (
        "SELECT event_group, count(*) FILTER (WHERE competition_id IS NULL), count(*) "
        "FROM rkm.records GROUP BY 1 ORDER BY 3 DESC"),
    "mark_patterns_5000": (
        "SELECT regexp_replace(coalesce(mark_raw, '<NULL>'), '[0-9]', '9', 'g'), mark_unit, status, "
        "count(*), min(mark_value), max(mark_value) FROM rkm.records WHERE event = '5000m' "
        "GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 60"),
    "mark_range_5000": (
        "SELECT count(*), min(mark_value), max(mark_value), "
        "count(*) FILTER (WHERE mark_value < 750), count(*) FILTER (WHERE mark_value > 1800), "
        "count(*) FILTER (WHERE mark_value IS NULL) FROM rkm.records WHERE event = '5000m' AND status IS NULL"),
    "status_marks": (
        "SELECT status, left(coalesce(mark_raw, '<NULL>'), 20), count(*) FROM rkm.records "
        "WHERE status IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 60"),
    "status_by_event_group": (
        "SELECT event_group, status, count(*) FROM rkm.records GROUP BY 1, 2 ORDER BY 1, 3 DESC"),
    "round_vocab": "SELECT round_raw, count(*) FROM rkm.records GROUP BY 1 ORDER BY 2 DESC LIMIT 60",
    "heat_patterns": (
        "SELECT regexp_replace(coalesce(heat_raw, '<NULL>'), '[0-9]', '9', 'g'), count(*) "
        "FROM rkm.records GROUP BY 1 ORDER BY 2 DESC LIMIT 30"),
    "timing_vocab": "SELECT timing, mark_unit, count(*) FROM rkm.records GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 30",
    "flags_vocab": "SELECT flags, count(*) FROM rkm.records GROUP BY 1 ORDER BY 2 DESC LIMIT 40",
    "grade_vocab": "SELECT grade_raw, count(*) FROM rkm.records GROUP BY 1 ORDER BY 2 DESC LIMIT 60",
    "class_vocab": "SELECT class_raw, count(*) FROM rkm.records GROUP BY 1 ORDER BY 2 DESC LIMIT 40",
    "category_vocab": "SELECT category_raw, count(*) FROM rkm.records GROUP BY 1 ORDER BY 2 DESC LIMIT 40",
    "in_flags": (
        "SELECT in_history, in_daily_best, in_annual_best, count(*) FROM rkm.records "
        "GROUP BY 1, 2, 3 ORDER BY 4 DESC"),
    "identity_role_vocab": (
        "SELECT identity_role, sex_raw, count(*) FROM rkm.profiles GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 30"),
    "profiles_per_person": (
        "SELECT n, count(*) FROM (SELECT person_id, count(*) n FROM rkm.profiles GROUP BY 1) s "
        "GROUP BY 1 ORDER BY 1"),
    "athlete_field_patterns": (
        "SELECT 'entry_years', regexp_replace(coalesce(entry_years, '<NULL>'), '[0-9]', '9', 'g'), count(*) "
        "FROM rkm.athletes GROUP BY 2 UNION ALL "
        "SELECT 'run_years', regexp_replace(coalesce(run_years, '<NULL>'), '[0-9]', '9', 'g'), count(*) "
        "FROM rkm.athletes GROUP BY 2 UNION ALL "
        "SELECT 'birth_date', regexp_replace(coalesce(birth_date, '<NULL>'), '[0-9]', '9', 'g'), count(*) "
        "FROM rkm.athletes GROUP BY 2 UNION ALL "
        "SELECT 'highschool_raw_null', (highschool_raw IS NULL)::text, count(*) FROM rkm.athletes GROUP BY 2 "
        "UNION ALL SELECT 'university_raw_null', (university_raw IS NULL)::text, count(*) "
        "FROM rkm.athletes GROUP BY 2 ORDER BY 1, 3 DESC"),
    "affiliation_year_patterns": (
        "SELECT regexp_replace(coalesce(year_raw, '<NULL>'), '[0-9]', '9', 'g'), (fiscal_year IS NULL), count(*) "
        "FROM rkm.affiliations GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 40"),
    "cross_profile_duplicates": (
        "SELECT count(*), coalesce(sum(n_profiles), 0) FROM (SELECT person_id, date, event, mark_raw, "
        "count(DISTINCT profile_id) n_profiles FROM rkm.records WHERE status IS NULL AND mark_raw IS NOT NULL "
        "GROUP BY 1, 2, 3, 4 HAVING count(DISTINCT profile_id) > 1) s"),
    "same_day_5000": (
        "SELECT count(*), count(*) FILTER (WHERE n_rounds = n) FROM (SELECT person_id, profile_id, date, "
        "count(*) n, count(DISTINCT round_raw) n_rounds FROM rkm.records WHERE event = '5000m' "
        "AND status IS NULL GROUP BY 1, 2, 3 HAVING count(*) > 1) s"),
    "event_id_consistency": (
        "SELECT count(*) FROM (SELECT event_id FROM rkm.records WHERE event_id IS NOT NULL "
        "GROUP BY 1 HAVING count(DISTINCT event) > 1) s"),
    "detail_json_shape": (
        "SELECT left(ltrim(coalesce(detail_tables_json, '<NULL>')), 1), count(*) FROM rkm.records "
        "GROUP BY 1 ORDER BY 2 DESC"),
    "detail_json_keys": (
        "SELECT k, count(*) FROM (SELECT jsonb_object_keys(detail_tables_json::jsonb) k FROM rkm.records "
        "WHERE detail_tables_json LIKE '{%' LIMIT 20000) s GROUP BY 1 ORDER BY 2 DESC LIMIT 50"),
    "hakone_competitions": (
        "SELECT regexp_replace(competition_raw, '[0-9]', '9', 'g'), event_group, count(*), "
        "count(ekiden_leg), count(ekiden_leg_rank), min(fiscal_year), max(fiscal_year) FROM rkm.records "
        "WHERE competition_raw LIKE '%箱根%' GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 30"),
    # 複数日大会の日付：同じ大会・種目でラウンドごとに日付が違うか（大会名・日付は公開情報。氏名なし）
    "multiday_5000_dates": (
        "SELECT competition_raw, round_raw, date, count(*) FROM rkm.records "
        "WHERE event = '5000m' AND competition_id IN (SELECT competition_id FROM rkm.records "
        "WHERE event = '5000m' AND competition_id IS NOT NULL GROUP BY 1 HAVING count(DISTINCT date) > 1) "
        "GROUP BY 1, 2, 3 ORDER BY 1, 3 LIMIT 120"),
    "interhigh_5000_dates": (
        "SELECT competition_raw, round_raw, date, count(*) FROM rkm.records WHERE event = '5000m' "
        "AND (competition_raw LIKE '%総体%' OR competition_raw LIKE '%インターハイ%' "
        "OR competition_raw LIKE '%高等学校総合体育大会%') GROUP BY 1, 2, 3 ORDER BY 3 DESC LIMIT 80"),
    # 箱根の学生連合（所属名に「連合」）と区間順位の有無
    "hakone_alliance": (
        "SELECT (affiliation_raw LIKE '%連合%'), count(*), count(ekiden_leg), count(ekiden_leg_rank) "
        "FROM rkm.records WHERE competition_raw LIKE '%箱根%' GROUP BY 1"),
    # ---- 第3回（2026-10-19 追加） ----
    "grade_by_category": (
        "SELECT grade_raw, category_raw, count(*) FROM rkm.records WHERE grade_raw IS NOT NULL "
        "GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 80"),
    "affiliation_suffix_by_category": (
        "SELECT right(affiliation_raw, 1), category_raw, count(*) FROM rkm.records "
        "WHERE affiliation_raw IS NOT NULL GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 60"),
    "same_profile_same_mark_rounds": (
        "SELECT rounds, count(*) FROM (SELECT person_id, profile_id, competition_id, date, event, mark_raw, "
        "string_agg(coalesce(replace(round_raw, E'\\n', ''), '<NULL>'), ' | ' ORDER BY coalesce(round_raw, '')) rounds "
        "FROM rkm.records WHERE status IS NULL AND mark_raw IS NOT NULL AND event IN ('5000m', '1500m', '3000m') "
        "GROUP BY 1, 2, 3, 4, 5, 6 HAVING count(*) > 1) s GROUP BY 1 ORDER BY 2 DESC LIMIT 60"),
    "date_first_day_share": (
        "SELECT count(*) FILTER (WHERE r.date = c.d0 AND c.d1 > c.d0), count(*) FILTER (WHERE c.d1 > c.d0), count(*) "
        "FROM rkm.records r JOIN (SELECT competition_id, min(date) d0, max(date) d1 FROM rkm.records "
        "WHERE competition_id IS NOT NULL GROUP BY 1) c USING (competition_id) WHERE r.event = '5000m'"),
    "hakone_main_place": (
        "SELECT CASE WHEN place_raw ~ '^[0-9]+$' THEN '<数字>' ELSE coalesce(place_raw, '<NULL>') END, "
        "(ekiden_leg_rank IS NULL), min(fiscal_year), max(fiscal_year), count(*) FROM rkm.records "
        "WHERE event_group = 'ekiden' AND competition_raw LIKE '%箱根%' AND competition_raw NOT LIKE '%予選%' "
        "GROUP BY 1, 2 ORDER BY 5 DESC"),
    "ekiden_years_vs_hakone": (
        "SELECT (a.run_years IS NOT NULL AND a.run_years <> '[]'), count(DISTINCT a.person_id), "
        "count(DISTINCT h.person_id) FROM rkm.athletes a LEFT JOIN (SELECT DISTINCT person_id FROM rkm.records "
        "WHERE event_group = 'ekiden' AND competition_raw LIKE '%箱根%' AND competition_raw NOT LIKE '%予選%') h "
        "USING (person_id) GROUP BY 1"),
    # run_years の年が暦年（1月の大会の年）か年度かの確認：箱根本戦の記録の年度との差の分布
    "run_years_alignment": (
        "SELECT h.fiscal_year - y.v::int, count(*) FROM rkm.athletes a "
        "CROSS JOIN LATERAL jsonb_array_elements_text(a.run_years::jsonb) AS y(v) "
        "JOIN (SELECT DISTINCT person_id, fiscal_year FROM rkm.records WHERE event_group = 'ekiden' "
        "AND competition_raw LIKE '%箱根%' AND competition_raw NOT LIKE '%予選%') h "
        "ON h.person_id = a.person_id AND abs(h.fiscal_year - y.v::int) <= 1 GROUP BY 1 ORDER BY 1"),
    "run_years_unmatched": (
        "SELECT count(*), count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM rkm.records r "
        "WHERE r.person_id = a.person_id AND r.event_group = 'ekiden' AND r.competition_raw LIKE '%箱根%' "
        "AND r.competition_raw NOT LIKE '%予選%' AND r.fiscal_year IN (y.v::int - 1, y.v::int))) "
        "FROM rkm.athletes a CROSS JOIN LATERAL jsonb_array_elements_text(a.run_years::jsonb) AS y(v)"),
    "ekiden_self": (
        "SELECT is_self, count(*), count(leg_rank), count(leg_value), count(pass_value) "
        "FROM rkm.ekiden_legs GROUP BY 1 ORDER BY 1"),
    "ekiden_multi_self": (
        "SELECT count(*) FROM (SELECT person_id, profile_id, record_id FROM rkm.ekiden_legs WHERE is_self = 1 "
        "GROUP BY 1, 2, 3 HAVING count(*) > 1) s"),
    # 第4回：高校・都道府県駅伝の大会名（大会区分の判定ルールの確認用。個人情報なし）と中学の記録の量
    "ekiden_names_non_hakone": (
        "SELECT regexp_replace(competition_raw, '^第[0-9０-９]+回', ''), count(*), count(ekiden_leg), "
        "count(ekiden_leg_rank), min(date), max(date) FROM rkm.records WHERE event_group = 'ekiden' "
        "AND competition_raw NOT LIKE '%箱根%' GROUP BY 1 ORDER BY 2 DESC LIMIT 80"),
    "junior_rows_by_event": (
        "SELECT event, count(*), count(DISTINCT person_id) FROM rkm.records WHERE affiliation_raw LIKE '%中' "
        "OR grade_raw LIKE '中%' OR grade_raw LIKE 'J%' GROUP BY 1 ORDER BY 2 DESC LIMIT 20"),
    "split_label_patterns": (
        "SELECT regexp_replace(coalesce(label_raw, '<NULL>'), '[0-9]', '9', 'g'), count(*) FROM rkm.splits "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 40"),
    "captured_profiles": (
        "SELECT (rc.person_id IS NOT NULL), count(DISTINCT p.person_id), count(*) FROM rkm.profiles p "
        "LEFT JOIN rkm.raw_captures rc ON rc.person_id = p.person_id AND rc.profile_id = p.profile_id GROUP BY 1"),
    # 内容ハッシュ（導入前後で既存データが不変であることの確認用）
    "records_hash": (
        "SELECT md5(string_agg(person_id || '/' || profile_id || '/' || record_id || '/' || "
        "coalesce(mark_raw, '') || '/' || coalesce(date::text, ''), ',' "
        "ORDER BY person_id, profile_id, record_id)) FROM rkm.records"),
}


_LITERAL = re.compile(r"'(?:[^']|'')*'")


def assert_readonly_sql(sql: str) -> None:
    code = _LITERAL.sub("''", sql)  # 文字列リテラル内（'INSERT' 等の権限名）は判定対象外
    head = code.lstrip().split(None, 1)[0].lower()
    if head not in ("select", "with") or FORBIDDEN.search(code) or ";" in code.strip().rstrip(";"):
        raise ValueError("読み取り専用の単一 SELECT 以外は実行しません")


# 実行前の安全確認：書き込みできる接続（postgres 等）なら監査を中止する
SAFETY_QUERIES: dict[str, str] = {
    "current_user": "SELECT current_user",
    "read_only_default": "SELECT current_setting('default_transaction_read_only')",
    "rkm_exists": "SELECT count(*) FROM pg_namespace WHERE nspname = 'rkm'",
    "can_write_rkm": (
        "SELECT count(*) FROM information_schema.tables t WHERE t.table_schema = 'rkm' "
        "AND t.table_type = 'BASE TABLE' AND (has_table_privilege(current_user, "
        "quote_ident(t.table_schema) || '.' || quote_ident(t.table_name), 'INSERT') OR "
        "has_table_privilege(current_user, quote_ident(t.table_schema) || '.' || "
        "quote_ident(t.table_name), 'UPDATE') OR has_table_privilege(current_user, "
        "quote_ident(t.table_schema) || '.' || quote_ident(t.table_name), 'DELETE'))"),
}


class UnsafeConnection(RuntimeError):
    pass


def run_audit(dsn_env: str = "RKM_READONLY_DSN") -> dict:  # pragma: no cover - 実DBが必要
    """読み取り専用監査。結果に氏名・接続情報・秘密は含めない。"""
    dsn = os.environ.get(dsn_env)
    if not dsn:
        raise RuntimeError(f"環境変数 {dsn_env} が未設定です")
    import psycopg  # requirements-db.txt
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    # Supabase のデータベース名は postgres。末尾の /postgres が抜けると
    # ユーザー名（lab_reader）がデータベース名として使われ接続に失敗するため補う。
    if not conninfo_to_dict(dsn).get("dbname"):
        dsn = make_conninfo(dsn, dbname="postgres")

    timeout = int(os.environ.get("RKM_STATEMENT_TIMEOUT_MS", "60000"))
    out: dict = {"safety": {}, "results": {}, "errors": {}}
    with psycopg.connect(dsn, connect_timeout=15) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('statement_timeout', %s, false)", (str(timeout),))
            for name, sql in SAFETY_QUERIES.items():
                assert_readonly_sql(sql)
                cur.execute(sql)
                out["safety"][name] = cur.fetchone()[0]
            if out["safety"]["rkm_exists"] != 1:
                raise UnsafeConnection("rkm スキーマが見つかりません（接続先のプロジェクトを確認してください）")
            if out["safety"]["can_write_rkm"] != 0:
                raise UnsafeConnection(
                    f"接続ユーザー {out['safety']['current_user']} は rkm に書き込めます。"
                    "lab_reader で接続してください（監査を中止しました）")
            for name, sql in AUDIT_QUERIES.items():
                assert_readonly_sql(sql)
                try:
                    cur.execute(sql)
                    out["results"][name] = cur.fetchmany(1000)
                except psycopg.Error as e:  # 1つの失敗で全体を止めない
                    conn.rollback()
                    out["errors"][name] = type(e).__name__ + ": " + str(e).splitlines()[0]
                    cur.execute("SELECT set_config('statement_timeout', %s, false)", (str(timeout),))
        conn.rollback()
    return out
