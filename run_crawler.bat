@echo off
chcp 65001 >nul
title Taiwan Law Exam Crawler and SFT Generator

echo ========================================================
echo   Taiwan Law Exam Data Harvester
echo ========================================================
echo.

cd /d "%~dp0"
python pipelines/mass_crawler_pipeline.py

echo.
echo Harvester process finished.
pause
