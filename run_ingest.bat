@echo off
chcp 65001 >nul
echo ========================================================
echo    🚀 司法院裁判開放資料串流低記憶體匯入 (一鍵啟動)
echo ========================================================
echo.
echo 正在啟動 PowerShell 串流匯入引擎...
echo 自動掃描: G:\我的雲端硬碟\LawExamData\data\judgements 及 opendata_inbox
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0schedule_ingest.ps1"

echo.
echo ========================================================
echo 執行完畢。請查看日誌或開啟 Streamlit 查看匯入總筆數。
echo ========================================================
pause

