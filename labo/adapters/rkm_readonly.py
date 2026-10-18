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
    "constraints": (
        "SELECT tc.table_name, tc.constraint_type, tc.constraint_name "
        "FROM information_schema.table_constraints tc WHERE tc.table_schema = 'rkm' "
        "ORDER BY tc.table_name, tc.constraint_type"),
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
    "season_bests_def": (
        "SELECT pg_get_viewdef('rkm.season_bests'::regclass, true)"),
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
