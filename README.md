# ⚖️ 司律 AI 評分、命題、判解檢索與六法研析平台 (Taiwan Law Exam AI Platform)

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://law-exam-evaluator.streamlit.app/)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> 專為台灣司法官、律師國家考試、法研所與司法特考考生量身打造的**一站式法學實戰與研析平台**。整合多模態視覺 OCR 批改、司律一二試命題、歷屆真題庫檢索、406 萬實務判解檢索、最高法院大法庭裁定/原判例/座談會/決議/憲判字研析、智慧六法與 AI 筆記煉金工坊。

---

## 🤖 【給後續接手開發的 AI 協同開發協議與更新守則】(AI Developer Protocol)

本節是專為**所有參與後續開發、維護與擴充之 AI Agent（如 Claude、Gemini、GPT、DeepSeek 等）**量身制定的協同開發協議。請任何接手本專案的 AI 在執行任何寫入、修改或代碼重構前，**務必嚴格遵循以下 6 大鐵律**：

### 🚨 鐵律一：法規條號與司法裁判字號「絕對零幻覺」原則 (Zero Hallucination Policy)
1. **裁判字號絕對真實**：最高法院判決、大法庭裁定（如 `最高法院 108年度台上大字第1636號民事大法庭裁定`）、憲判字、司法院大法官釋字、最高行政法院裁定等，案號、審級與日期**必須與司法院官方公報完全一致，嚴禁任何 AI 自行腦補或拼裝不存在之字號**。
2. **案號查詢絕不誤當法條條號**：
   - 當使用者搜尋 `最高法院 108年度台上大字第1636號 民事判例` 時，系統已建立 `is_case_citation_query()` 偵測機制。
   - **嚴禁**將民國年份（如 `108`）誤提取為條號，導致搜尋結果誤配至所有法規的「第 108 條」。
   - 若為裁判案號查詢，必須調用 `legal_query_engine.py` 或 `landmark_grand_chamber_engine.py` 進行案號關聯定位。

### 🚨 鐵律二：法條標題與顯示格式規範（徹底根絕「第第」、「條條」贅字）
1. **嚴禁字串無腦拼接**：資料庫中儲存的條號（`ano`）有時為 `"184"`，有時已是 `"第 184 條"` 或 `"第 157-1 條"`。
   - **嚴禁**直接撰寫 `f"第{ano}條"` 或 `f"第 {ano} 條"`，這會引發嚴重的 `第第 1 條條` 贅字 Bug。
2. **標準化顯示寫法**：
   ```python
   # 正確做法：先 normalize，再組裝顯示字串
   clean_ano = normalize_article_no(ano) # 例如 "184" 或 "157-1"
   ano_disp = f"第 {clean_ano} 條" if clean_ano else str(ano)
   # 標題輸出：
   st.markdown(sanitize_article_title(f"📜 【{lname} {ano_disp}】現行有效條文全文"))
   ```
3. **枝條與連字號標準**：
   - 全面統一使用阿拉伯數字與連字號（例如：`第 157-1 條`、`第 10-1 條`）。
   - `normalize_article_no()` 會自動將「之」替換為 `-`，並移除所有多餘空白。

### 🚨 鐵律三：台灣法學編排層級階度規範（條 ➔ 項 ➔ 款 ➔ 目）
1. **嚴謹區分項與款**：
   - **條（Article）**：法律之基本單元。
   - **項（Paragraph）**：條下之段落，可為具編號之項（`1   ...`）或無編號之自然段落。
   - **款（Item）**：以國字數字加頓號標示（`一、`、`二、` ... `十一、`、`十二、`）。
   - **目（Sub-item）**：以括號標示（`（一）`、`（二）`）。
2. **嚴防 Lookahead Regex 陷阱**：
   - 切割款次時，**嚴禁**使用 `(?=[一二三四五六七八九十百]+[、\s])` 盲目分割，否則遇到「十一、」時會被拆成「十」與「一、」，導致「十」被誤認成新段落並渲染出荒謬的「第 12 項」。
   - 請一律調用 [`six_codes_engine.py`](file:///g:/我的雲端硬碟/LawExamData/code/six_codes_engine.py) 中的 `render_formatted_article_html(content, title)` 進行安全渲染。

### 🚨 鐵律四：使用者核心資料庫與歷史資產「零破壞」原則 (Data Safety First)
1. **嚴禁刪除或覆寫現有 SQLite 大庫**：
   - `judicial_1m_index.db`、`judgements.db` 等含有數百萬筆真實判解索引。
   - 任何資料遷移或新增欄位，必須採 `ALTER TABLE` 或增量寫入，嚴禁執行 `DROP TABLE`、清空或覆寫現有 db 檔案。
2. **保護法定全量典藏庫**：
   - `core_exam_laws_articles.json`、`national_laws/ChOrder.json`（收錄全國 10,452 部行政法規命令）為核心靜態資產，切勿覆蓋或刪除。

### 🚨 鐵律五：Streamlit Cloud 雙軌容錯規範 (Dual-Track Import & Fallback)
1. 本專案在 **Streamlit Cloud** 上自動發布，遠端環境可能因為暫態網路波動、子模組相依性或快取問題而出現載入延遲。
2. **任何在 `app.py` 中引入的新函式**，必須在 `try:` 導入區塊與 `except Exception:` 降級防護區塊中**雙重聲明**：
   ```python
   # 正確的引入防護範例
   try:
       from six_codes_engine import my_new_feature
   except Exception:
       def my_new_feature(*args, **kwargs):
           return "安全降級防護模式"
   ```
3. 任何導出模組（如 `six_codes_engine.py`）中的公開 API，必須同步加入其內部的 `__all__ = [...]` 清單。

### 🚨 鐵律六：三步驗證提交工作流 (Pre-Commit Verification Workflow)
任何 AI 在修改程式碼後，**不可直接結束交差**，必須依序完成以下三步驟：
1. **語法編譯檢查**：
   ```bash
   python scratch/verify_compile.py
   # 或
   python -m py_compile app.py six_codes_engine.py legal_cross_reference_engine.py
   ```
   確保退出碼（exit code）為 0，零語法錯誤。
2. **整合回歸測試**：
   ```bash
   python scratch/test_six_codes_comprehensive.py
   ```
   確保 8 大核心測試項目（條號解析、憲法108條排版、大法庭裁定、布林搜尋、ChOrder 命令加載、標題消毒等）**100% 全部通過**。
3. **提交並同步至遠端**：
   ```bash
   git add <modified_files>
   git commit -m "清楚描述修改之功能或錯誤修復"
   git push origin main
   ```
   確保 Streamlit Cloud 能自動拉取最新程式碼重啟。

---

## 🌟 系統九大核心功能模組 (Platform Modes)

| 模式編號 | 模組名稱 | 核心能力與引擎支援 |
| :---: | :--- | :--- |
| **Mode 1** | **📝 手寫試卷評分與 OCR 診斷** | 支援手寫拍照/PDF/Word 上傳，多模態視覺模型 IRAC 三段論法診斷、爭點開標與深度涵攝評分。 |
| **Mode 2** | **🎯 司律客製模擬出題** | 一試選擇題（單選/複選）全真擬題；二試實例申論題（命題、客製考點、自動配分）。 |
| **Mode 3** | **📚 歷年真題庫檢索** | 收錄考選部近 30 年司律二試、司法特考歷屆真題，頂大公私立歷屆法研所考題，百題爭點演練。 |
| **Mode 4** | **⚡ AI 爭點破題與上位卷高分擬答** | 針對輸入之題目事實，自動提煉二試上位卷 IRAC 開標、大前提法條判解、小前提事實驗證與結論。 |
| **Mode 5** | **🔍 統一法學檢索樞紐** | 跨庫打通全國法規、司法院裁判書、法源法律網、七法 Lawsnote、立法院法律系統之一站式檢索。 |
| **Mode 6** | **📄 AI 長篇裁判與行政函釋要旨自動精鍊** | 支援裁判書字號或全文輸入，自動提煉歷審攻防、核心法律爭點見解與判決主文要旨。 |
| **Mode 7** | **⚖️ 裁判橫向比對研析與爭點立場分析** | 多案事實、立論根據、法律見解分歧橫向對比；通說（甲說）、有力說（乙說）、折衷說分析。 |
| **Mode 8** | **📖 智慧六法全書與條文爭點標註** | 收錄 64,162 條法定條文，條文下方無縫串接：項款目排版、立法理由與歷次修法沿革、最高法院大法庭裁定/憲判字/原判例、主管機關函釋（600+ 則）、授權法規命令細則（10,452 部）、個人筆記與講義、AI 深度釋析。 |
| **Mode 9** | **📥 個人法學筆記與考點爭點提煉** | 雲端筆記、手寫心智圖、課輔教材提煉為二試爭點模版、Anki 閃卡與考前救命大抄。 |

---

## 🏗️ 核心架構與重要代碼檔案索引

```text
code/
├── app.py                             # Streamlit Web 圖形介面入口與九大模式調度中心
├── config.py                          # 系統全域路徑、Gemini API 金鑰與模型設定
│
├── six_codes_engine.py                # 智慧六法全書核心引擎（條文查詢、立法理由、沿革、布林搜尋）
├── six_codes_updater.py               # 六法即時聯網爬取與修法自動同步引擎
├── admin_rulings_engine.py            # 主管機關行政函釋（金管會/經濟部/智財局/法務部）與法規命令全文引擎
├── landmark_grand_chamber_engine.py   # 最高法院大法庭裁定、原判例與憲判字權威主文與理由資料庫
├── legal_cross_reference_engine.py    # 406 萬實務判解跨庫關聯、OpenData 引用法條清洗為徽章
├── legal_summarizer_engine.py         # AI 裁判要旨精鍊、爭點橫向對比、布林精確搜尋語法解析器 (BooleanQueryParser)
├── legal_query_engine.py              # 統一法學檢索樞紐與案號歷程溯源引擎
├── evaluator.py                       # 司律手寫試卷評分與 IRAC 診斷核心引擎
├── exam_generator.py                  # 一試選擇題與二試實例題模擬出題引擎
├── doc_parser.py                      # 多模態文件解析器 (PDF, DOCX, 影像 OCR)
│
├── scratch/
│   ├── verify_compile.py              # 全專案 Python 代碼語法編譯檢查工具
│   ├── test_six_codes_comprehensive.py # 六法與判解系統 8 大核心功能端到端回歸測試腳本
│   └── verify_all.py                  # 整合驗證套件
│
└── data/
    ├── drive_notes_manifest.json      # 雲端硬碟 700+ 份學習資產結構化清單
    ├── national_laws/                 # 全國法規、六法條文與立法沿革庫 (含 ChOrder.json)
    └── raw_exams/                     # 歷屆試題目錄、行政法300題庫與判解索引
```

---

## ⚙️ 常用核心 API 呼叫指南 (API Quick Reference)

後續接手開發的 AI 請直接復用下列已封裝良好的高效 API，**請勿重複造輪子**：

### 1. 條號標準化與條文檢索
```python
from six_codes_engine import normalize_article_no, sanitize_article_title, search_articles, get_law_articles

# 標準化條號（"第 184-1 條" -> "184-1", "第 10 之 1 條" -> "10-1"）
clean_no = normalize_article_no("第 184-1 條")

# 獲取指定法規的所有條文全文（支援全國 10,452 部法規與命令）
articles = get_law_articles("民法")

# 智慧搜尋條文（支援純條號、關鍵字、布林邏輯如 "(侵權行為 ＋ 債務不履行) ＆ 純粹經濟"）
results = search_articles("(侵權行為 ＋ 債務不履行) ＆ 純粹經濟", selected_law="民法")
```

### 2. 條文 HTML 排版渲染
```python
from six_codes_engine import render_formatted_article_html

# 自動進行項、款、目階度縮排，並對但書、準用提供法學色彩高亮
html_card = render_formatted_article_html(
    content=article_content,
    title="📜 【民法 第 184 條】現行有效條文全文"
)
st.markdown(html_card, unsafe_allow_html=True)
```

### 3. 大法庭裁定與原判例主文調閱
```python
from landmark_grand_chamber_engine import get_grand_chamber_holding, get_grand_chamber_full_text

# 獲取最高法院大法庭官方權威裁判主文
holding = get_grand_chamber_holding("最高法院 108年度台上大字第1636號 民事大法庭裁定")
```

### 4. 引用法條 OpenData 碎片清洗為徽章標籤
```python
from legal_cross_reference_engine import format_statute_citations_display

# 將 OpenData 字串陣列轉換為工整的法規徽章清單
raw_citations = ['山坡地保育利用條例', '第', '37', '條', '民法', '第', '71、113、179、184 條']
chips = format_statute_citations_display(raw_citations)
# 結果：['📖 山坡地保育利用條例 第 37 條', '📖 民法 第 71、113、179、184 條']
```

### 5. 官方資料庫外鏈產生器
```python
from six_codes_engine import (
    get_moj_article_url,           # 全國法規資料庫官方條文直通網址 (LawSingle.aspx?pcode=...&flno=...)
    get_ly_article_url,            # 立法院法律系統審查與公報直通網址
    get_judicial_article_url,      # 司法院判解檢索
    get_constitutional_article_url # 憲法法庭裁判查詢
)
url_moj = get_moj_article_url("民法", "184")
url_ly = get_ly_article_url("民法", "184")
```

---

## 🎨 UI/UX 設計與體驗對齊準則

請所有開發者對齊**法源法律網、七法（Lawsnote）、法律人（Lawman）、月旦法學**之現代化法學科技 UI 標準：
1. **簡潔有力，預設收合**：立法理由、全法沿革與歷次修正公報動輒數千字，**預設必須收合於 `st.expander` 或獨立頁籤（Tab）內**，切勿在進入條文時一次攤開佔滿整個螢幕。
2. **漸進式渲染，防瀏覽器卡死**：全法瀏覽預設載入前 5–15 條，下方提供「⏬ 載入後續條文」按鈕，避免一次繪製數百個組件造成前端記憶體耗盡。
3. **外部官方入口整合**：在條文工具列提供一鍵直連按鈕（全國法規、立院公報、司法院裁判、憲法法庭、法源法律網），方便考生即時查核官方法律公報。

---

## 🚀 本地開發環境快速啟動 (Quick Start)

### 1. 安裝環境相依
```bash
cd code
pip install -r requirements.txt
```

### 2. 環境變數設定
在 `code/.env` 中填入 Google Gemini API Key：
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. 本地啟動 Streamlit
```bash
streamlit run app.py
```
或在 Windows 系統中直接雙擊執行 `run_app.bat`。

---

## 🗺️ 後續開發優先待辦事項 (Roadmap for Next AI Agents)

1. **實務判解庫持續擴充**：
   - 繼續匯入高等法院法律座談會決議、最高法院民刑庭總會決議、司法院大法官早期釋字（釋字 1–813 號）及最高行政法院重大裁判。
2. **裁判前審與後審鏈條強化**：
   - 在裁判卡片中擴充「審級歷程（Appeal Chain）」，自動串接一審地方法院判決 ➔ 二審高等法院判決 ➔ 三審最高法院判決 ➔ 發回更審裁判。
3. **AI 裁判摘要即時緩存**：
   - 針對高頻搜尋之判解，預先生成 IRAC 摘要並快取至本地 SQLite，實現 0 秒載入。

---
*本文件由 Antigravity 團隊維護，旨在為所有共同參與開發的 AI 與人類工程師提供清晰、一致、可驗證的架構規範與更新守則。*
