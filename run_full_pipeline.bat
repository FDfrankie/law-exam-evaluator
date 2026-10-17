@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Taiwan Law Exam Master Ingestion Pipeline

echo ========================================================
echo   Taiwan Law Exam Master Ingestion Pipeline (1 Million SFT)
echo ========================================================
echo.
echo Target Storage: G:\我的雲端硬碟\LawExamData\
echo Python: C:\Users\mis\miniconda3\python.exe
echo.

cd /d "G:\我的雲端硬碟\LawExamData\code"

echo [1/9] Ingesting National Laws and Regulations...
"C:\Users\mis\miniconda3\python.exe" ingest_national_laws.py

echo.
echo [2/9] Building Statutory Articles Corpus...
"C:\Users\mis\miniconda3\python.exe" build_law_articles_corpus.py

echo.
echo [3/9] Harvesting Constitutional Court Decisions and Interpretations...
"C:\Users\mis\miniconda3\python.exe" harvest_constitutional_corpus.py

echo.
echo [4/9] Compiling Master Theories and Jurists Matrix...
"C:\Users\mis\miniconda3\python.exe" law_master_theories_matrix.py

echo.
echo [5/9] Harvesting Authentic Court Decisions & Filtering Procedural Dismissals...
"C:\Users\mis\miniconda3\python.exe" mass_crawler_pipeline.py

echo.
echo [6/9] Ingesting Academic Teaching Notes & Coursework...
"C:\Users\mis\miniconda3\python.exe" ingest_academic_resources.py

echo.
echo [7/9] Ingesting Bar Exam MCQs (300 Questions) & Past Exams to SFT...
"C:\Users\mis\miniconda3\python.exe" ingest_exam_banks_to_sft.py

echo.
echo [8/9] Generating 1,000,000 Multi-Task Judicial Reasoning SFT Triples...
"C:\Users\mis\miniconda3\python.exe" generate_1m_judicial_reasoning.py

echo.
echo [9/9] Merging & Validating Master 1,000,000+ Unified SFT Corpus...
"C:\Users\mis\miniconda3\python.exe" merge_all_sft_datasets.py

echo.
echo ========================================================
echo   Master 1 Million+ Legal SFT Pipeline Complete!
echo ========================================================
pause
