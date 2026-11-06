@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title 司法院裁判資料庫 全自動低記憶體串流入庫 (斷點續傳)

cd /d "%~dp0"
set "PY_EXE=C:\Users\mis\miniconda3\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=python"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

echo ========================================================
echo    🚀 司法院裁判資料庫 全自動低記憶體串流入庫 (斷點續傳)
echo ========================================================
echo  Python 環境 : %PY_EXE%
echo  工作目錄   : %~dp0
echo  入庫引擎   : ingest_opendata_lowmem.py
echo ========================================================
echo.

"%PY_EXE%" -X utf8 -u ingest_opendata_lowmem.py %*

set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo ========================================================
if %EXIT_CODE% equ 0 (
    echo [成功] 入庫作業已圓滿完成！ (代碼: 0)
) else (
    echo [提示] 串流入庫已停止或中斷 (結束代碼: %EXIT_CODE%)。
    echo 系統具備自動斷點續傳與 0 位元鎖定檔自我修復功能，隨時雙擊本程式即可無縫繼續！
)
echo ========================================================
pause
