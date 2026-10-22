# ==============================================================================
# 司法院裁判開放資料自動串流低記憶體排程匯入腳本 (schedule_ingest.ps1)
# ==============================================================================

$ErrorActionPreference = "Continue"

# 1. 定位工作目錄與紀錄目錄
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -Path $ScriptDir

$LogDir = Join-Path $ScriptDir "logs\ingest"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "ingest_$Timestamp.log"

Write-Output "==========================================================" | Tee-Object -FilePath $LogFile
Write-Output "🚀 啟動司法院裁判書開放資料自動串流匯入排程" | Tee-Object -FilePath $LogFile -Append
Write-Output "時間: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Tee-Object -FilePath $LogFile -Append
Write-Output "工作目錄: $ScriptDir" | Tee-Object -FilePath $LogFile -Append
Write-Output "==========================================================" | Tee-Object -FilePath $LogFile -Append

# 2. 探測 Conda 或 Python 執行檔
$PythonExe = $null

$CondaCandidates = @(
    "C:\Users\mis\miniconda3\python.exe",
    "C:\ProgramData\miniconda3\python.exe",
    "$env:USERPROFILE\miniconda3\python.exe",
    "$env:USERPROFILE\anaconda3\python.exe",
    "C:\miniconda3\python.exe",
    "C:\anaconda3\python.exe"
)

foreach ($cand in $CondaCandidates) {
    if (Test-Path $cand) {
        $PythonExe = $cand
        break
    }
}

if (-not $PythonExe) {
    $SysPy = Get-Command python -ErrorAction SilentlyContinue
    if ($SysPy) {
        $PythonExe = $SysPy.Source
    }
}

if (-not $PythonExe) {
    Write-Output "❌ 錯誤: 找不到合適的 Conda 或 Python 執行環境！" | Tee-Object -FilePath $LogFile -Append
    exit 1
}

Write-Output "🐍 使用 Python: $PythonExe" | Tee-Object -FilePath $LogFile -Append

# 3. 指定匯入資料來源目錄
$InputDir = "G:\我的雲端硬碟\LawExamData\data\judgements"
if (-not (Test-Path $InputDir)) {
    # 備選本機目錄
    $AltInput = Join-Path $ScriptDir "data\judgements"
    if (Test-Path $AltInput) {
        $InputDir = $AltInput
    } else {
        $InputDir = "G:\My Drive\LawExamData\data\judgements"
    }
}

Write-Output "📂 輸入目標目錄: $InputDir" | Tee-Object -FilePath $LogFile -Append

# 4. 執行串流匯入
$IngestScript = Join-Path $ScriptDir "ingest_opendata_lowmem.py"

& $PythonExe $IngestScript --input $InputDir --batch-size 100 2>&1 | Tee-Object -FilePath $LogFile -Append

$ExitCode = $LASTEXITCODE

Write-Output "==========================================================" | Tee-Object -FilePath $LogFile -Append
if ($ExitCode -eq 0) {
    Write-Output "🎉 司法院開放資料匯入排程成功完成！ExitCode: 0" | Tee-Object -FilePath $LogFile -Append
} else {
    Write-Output "⚠️ 匯入排程結束，ExitCode: $ExitCode" | Tee-Object -FilePath $LogFile -Append
}
Write-Output "紀錄檔已保存至: $LogFile" | Tee-Object -FilePath $LogFile -Append
Write-Output "==========================================================" | Tee-Object -FilePath $LogFile -Append

exit $ExitCode

