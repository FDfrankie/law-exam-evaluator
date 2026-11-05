@echo off
chcp 65001 > nul
title 司律考試全量法學資料處理主流水線
echo ========================================================
echo        司律考試全量法學資料處理主流水線
echo ========================================================
echo.

cd /d "%~dp0"
set PY_EXE=C:\Users\mis\miniconda3\python.exe
if not exist "%PY_EXE%" set PY_EXE=python

echo [1/7] 全國法規與命令條文匯入...
"%PY_EXE%" ingest_national_laws.py

echo.
echo [2/7] 憲法法庭判決與最高法院原判例爬梳...
"%PY_EXE%" harvest_landmark_precedents.py

echo.
echo [3/7] 法學大師爭點與學說矩陣編譯...
"%PY_EXE%" law_master_theories_matrix.py

echo.
echo [4/7] 裁判全文爬梳與程序駁回實體過濾...
"%PY_EXE%" mass_crawler_pipeline.py

echo.
echo [5/7] 法學教材與課程筆記解析...
"%PY_EXE%" ingest_academic_resources.py

echo.
echo [6/7] 司律一二試歷屆真題庫 SFT 轉化...
"%PY_EXE%" ingest_exam_banks_to_sft.py

echo.
echo [7/7] 全量法學語料驗證與整合...
"%PY_EXE%" merge_all_sft_datasets.py

echo.
echo ========================================================
echo   主流水線全數執行完成！
echo ========================================================
pause
