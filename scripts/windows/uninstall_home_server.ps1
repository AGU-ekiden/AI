# 家のPCの常時起動設定を元に戻す（管理者の PowerShell で実行）。データ（data フォルダ）は消さない。
$ErrorActionPreference = "Continue"
foreach ($t in "LaboServerDailyUpdate", "LaboServer") {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
}
Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Get-NetFirewallRule -DisplayName "Labo (Tailscale only)" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Write-Host "常時起動の設定を外しました（スリープの設定は Windows の設定 → 電源 で戻してください）。"
