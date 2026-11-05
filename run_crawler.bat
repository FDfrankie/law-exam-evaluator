@echo off
title Taiwan Law Exam Crawler and SFT Generator
echo ========================================================
echo   Taiwan Law Exam Data Harvester
echo ========================================================
echo.
echo Target Storage: G:\§Úªº¶³ºÝµwºÐ\LawExamData\
echo Python interpreter: C:\Users\mis\miniconda3\python.exe
echo.

cd /d "%~dp0"
"C:\Users\mis\miniconda3\python.exe" mass_crawler_pipeline.py

echo.
echo Harvester process finished.
pause
