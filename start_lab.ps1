# 特徴量ラボを最新版にしてから起動する（ダブルクリックは start_lab.bat）
# 初回だけ：Git for Windows を入れて git clone で取得し、接続文字列を利用者の環境変数に保存しておく（docs/how_to_use.md）
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
$port = if ($env:LABO_PORT) { $env:LABO_PORT } else { "8765" }
Start-Job -ScriptBlock { param($p) Start-Sleep -Seconds 4; Start-Process "http://127.0.0.1:$p/" } -ArgumentList $port | Out-Null
python -m labo.server
