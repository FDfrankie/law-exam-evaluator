@echo off
echo ========================================================
echo        Syncing and Pushing Updates to GitHub...
echo ========================================================

cd /d "%~dp0"

git add -A
git commit -m "Auto update: %date% %time%"
git push origin main

echo.
echo ========================================================
echo Push complete! Streamlit Cloud will auto-redeploy!
echo ========================================================
pause
