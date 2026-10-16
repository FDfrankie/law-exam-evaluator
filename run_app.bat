@echo off
REM Activate conda environment if needed
CALL "C:\Users\mis\miniconda3\Scripts\activate.bat" base

echo ========================================================
echo   司律 AI 評分系統正在啟動...
echo   本機電腦存取: http://localhost:8501
echo   手機連線網址: http://192.168.0.10:8501
echo ========================================================

REM Run the Streamlit application
python -m streamlit run "%~dp0app.py" --server.address 0.0.0.0 --server.port 8501 %*

REM Keep the window open after execution
pause
