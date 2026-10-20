# 家のPCで特徴量ラボを常時起動にする（管理者の PowerShell で1回だけ実行）
#   powershell -ExecutionPolicy Bypass -File scripts\windows\install_home_server.ps1
# 設定すること：
#   1. PC起動時に特徴量ラボを自動起動（サインインしていなくても動く）
#   2. 毎朝4時に最新版を取得して起動し直す
#   3. Windows ファイアウォールで Tailscale（100.64.0.0/10）からの接続だけを許可
#   4. 電源接続時はスリープ・休止しない
# 元に戻すときは scripts\windows\uninstall_home_server.ps1
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$port = 8765

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw "管理者として実行してください（スタートメニューで PowerShell を右クリック →「管理者として実行」）。" }

Write-Host "確認中…"
foreach ($cmd in "git", "python") {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd が見つかりません。docs/home_server.md の手順1を先に行ってください。" }
}
if (-not (Test-Path (Join-Path $root ".git"))) { throw "git clone で取得したフォルダで実行してください（自動更新に必要）。" }
& python -c "import psycopg" 2>$null
if ($LASTEXITCODE -ne 0) { throw "psycopg が入っていません。python -m pip install -r requirements-db.txt を実行してください。" }
if (-not [Environment]::GetEnvironmentVariable("RKM_READONLY_DSN", "User")) {
    Write-Warning "接続文字列（RKM_READONLY_DSN）が未保存です。起動はしますが前回の集計だけの表示になります。"
}
$ts = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe"
if (-not (Test-Path $ts)) { Write-Warning "Tailscale が見つかりません。入れるまではこのPCからだけ開けます。" }

Write-Host "サインインなしで動かすため、この PC にサインインするときのパスワードを入力してください（Windows のタスクに保存され、ファイルには残りません）。"
Write-Host "Microsoft アカウントでサインインしている場合は、その Microsoft アカウントのパスワードです（PIN ではありません）。"
$cred = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" -Message "このPCのサインイン用パスワード"
$pw = $cred.GetNetworkCredential().Password

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) -MultipleInstances IgnoreNew

# 1. 起動時に自動起動
$start = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $root `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\start_lab.ps1`" -Service"
Register-ScheduledTask -TaskName "LaboServer" -Description "特徴量ラボ（常時起動）" -Action $start `
    -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $settings `
    -User $cred.UserName -Password $pw -RunLevel Limited -Force | Out-Null

# 2. 毎朝4時に起動し直す（その時に最新版を取得）
$restartCmd = "Stop-ScheduledTask -TaskName LaboServer; " +
    "Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id `$_.OwningProcess -Force }; " +
    "Start-Sleep -Seconds 5; Start-ScheduledTask -TaskName LaboServer"
$restart = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$restartCmd`""
Register-ScheduledTask -TaskName "LaboServerDailyUpdate" -Description "特徴量ラボを最新版にして起動し直す" -Action $restart `
    -Trigger (New-ScheduledTaskTrigger -Daily -At 4am) -Settings $settings `
    -User $cred.UserName -Password $pw -RunLevel Limited -Force | Out-Null
$pw = $null

# 3. ファイアウォール：Tailscale からだけ許可
Get-NetFirewallRule -DisplayName "Labo (Tailscale only)" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName "Labo (Tailscale only)" -Direction Inbound -Protocol TCP -LocalPort $port `
    -RemoteAddress 100.64.0.0/10 -Action Allow -Profile Any | Out-Null

# 4. 電源につながっている間はスリープ・休止しない（画面は消えてよい）
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

Start-ScheduledTask -TaskName "LaboServer"
Write-Host ""
Write-Host "設定しました。1分ほどで起動します。"
if (Test-Path $ts) {
    $ip = & $ts ip -4 2>$null | Select-Object -First 1
    if ($ip) { Write-Host "スマホ（Tailscale 接続中）から開くアドレス: http://$($ip.Trim()):$port/" }
}
Write-Host "このPCから確認するときは data\server-start.log に表示されるアドレスを開いてください。"
