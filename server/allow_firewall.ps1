<#
Opens inbound TCP 5000 so LAN devices can reach the Flask POC (see
start_server.ps1). Scoped to Private/Domain network profiles only -- never
Public -- so this doesn't open the port to an untrusted network (e.g. campus
guest wifi classified as Public). Run remove_firewall.ps1 when the demo is
over to close it back up.

Must be run elevated (New-NetFirewallRule requires it).
#>

$ErrorActionPreference = "Stop"

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "此腳本需要系統管理員權限才能修改防火牆規則。" -ForegroundColor Yellow
    Write-Host "請在檔案總管對 allow_firewall.ps1 按右鍵 -> 以系統管理員身分執行，或用系統管理員 PowerShell 視窗重新執行。" -ForegroundColor Yellow
    exit 1
}

$ruleName = "Flask POC 5000"

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "防火牆規則「$ruleName」已存在，略過建立。"
} else {
    New-NetFirewallRule `
        -DisplayName $ruleName `
        -Direction Inbound `
        -Protocol TCP `
        -LocalPort 5000 `
        -Action Allow `
        -Profile Private,Domain | Out-Null
    Write-Host "已建立防火牆規則「$ruleName」-- 開放 TCP 5000 inbound（僅限私人/網域網路，不含公用網路）。"
}

Write-Host ""
Write-Host "Demo 結束後，請以系統管理員身分執行 remove_firewall.ps1 收回這條規則。"

