@echo off
title Git Push Sync
echo ========================================================
echo        Git Commit & Push Auto Sync
echo ========================================================

cd /d "%~dp0"
git add -A
git commit -m "Auto update project files"
git push

pause
