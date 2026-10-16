@echo off
chcp 65001 >nul
title Taiwan Law Exam Master Ingestion Pipeline

echo ========================================================
echo   Taiwan Law Exam Master Ingestion Pipeline
echo   Scale: 100k - 1M Scale Legal Knowledge Engine
echo ========================================================
echo.
echo Target Storage: G:\LawExamData\
echo Python: C:\Users\mis\miniconda3\python.exe
echo.

cd /d "G:\我的雲端硬碟\LawExamData\code"

echo [1/5] Ingesting National Laws and Regulations...
"C:\Users\mis\miniconda3\python.exe" ingest_national_laws.py

echo.
echo [2/5] Building Statutory Articles Corpus...
"C:\Users\mis\miniconda3\python.exe" build_law_articles_corpus.py

echo.
echo [3/5] Compiling Master Theories and Jurists Knowledge...
"C:\Users\mis\miniconda3\python.exe" law_master_theories_matrix.py

echo.
echo [4/5] Harvesting Real Court Decisions across 26 Domains...
"C:\Users\mis\miniconda3\python.exe" mass_crawler_pipeline.py

echo.
echo [5/5] Merging Unified SFT Fine-Tuning Corpus...
"C:\Users\mis\miniconda3\python.exe" merge_all_sft_datasets.py

echo.
echo ========================================================
echo   Master Pipeline Complete! All datasets stored on Drive.
echo ========================================================
pause
