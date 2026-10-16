# ⚖️ 司律考試 AI 評分與命題大師 (Taiwan Law Exam AI Grader)

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://share.streamlit.io/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

專為台灣**司法官暨律師高等考試（司律）**設計的多模態 AI 自動評分、模擬命題與示範擬答系統。搭載 Google **Gemini 2.0 Flash** 視覺模型，支援手寫拍照辨識、PDF/Word 匯入與權威法學論理分析。

---

## 🌟 核心功能

1. **📝 多模態試卷評分與手寫辨識**
   - 支援手機拍照手寫試卷 (JPG/PNG)、文字或掃描版 PDF、Word (.docx)。
   - 繁體法律專門名詞自動校正（三段論法、法條構成要件、請求權基礎）。
   - 四大維度精準評分（滿分 100 分）：
     - **爭點意識（Issue Spotting）** (25分)
     - **法學推論與三段論法（Legal Reasoning）** (25分)
     - **實務見解與學說對比（Precedent & Scholarship）** (25分)
     - **具體事實涵攝（Subsumption）** (25分)
   - 自動抓出命中爭點、漏答爭點與閱卷委員重構優化建議。

2. **🎯 司律模擬出題系統**
   - **一試（選擇題）**：四選一案例測驗題，附詳細解析與法條依據。
   - **二試（實例申論題）**：綜合實例題型，包含案件事實、多角子題與閱卷評分指標。

3. **📖 榜首級權威高分擬答生成**
   - 針對爭議二試題型，即時撰寫符合「開標俐落、大前提嚴謹、各說對比、事實嚴密涵攝」的全國最高分示範作答。

---

## 🚀 部署至 Streamlit Community Cloud（手機電腦 24 小時免費在線）

1. 將本專案 Fork 或 Push 至您的 GitHub 帳號。
2. 開啟 [Streamlit Community Cloud](https://share.streamlit.io/) 並使用 GitHub 登入。
3. 點擊 **「Create app」**：
   - **Repository**：選擇您的 GitHub 倉庫
   - **Branch**：`main`
   - **Main file path**：`app.py`
4. 點擊 **Advanced settings ➔ Secrets**，填入您的 API Key：
   ```toml
   GEMINI_API_KEY = "你的_Gemini_API_Key"
   ```
5. 點擊 **「Deploy!」**，數秒後即可在手機、平板與任何電腦透過專屬網址隨時隨地開啟！

---

## 💻 本地端本機執行

```bash
# 1. 安裝相依套件
pip install -r requirements.txt

# 2. 設定 .env 金鑰
echo GEMINI_API_KEY=你的APIKey > .env

# 3. 啟動 Web 介面
streamlit run app.py
```
