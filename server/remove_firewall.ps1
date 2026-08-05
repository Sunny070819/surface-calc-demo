<#
Removes the "Flask POC 5000" inbound firewall rule created by
allow_firewall.ps1. Run this once the LAN demo is over.

Must be run elevated (Remove-NetFirewallRule requires it).
#>

$ErrorActionPreference = "Stop"

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "此腳本需要系統管理員權限才能修改防火牆規則。" -ForegroundColor Yellow
    Write-Host "請在檔案總管對 remove_firewall.ps1 按右鍵 -> 以系統管理員身分執行，或用系統管理員 PowerShell 視窗重新執行。" -ForegroundColor Yellow
    exit 1
}

$ruleName = "Flask POC 5000"

$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if ($existing) {
    $existing | Remove-NetFirewallRule
    Write-Host "已移除防火牆規則「$ruleName」。"
} else {
    Write-Host "找不到防火牆規則「$ruleName」，可能本來就沒建立或已經移除過了。"
}

