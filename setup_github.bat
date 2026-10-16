@echo off
chcp 65001 >nul
echo ========================================================
echo        司律 AI 評分系統 - 首次綁定 GitHub 倉庫
echo ========================================================
echo.
echo 請先在 GitHub (https://github.com/new) 建立一個空白 Repository
echo （不要勾選 Add README，也不要勾選 .gitignore）。
echo.
set /p REPO_URL="請貼上您的 GitHub 倉庫網址 (例如 https://github.com/你的帳號/專案名稱.git): "

cd /d "%~dp0"
git remote remove origin 2>nul
git remote add origin %REPO_URL%
git branch -M main

echo.
echo 正在推送到 GitHub...
git push -u origin main

echo.
echo ========================================================
echo 綁定與首次推送完成！
echo 以後程式碼有任何修改，只需點擊 git_push.bat 即可一鍵自動同步！
echo ========================================================
pause
