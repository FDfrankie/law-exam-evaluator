@echo off
chcp 65001 >nul
title Taiwan Law Exam Crawler and SFT Generator

echo ========================================================
echo   Taiwan Law Exam Data Harvester
echo ========================================================
echo.
echo Target Storage: G:\LawExamData\
echo Python interpreter: C:\Users\mis\miniconda3\python.exe
echo.

cd /d "G:\我的雲端硬碟\LawExamData\code"
"C:\Users\mis\miniconda3\python.exe" mass_crawler_pipeline.py

echo.
echo Harvester process finished.
pause
