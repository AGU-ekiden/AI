# スマホから見る方法（2026-10-19）

出先のスマホで確認する方法は2つあります。用途で使い分けてください。

| | A. 研究状況ダッシュボード（claude.ai） | B. 特徴量ラボ本体（チームPC＋VPN） |
|---|---|---|
| 見られるもの | 集計だけ（人数・特徴量ごとの値あり件数と分布・成果ラベルの年度別人数・5000mの判定件数・箱根の記録欠け・研究評価） | すべての画面。最初の画面「**研究状況**」で評価値・上積みの確認、承認・「研究で採用」、実データでの再計算・再評価までできる |
| 氏名・ID | **載せていない** | 表示される（認証必須） |
| 必要なもの | claude.ai にログインできること | VPN 接続とログイン用トークン、チームPCの起動 |
| 更新 | real_summary.json を Claude に渡したときに Claude が更新（PCを切っているとき用の控え） | 「再計算・再評価」でその場で反映 |
| 指示の出し方 | 見た内容をもとに Claude のセッションへ指示 | 同左（画面上の操作もできる） |

## A. 研究状況ダッシュボード
- URL：https://claude.ai/artifact/MAsufu8UyX6WQNUpqWANtp
- 非公開（作成者のアカウントだけが開ける）。共有メニューで共有しない限り他の人は見られない。
- 中身は `data/real_summary.json`（第4回）から作った集計のみ。個人の行は含めない。
- 新しい計算をしたら real_summary.json を Claude に渡す → Claude がダッシュボードの数値を差し替える。

## B. 特徴量ラボ本体を VPN 経由で開く
インターネットへは公開しません。VPN の中からだけ開けるようにします。

1. チームPCとスマホを同じ VPN に入れる（VPN アプリでスマホを接続）。
2. チームPCの VPN 側の IP アドレスを確認（VPN アプリの画面、または `ipconfig` の VPN アダプター）。例：`100.x.y.z`
3. チームPCで起動（PowerShell）：
   ```powershell
   $env:RKM_READONLY_DSN = "（lab_reader の接続文字列）"   # チャットには貼らない
   $env:LABO_DATA_SOURCE = "rkm"
   $env:LABO_HOST = "100.x.y.z"        # VPN のアドレスだけで待ち受ける（0.0.0.0 にしない）
   $env:LABO_PORT = "8765"
   $env:LABO_SECURE_COOKIE = "false"   # VPN で暗号化されるため（decisions.md 2026-10-19）
   python -m labo.server
   ```
4. Windows ファイアウォールで 8765 番を **VPN のアドレス範囲からだけ** 許可（管理者 PowerShell、範囲は VPN に合わせる）：
   ```powershell
   New-NetFirewallRule -DisplayName "labo-vpn-only" -Direction Inbound -Protocol TCP -LocalPort 8765 -RemoteAddress 100.64.0.0/10 -Action Allow
   ```
5. スマホのブラウザで `http://100.x.y.z:8765/` を開き、トークンでログイン（トークンは `data/.token` または `python -m labo.users add` で発行。チャットには貼らない）。
6. 使い終わったら PowerShell で Ctrl+C で停止。チームPCがスリープすると見られない。

### 注意
- ルーターのポート開放・公開トンネル（URLを知っていれば誰でも開けるもの）は使わない。
- スマホ用に閲覧専用の利用者を作るなら：`python -m labo.users add --name 自分のスマホ --role viewer`
- 画面はスマホ幅で表示確認済み（docs/progress.md の Web 7画面）。
