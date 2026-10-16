#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1
echo "========================================================"
echo " Starting Law Exam AI Streamlit Server..."
echo "========================================================"
python -m streamlit run app.py --server.port 8501
