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
- records_hash・語彙・親なし行・共有 record_id・season_bests 定義は audit_report.json の受領後に追記。
