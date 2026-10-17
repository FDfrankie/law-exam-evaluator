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

echo [1/7] Ingesting National Laws and Regulations...
"C:\Users\mis\miniconda3\python.exe" ingest_national_laws.py

echo.
echo [2/7] Building Statutory Articles Corpus...
"C:\Users\mis\miniconda3\python.exe" build_law_articles_corpus.py

echo.
echo [3/7] Harvesting Constitutional Court Decisions and Interpretations...
"C:\Users\mis\miniconda3\python.exe" harvest_constitutional_corpus.py

echo.
echo [4/7] Compiling Master Theories and Jurists Knowledge...
"C:\Users\mis\miniconda3\python.exe" law_master_theories_matrix.py

echo.
echo [5/7] Harvesting Real Court Decisions across 26 Domains...
"C:\Users\mis\miniconda3\python.exe" mass_crawler_pipeline.py

echo.
echo [6/7] Generating 100,000 Real Court Judgment Legal Reasoning Pairs...
"C:\Users\mis\miniconda3\python.exe" generate_100k_judicial_reasoning.py

echo.
echo [7/7] Merging 100,000+ Unified SFT Fine-Tuning Corpus...
"C:\Users\mis\miniconda3\python.exe" merge_all_sft_datasets.py

echo.
echo ========================================================
echo   Master 100k+ Pipeline Complete! All datasets stored on Drive.
echo ========================================================
pause
