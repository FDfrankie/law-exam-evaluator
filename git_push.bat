@echo off
chcp 65001 >nul
echo ========================================================
echo        正在同步更新並推送到 GitHub (Streamlit Cloud)...
echo ========================================================

cd /d "%~dp0"

git add -A
git commit -m "Update law exam app: %date% %time%"
git push origin main

echo ========================================================
echo 同步完成！Streamlit Community Cloud 將在數秒內自動重新部署！
echo ========================================================
pause
