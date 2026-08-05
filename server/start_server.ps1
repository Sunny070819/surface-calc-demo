<#
Starts the Flask app with the SAP ICF connection env vars set.

SAP_ICF_URL / SAP_ICF_USERNAME / SAP_ICF_VERIFY_SSL are not secret (the URL and
account name), so they're set directly below. SAP_ICF_PASSWORD is secret and is
NEVER written to this file: it's read from a gitignored .env in this directory
(SAP_ICF_PASSWORD=xxx) if present, otherwise prompted for interactively and only
ever held in this process's environment.
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$env:SAP_ICF_URL = "https://ncus4ap.mgt.ncu.edu.tw:44320/sap/bc/zai_dim?sap-client=700"
$env:SAP_ICF_USERNAME = "CERP16"
$env:SAP_ICF_VERIFY_SSL = "false"  # self-signed cert on the school SAP host

# Bind on all interfaces so LAN devices (teammates, phones, demo audience) can
# reach the app.py, not just this machine. debug MUST be false once bound off
# 127.0.0.1 -- the Werkzeug debugger console is a remote-code-execution risk to
# anyone who can reach the port (see app.py's own comment on this).
$env:FLASK_RUN_HOST = "0.0.0.0"
$env:FLASK_DEBUG = "false"

$envFile = Join-Path $ScriptDir ".env"
$password = $null

if (Test-Path $envFile) {
    $line = Get-Content $envFile | Where-Object { $_ -match '^\s*SAP_ICF_PASSWORD\s*=' } | Select-Object -First 1
    if ($line) {
        $password = ($line -split '=', 2)[1].Trim()
    }
}

if ([string]::IsNullOrEmpty($password)) {
    $secure = Read-Host -Prompt "SAP_ICF_PASSWORD (帳號 $($env:SAP_ICF_USERNAME))" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $password = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

if ([string]::IsNullOrEmpty($password)) {
    Write-Error "SAP_ICF_PASSWORD 未設定（.env 沒有值，也沒有手動輸入），中止啟動。"
    exit 1
}

$env:SAP_ICF_PASSWORD = $password
$password = $null

$timeoutDisplay = "30（config.py 預設值）"
if ($env:SAP_ICF_TIMEOUT_SECONDS) { $timeoutDisplay = $env:SAP_ICF_TIMEOUT_SECONDS }

Write-Host "SAP_ICF_URL         = $env:SAP_ICF_URL"
Write-Host "SAP_ICF_USERNAME    = $env:SAP_ICF_USERNAME"
Write-Host "SAP_ICF_PASSWORD    = ********（已設定）"
Write-Host "SAP_ICF_VERIFY_SSL  = $env:SAP_ICF_VERIFY_SSL"
Write-Host "SAP_ICF_TIMEOUT_SECONDS = $timeoutDisplay"
Write-Host ""

# Best-effort LAN IPv4 detection: skip loopback/link-local addresses and
# adapters that are down or virtual (VPN, Hyper-V, WSL, etc.), take the first
# real, up, physical-ish adapter's address.
function Get-LanIPv4 {
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        ForEach-Object {
            $adapter = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
            if ($adapter -and $adapter.Status -eq "Up" -and -not $adapter.Virtual) {
                $_.IPAddress
            }
        } |
        Select-Object -First 1
}

$lanIp = Get-LanIPv4

Write-Host "本機測試：http://127.0.0.1:5000"
if ($lanIp) {
    Write-Host "其他裝置請開：http://$($lanIp):5000"
} else {
    Write-Host "（找不到區網 IPv4 位址，其他裝置可能無法連入 -- 手動用 ipconfig 確認本機 IP）"
}
Write-Host ""
Write-Host "已綁定 0.0.0.0，同網路裝置都連得到這個 port -- 若還沒開防火牆，先以系統管理員身分執行 allow_firewall.ps1。"
Write-Host "Demo 結束後記得跑 remove_firewall.ps1 收回規則。"
Write-Host ""

& "$ScriptDir\.venv\Scripts\python.exe" "$ScriptDir\app.py"


