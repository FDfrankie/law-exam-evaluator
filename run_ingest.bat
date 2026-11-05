@echo off
title 司法院裁判資料庫低記憶體串流匯入
echo ========================================================
echo    司法院裁判資料庫低記憶體入庫引擎 (斷點續傳)
echo ========================================================
echo.
echo Python 直譯器 : C:\Users\mis\miniconda3\python.exe
echo 程式腳本路徑 : G:\我的雲端硬碟\LawExamData\code\ingest_opendata_lowmem.py
echo.
echo [提示] 具備完全斷點續傳功能，任何時候關閉視窗都不會遺失進度。
echo.
echo ========================================================
echo [開始執行串流入庫...]
echo ========================================================
echo.

"C:\Users\mis\miniconda3\python.exe" -u "G:\我的雲端硬碟\LawExamData\code\ingest_opendata_lowmem.py"

echo.
echo ========================================================
echo 執行結束。
echo ========================================================
pause
