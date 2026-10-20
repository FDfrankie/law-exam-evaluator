@echo off
echo ========================================================
echo        Starting Law Exam AI App (Local Streamlit)...
echo        URL: http://localhost:8501
echo ========================================================

CALL "C:\Users\mis\miniconda3\Scripts\activate.bat" base
python -m streamlit run "%~dp0app.py" --server.port 8501 %*

pause
