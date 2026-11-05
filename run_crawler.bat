@echo off
chcp 65001 > nul
title 台灣法學試題與判解自動爬梳流水線
echo ========================================================
echo        台灣法學試題與權威判解自動爬梳
echo ========================================================
echo.

cd /d "%~dp0"
set PY_EXE=C:\Users\mis\miniconda3\python.exe
if not exist "%PY_EXE%" set PY_EXE=python

"%PY_EXE%" mass_crawler_pipeline.py

echo.
echo 爬梳流程完成。
pause
