@echo off
chcp 65001 > nul
title 司法院裁判資料庫全自動低記憶體串流入庫
echo ========================================================
echo        司法院裁判資料庫全自動串流入庫 (斷點續傳)
echo ========================================================
echo.

cd /d "%~dp0"
set PY_EXE=C:\Users\mis\miniconda3\python.exe
if not exist "%PY_EXE%" set PY_EXE=python

"%PY_EXE%" -u ingest_opendata_lowmem.py

echo.
echo ========================================================
echo 入庫作業執行完畢。
echo ========================================================
pause
