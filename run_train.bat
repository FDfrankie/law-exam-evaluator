@echo off
chcp 65001 >nul
title Taiwan Law Exam Model Fine-Tuning

echo ========================================================
echo   Taiwan Law Exam Model SFT Fine-Tuning
echo ========================================================
echo.
echo Dataset: G:\LawExamData\training_data\law_exam_verified_sft.jsonl
echo Checkpoints: G:\LawExamData\checkpoints\law_evaluator_qwen
echo Python: C:\Users\mis\miniconda3\python.exe
echo.

cd /d "G:\我的雲端硬碟\LawExamData\code"
"C:\Users\mis\miniconda3\python.exe" train_evaluator.py --epochs 1 --batch_size 2 --max_samples 100

echo.
echo Training process completed.
pause
