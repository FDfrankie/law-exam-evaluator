#!/usr/bin/env bash
# 司律考試 AI 評分與命題系統啟動腳本 (Git Bash / WSL / Linux)

cd "$(dirname "$0")" || exit 1

echo "========================================================"
echo "       正在啟動 司律考試 AI 自動評分與命題大師..."
echo "========================================================"

/c/Users/mis/miniconda3/python.exe -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
