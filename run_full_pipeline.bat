@echo off
title Taiwan Law Exam Master Ingestion Pipeline
echo ========================================================
echo   Taiwan Law Exam Master Ingestion Pipeline (1 Million SFT)
echo ========================================================
echo.
echo Target Storage: G:\§Úªº¶³ºÝµwºÐ\LawExamData\
echo Python: C:\Users\mis\miniconda3\python.exe
echo.

cd /d "%~dp0"

echo [1/7] Ingesting National Laws and Regulations...
"C:\Users\mis\miniconda3\python.exe" ingest_national_laws.py

echo.
echo [2/7] Harvesting Landmark Constitutional & Supreme Court Precedents...
"C:\Users\mis\miniconda3\python.exe" harvest_landmark_precedents.py

echo.
echo [3/7] Compiling Master Theories and Jurists Matrix...
"C:\Users\mis\miniconda3\python.exe" law_master_theories_matrix.py

echo.
echo [4/7] Harvesting Authentic Court Decisions & Filtering Procedural Dismissals...
"C:\Users\mis\miniconda3\python.exe" mass_crawler_pipeline.py

echo.
echo [5/7] Ingesting Academic Teaching Notes & Coursework...
"C:\Users\mis\miniconda3\python.exe" ingest_academic_resources.py

echo.
echo [6/7] Ingesting Bar Exam MCQs & Past Exams to SFT...
"C:\Users\mis\miniconda3\python.exe" ingest_exam_banks_to_sft.py

echo.
echo [7/7] Merging & Validating Master Unified SFT Corpus...
"C:\Users\mis\miniconda3\python.exe" merge_all_sft_datasets.py

echo.
echo ========================================================
echo   Master Pipeline Complete!
echo ========================================================
pause
