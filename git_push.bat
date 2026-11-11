@echo off
chcp 65001 > nul
title Git 專案同步與雲端推送
echo ========================================================
echo        Git 自動提交與 GitHub 遠端同步
echo ========================================================

cd /d "%~dp0"
set "COMMIT_MSG=%~1"
if "%COMMIT_MSG%"=="" set "COMMIT_MSG=chore: sync verified codebase and core DB assets"

git add -A
git status --short
git commit -m "%COMMIT_MSG%"
git push origin main

echo.
echo 同步完成。
pause
