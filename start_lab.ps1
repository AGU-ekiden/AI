# 特徴量ラボを最新版にしてから起動する（ダブルクリックは start_lab.bat）
#   -Service : 家のPCで常時起動するとき（タスクスケジューラから実行）。ブラウザを開かず、
#              Tailscale のアドレスだけで待ち受け、画面の出力を data\server.log に残す。
param([switch]$Service)
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

if (Test-Path ".git") {
    Write-Host "最新版を確認しています…"
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { Write-Host "更新できませんでした（ネットワークか、手元のファイルの変更が原因）。今の版で起動します。" }
} else {
    Write-Host "git で取得したフォルダではないため、自動更新はしません（docs/how_to_use.md の「初回だけ」を参照）。"
}

if (-not $env:RKM_READONLY_DSN) {
    $env:RKM_READONLY_DSN = [Environment]::GetEnvironmentVariable("RKM_READONLY_DSN", "User")
}
if (-not $env:RKM_READONLY_DSN) {
    Write-Host "接続文字列（RKM_READONLY_DSN）が未設定です。前回の集計だけを表示します。"
}
$env:LABO_DATA_SOURCE = "rkm"
$env:PYTHONUTF8 = "1"
$port = if ($env:LABO_PORT) { $env:LABO_PORT } else { "8765" }

if (-not $Service) {
    Start-Job -ScriptBlock { param($p) Start-Sleep -Seconds 4; Start-Process "http://127.0.0.1:$p/" } -ArgumentList $port | Out-Null
    python -m labo.server
    exit
}

# ---- 常時起動（家のPC）----
function Get-TailscaleIp {
    $exe = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
    if (-not $exe) { $exe = Join-Path $env:ProgramFiles "Tailscale\tailscale.exe" }
    if (-not (Test-Path $exe)) { return $null }
    $ip = & $exe ip -4 2>$null | Select-Object -First 1
    if ($ip -match '^100\.') { return $ip.Trim() } else { return $null }
}
$ip = $null
for ($i = 0; $i -lt 60 -and -not $ip; $i++) {   # 起動直後は Tailscale の接続を最大10分待つ
    $ip = Get-TailscaleIp
    if (-not $ip) { Start-Sleep -Seconds 10 }
}
if ($ip) {
    $env:LABO_HOST = $ip
} else {
    $env:LABO_HOST = "127.0.0.1"   # Tailscale が無ければこのPCからだけ開ける
}
$log = Join-Path $PSScriptRoot "data\server.log"
"$(Get-Date -Format s) 起動 http://$($env:LABO_HOST):$port/" | Out-File -FilePath (Join-Path $PSScriptRoot "data\server-start.log") -Append -Encoding utf8
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue).Source }
Start-Process -FilePath $py -ArgumentList "-m", "labo.server" -WorkingDirectory $PSScriptRoot -NoNewWindow -Wait `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err"
