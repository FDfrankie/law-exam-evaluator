# 🏛️ 司律手寫試卷評分、出題、真題庫檢索與六法爭點註記大師 (Taiwan Law Exam AI Grader)

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://law-exam-evaluator.streamlit.app/)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

專為台灣司法官、律師國家考試、法研所與司法特考考生量身打造的頂級多模態法學 AI 研習系統。整合多模態視覺 OCR、IRAC 三段論法診斷、歷屆真題庫檢索、智能出題擬答、主管機關函釋、立法歷史沿革與條文實務關聯引擎。

---

## 🌟 九大核心功能模組 (Core Modes)

1. **📝 試卷評分與手寫辨識 (Mode 1)**：
   - 支援手寫拍照、PDF、Word 檔案上傳。
   - 採用多模態視覺模型進行文字辨識、IRAC 三段論法診斷、爭點開標與深度論證評分。
   - 支援從雲端實戰試題大庫（含民法/刑法百題、考古題）一鍵帶入題目。

2. **🎯 司律模擬出題 (Mode 2)**：
   - 一試選擇題（單選、複選）全真模擬。
   - 二試實例申論題（命題、客製考點、自動配分）。

3. **📚 歷年真題庫檢索 (Mode 3)**：
   - 收錄考選部近 30 年司律二試、司法特考歷屆真題。
   - 收錄頂尖大學法研所、轉學考歷屆試題。
   - 實時收錄全雲端實戰試題大庫與百題爭點演練（93 份題庫）。

4. **⚡ AI 爭點破題與示範高分擬答 (Mode 4)**：
   - 針對輸入之題目事實，自動提煉二試上位卷 IRAC 開標、大前提法條判解、小前提事實驗證與結論。

5. **🔍 統一法學檢索樞紐 (Mode 5)**：
   - 整合全國法規、司法院裁判書、法源法律網、七法 Lawsnote、立法院法律系統之一站式檢索。

6. **📄 AI 長篇裁判與行政函釋要旨自動精鍊 (Mode 6)**：
   - 支援裁判書字號或全文輸入。
   - 自動提煉當事人主張、歷審攻防、核心法律見解與判決主文要旨。

7. **⚖️ 裁判橫向比對研析與爭點判決立場分析 (Mode 7)**：
   - 兩案事實、立論根據、法律見解分歧之橫向對比分析。
   - 爭點採何說自動歸納（肯定說、否定說、折衷說）。

8. **📖 智慧六法全書與條文爭點判解註記 (Mode 8)**：
   - 涵蓋民法、刑法、憲法、行政法、民事訴訟法、刑事訴訟法、公司法、證交法、保險法等核心六法。
   - 各條文精準關聯：
     - 🏛️ 權威司法判解（最高法院大法庭裁定、具參考價值裁判）
     - 📋 關聯法規命令與細則
     - 📜 主管機關行政函釋（經濟部/智財局/金管會等）
     - 🕰️ 立法理由與歷次修正條文對照
     - 🎯 實戰試題與百題爭點演練（民法百題、刑法百題）
     - 📘 課輔與授課講義
     - 📝 純個人讀書筆記
     - 🤖 AI 深度釋析與作答模版
   - 提供「🔄 聯網一鍵同步最新修法」，即時更新立法院三讀修正條文與最新公布施行法規。

9. **💬 法律智慧助手與全方位諮詢 (Mode 9)**：
   - 涵蓋各民事、刑事、行政實務爭議之深度諮詢與解答。

---

## 📁 專案架構目錄說明

`
code/
├── app.py                         # Streamlit Web 圖形介面主程式 (九大模式入口)
├── config.py                      # 系統全域路徑、Gemini API 金鑰與模型設定
├── evaluator.py                   # 司律手寫試卷評分與 IRAC 診斷核心引擎
├── exam_generator.py              # 一試選擇題與二試實例題模擬出題引擎
├── doc_parser.py                  # 多模態文件解析器 (PDF, DOCX, 影像 OCR)
│
├── six_codes_engine.py            # 智慧六法全書與條文爭點判解註記引擎
├── six_codes_updater.py           # 六法聯網更新引擎 (即時爬取最新修法)
├── admin_rulings_engine.py        # 主管機關行政函釋與法規命令檢索引擎
├── legal_query_engine.py          # 統一法學檢索樞紐與裁判/釋字檢索引擎
├── legal_summarizer_engine.py     # AI 裁判要旨精鍊與爭點橫向比對引擎
├── legal_qa_engine.py             # 全方位通用法律諮詢引擎
├── core_issues_taxonomy.py        # 司律二試 50+ 核心爭點大典
├── community_archive_engine.py    # 社群試題、講義與筆記實時典藏引擎
│
├── exam_bank_crawler.py           # 考選部歷屆真題與大學法研所考題爬蟲 (整合 MoexCrawler)
├── ingest_user_notes_to_sft.py    # 雲端硬碟個人筆記/百題同步與 SFT 蒸餾
├── ingest_national_laws.py        # 全國法規資料庫下載與核心法條知識庫構建
├── harvest_landmark_precedents.py # 權威裁判、大法庭裁定建庫與筆記裁判擴充
├── harvest_constitutional_corpus.py # 憲法法庭判決與大法官解釋文整理
├── merge_all_sft_datasets.py      # SFT 微調資料集合併驗證與加權平衡器
│
├── data/
│   ├── drive_notes_manifest.json  # 雲端硬碟 700+ 份學習資產結構化清單
│   ├── national_laws/             # 全國法規、六法條文與立法沿革庫
│   ├── raw_exams/                 # 歷屆試題目錄、行政法300題庫與判解索引
│   └── training_data/             # 模型微調訓練資料集 (Verified / Balanced / SFT)
│
├── train_evaluator.py             # 本地端 SFT 微調腳本 (Unsloth / Hugging Face)
├── train_colab.ipynb              # Google Colab GPU 微調筆記本
├── train_kaggle.ipynb             # Kaggle GPU 微調筆記本
├── run_app.bat                    # 本地端 Streamlit 一鍵啟動腳本
└── requirements.txt               # 專案依賴套件清單
`

---

## 🚀 快速上手 (Quick Start)

### 1. 安裝環境與套件
`ash
pip install -r requirements.txt
`

### 2. 設定環境變數
在 code/.env 中填入 Google Gemini API Key：
`env
GEMINI_API_KEY=your_api_key_here
`

### 3. 本地啟動 Web 介面
`ash
streamlit run app.py
`
或在 Windows 上直接雙擊執行 
un_app.bat。
