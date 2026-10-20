@echo off
chcp 65001 >nul
title Taiwan Law Exam Model Fine-Tuning

echo ========================================================
echo   Taiwan Law Exam Model SFT Fine-Tuning
echo ========================================================
echo.

cd /d "%~dp0"
python pipelines/train_evaluator.py --epochs 1 --batch_size 2 --max_samples 100

echo.
echo Training process completed.
pause
