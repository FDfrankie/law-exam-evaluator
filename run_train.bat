@echo off
chcp 65001 > nul
title 司律法學大模型微調訓練
echo ========================================================
echo        司律法學評分與擬答模型微調訓練
echo ========================================================
echo.

cd /d "%~dp0"
set PY_EXE=C:\Users\mis\miniconda3\python.exe
if not exist "%PY_EXE%" set PY_EXE=python

"%PY_EXE%" train_evaluator.py --epochs 1 --batch_size 2 --max_samples 100

echo.
echo 模型微調作業完成。
pause
