@echo off
title Law Exam AI App (Streamlit)
echo ========================================================
echo        Starting Law Exam AI App (Local Streamlit)...
echo        URL: http://localhost:8501
echo ========================================================

cd /d "%~dp0"
"C:\Users\mis\miniconda3\python.exe" -m streamlit run app.py --server.port 8501 %*

pause
