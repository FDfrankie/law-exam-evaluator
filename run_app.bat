@echo off
chcp 65001 > nul
title 司律 AI 評分與命題大師 (Streamlit)
echo ========================================================
echo        啟動司律考試 AI 評分、命題與判解研析系統...
echo        本機連線位址: http://localhost:8501
echo ========================================================

cd /d "%~dp0"
set PY_EXE=C:\Users\mis\miniconda3\python.exe
if not exist "%PY_EXE%" set PY_EXE=python

"%PY_EXE%" -m streamlit run app.py --server.port 8501 %*

pause
