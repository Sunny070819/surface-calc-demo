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
Write-Host "啟動 Flask 伺服器 -- http://127.0.0.1:5000"
Write-Host ""

& "$ScriptDir\.venv\Scripts\python.exe" "$ScriptDir\app.py"

