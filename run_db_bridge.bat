@echo off
chcp 65001 > nul
title 司律百萬裁判母庫本機遠端橋接伺服器 (FastAPI Bridge)
echo ========================================================
echo    🌐 啟動本機 797 萬筆裁判資料庫遠端橋接 API 伺服器
echo    監聽位址: http://127.0.0.1:8765
echo    搭配 Cloudflare Tunnel / ngrok 即可讓 Streamlit Cloud 即時查詢全量母庫
echo ========================================================

cd /d "%~dp0"
set PY_EXE=C:\Users\mis\miniconda3\python.exe
if not exist "%PY_EXE%" set PY_EXE=python

"%PY_EXE%" -u db_bridge_server.py %*
pause
