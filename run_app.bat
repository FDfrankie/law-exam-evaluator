@echo off
chcp 65001 >nul
title Law Exam AI App (Local Streamlit)
echo ========================================================
echo        Starting Law Exam AI App (Local Streamlit)...
echo        URL: http://localhost:8501
echo ========================================================

cd /d "%~dp0"
python -m streamlit run "%~dp0app.py" --server.port 8501 %*

pause
