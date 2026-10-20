# 家のPCで常時起動する（2026-10-20 利用者決定）

家のデスクトップPCで特徴量ラボを動かしっぱなしにし、外出先のスマホからは **Tailscale**（無料のVPN）経由で開く。
インターネットへは公開しない（Tailscale でつながった自分の端末からだけ開ける）。毎朝4時に最新版へ自動更新。

## 手順1. 必要なソフトを入れる（家のPC）
1. **Python**：https://www.python.org/downloads/ から最新版。インストール時に「Add python.exe to PATH」にチェック。
2. **Git for Windows**：https://git-scm.com/download/win （設定は既定のまま）。
3. **Tailscale**：https://tailscale.com/download/windows → 起動して Google などでログイン。
4. **スマホにも Tailscale** を入れ、**同じアカウント**でログイン。

## 手順2. 特徴量ラボを取得する（PowerShell）
```powershell
cd $HOME\Documents
git clone -b claude/new-session-pnnp13 https://github.com/AGU-ekiden/AI.git labo-ai
cd labo-ai
python -m pip install -r requirements-db.txt
[Environment]::SetEnvironmentVariable("RKM_READONLY_DSN", "（lab_reader の接続文字列）", "User")
```
- git clone のとき GitHub へのログイン画面が出たらログインする（以後は自動）。
- 今まで使っていたPCの `data` フォルダを `labo-ai\data` にコピーすると、ログイン用トークン・承認の記録・集計が引き継がれる
  （コピーしない場合は初回起動時に新しいトークンが `data\.token` にできる）。
- 接続文字列はチャットに貼らない。

## 手順3. 常時起動を設定する（1回だけ）
スタートメニューで PowerShell を右クリック →「**管理者として実行**」→
```powershell
cd $HOME\Documents\labo-ai
powershell -ExecutionPolicy Bypass -File scripts\windows\install_home_server.ps1
```
- 途中で **このPCにサインインするときのパスワード**を聞かれる（サインインしていなくても起動するため。Windows のタスクに保存され、ファイルには残らない）。
  Microsoft アカウントの場合はそのパスワード（PIN ではない）。
- 最後に「スマホから開くアドレス http://100.x.x.x:8765/」が表示される。

## 手順4. スマホから開く
1. スマホで Tailscale を「接続」にする。
2. ブラウザで手順3のアドレスを開き、トークンでログイン（`data\.token` の中身）。ホーム画面に追加しておくと便利。
3. 最初の画面「研究状況」から使う（docs/how_to_use.md）。

## 困ったとき
| 症状 | 確認 |
|---|---|
| 開けない | 家のPCの電源・ネット、スマホの Tailscale が「接続」か。家のPCで `Get-ScheduledTask Labo*` の State が Running か |
| 起動の記録 | `data\server-start.log`（起動時刻とアドレス）、`data\server.log`・`data\server.log.err`（画面の出力） |
| 最新版にすぐしたい | **スマホの画面「研究状況」の「最新版に更新」**（管理者のみ。1分ほどで戻る。ログインはそのまま）。家のPCなら `Start-ScheduledTask LaboServerDailyUpdate` でも可 |
| Windows のパスワードを変えた | 手順3をもう一度実行 |
| やめたい | 管理者の PowerShell で `powershell -ExecutionPolicy Bypass -File scripts\windows\uninstall_home_server.ps1` |

## 安全のために
- 待ち受けるのは Tailscale のアドレスだけ。家の Wi-Fi の他の機器やインターネットからは開けない（ファイアウォールでも Tailscale の範囲だけ許可）。
- ルーターのポート開放はしない。
- ログインはこれまでどおりトークン必須。トークンはスマホのブラウザに残るので、スマホ自体にもロックをかける。
