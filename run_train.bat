@echo off
title Taiwan Law Exam Model Fine-Tuning
echo ========================================================
echo   Taiwan Law Exam Model SFT Fine-Tuning
echo ========================================================
echo.
echo Dataset: G:\§Úªº¶³ºÝµwºÐ\LawExamData\data\training_data\law_exam_verified_sft.jsonl
echo Checkpoints: G:\§Úªº¶³ºÝµwºÐ\LawExamData\data\checkpoints\law_evaluator_qwen
echo Python: C:\Users\mis\miniconda3\python.exe
echo.

cd /d "%~dp0"
"C:\Users\mis\miniconda3\python.exe" train_evaluator.py --epochs 1 --batch_size 2 --max_samples 100

echo.
echo Training process completed.
pause
