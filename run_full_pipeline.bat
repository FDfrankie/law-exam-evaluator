@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Taiwan Law Exam Master Ingestion Pipeline

echo ========================================================
echo   Taiwan Law Exam Master Ingestion Pipeline (1 Million SFT)
echo ========================================================
echo.

cd /d "%~dp0"

echo [1/9] Ingesting National Laws and Regulations...
python pipelines/ingest_national_laws.py

echo.
echo [2/9] Building Statutory Articles Corpus...
python pipelines/build_legislative_catalog.py

echo.
echo [3/9] Harvesting Constitutional Court Decisions and Interpretations...
python pipelines/harvest_constitutional_corpus.py

echo.
echo [4/9] Compiling Master Theories and Jurists Matrix...
python pipelines/law_master_theories_matrix.py

echo.
echo [5/9] Harvesting Authentic Court Decisions and Precedents...
python pipelines/mass_crawler_pipeline.py

echo.
echo [6/9] Ingesting Academic Teaching Notes and Coursework...
python pipelines/ingest_academic_resources.py

echo.
echo [7/9] Ingesting Bar Exam MCQs and Past Exams to SFT...
python pipelines/ingest_exam_banks_to_sft.py

echo.
echo [8/9] Generating 1,000,000 Multi-Task Judicial Reasoning SFT Triples...
python pipelines/generate_1m_judicial_reasoning.py

echo.
echo [9/9] Merging and Validating Master 1,000,000+ Unified SFT Corpus...
python pipelines/merge_all_sft_datasets.py

echo.
echo ========================================================
echo   Master 1 Million+ Legal SFT Pipeline Complete!
echo ========================================================
pause
