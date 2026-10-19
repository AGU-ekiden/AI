# 引継ぎ文書（秘密情報なし）

## 現在地
段階1（合成データMVP）完了。実DBには未接続。仕様書の全文は利用者から受領済み（このリポジトリには未収録）。

## 守ること（仕様書より要約）
- rkm へ DROP/TRUNCATE/DELETE/一括UPDATE/スキーマ入替をしない。既存の全置換アップローダーを流用しない。
- 実在選手の成功確率・総合点・ランキング・推薦順位・選抜判断を作らない。健康・性格等を推測しない。
- 記録の欠落を故障や意欲不足と解釈しない。未来情報（進学先・箱根・高3全国）を特徴量や母集団選定に使わない。
- 実データの外部AI送信は既定で無効。鍵をコード・ログ・ブラウザ配信物に置かない。
- 定義変更は新しい版。古い実行結果を上書きしない。

## 設計の要点
- 判定順：個人走以外 → 証拠統合済み重複 → 本人照合 → 状態 → 正の秒 → 妥当範囲 → 行単位確認 → 実施日 → 締切 → H開始 → （厳密モード）公表日。`labo/quality.py`
- 件数・分布系（count/latest_n/iqr/gap）は未解決の重複疑いが窓内にあれば null。最小値系は重複に不変なので計算。
- 実行ID＝データ版・母集団・締切・定義版とspecハッシュ・コード版・オプションのハッシュ。`labo/store.py`
- コード版が変わると、未完了の実行は再開を拒否する（混在防止）。新しい条件で実行し直す。

## 決定済み（docs/decisions.md）
既定締切は高2の8/31、チームで複数人利用、推奨構成（lab_reader / lab_writer）、成果は箱根の往路区間5位以内または復路区間2位以内（hakone_leg_top@3：学生連合は区間順位の扱いから除く）、追跡は高校入学年度+3年度から4大会、運用はチームPC＋VPN、利用者は最大2人。

## 次の作業
1. 利用者が docs/supabase_setup.sql を実行し、チームPCで `scripts/run_audit.py` を実行（docs/next_steps.md A）。
   クラウドのClaudeセッションからはDBへ直接接続できない想定。結果ファイル data/audit_report.json を受け取る。
2. 監査結果から件数・語彙・孤児行・共有record_id・season_bests定義を報告（参考値との差分）。
3. 監査結果で対応表を確定し、`labo/adapters/` に rkm → Result 変換を実装。数名を手計算で突合。
4. 研究用保存先は docs/migration_proposal.sql を lab_writer で適用（前後で rkm 不変を確認）。
5. 箱根の結果が rkm に含まれるか（athletes.entry_years / run_years、records の箱根区間）を監査し、成果ラベル用の取り込みを設計。学生連合は除外（決定済み）。

## 実行方法
`python3 -m unittest discover -s tests -t .` / `python3 -m labo.server`。特徴量定義書は `python3 scripts/gen_feature_doc.py` で再生成。
