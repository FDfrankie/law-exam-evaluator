@echo off
chcp 65001 > nul
title Git 專案同步與雲端推送
echo ========================================================
echo        Git 自動提交與 GitHub 遠端同步
echo ========================================================

cd /d "%~dp0"
git add -A
git commit -m "fix: auto sync and optimize codebase"
git push origin main

echo.
echo 同步完成。
pause
