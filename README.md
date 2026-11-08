# ⚖️ 司律 AI 評分、命題、判解檢索與六法研析平台 (Taiwan Law Exam AI Platform)

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://law-exam-evaluator.streamlit.app/)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> 本平台是專為台灣司法官、律師國家考試、法研所與司法特考考生量身打造的**一站式法學實戰與研析系統**。全面整合：多模態手寫試卷批改、客製司律模擬命題、近 30 年歷屆真題庫檢索、406 萬實務判解檢索、最高法院大法庭裁定／原判例／座談會／民刑庭總會決議／憲判字研析、智慧六法與 AI 筆記煉金工坊。

---

## 📁 專案全域目錄與各資料夾職能深度解析 (Directory Architecture)

本專案根目錄為 `g:\我的雲端硬碟\LawExamData`，旗下共有 12 個核心資料夾與模組。為確保後續協同開發的 AI 與人類工程師能快速理解專案全貌，各資料夾之功能、檔案性質與互動關係如下：

```text
LawExamData/
├── 💻 code/                    # 核心程式碼庫、Streamlit 網頁應用與 Git 儲存庫 (主開發目錄)
├── 📜 national_laws/            # 全國法規與行政命令資料庫 (ChLaw.json, ChOrder.json 10,452 部法規)
├── 🏛️ constitutional_cases/     # 憲法裁判庫 (827 份憲判字與司法院大法官釋字全文 JSON)
├── 📚 raw_exams/                # 歷屆國考與法研所真題庫 (近30年試卷、行政法300題、真題目錄)
├── ⚖️ scoring_standards/        # 實務判決標準樣本庫 (1,636 份裁判書，供批改基準與實例校準)
├── 📝 SamsungNotes/             # 考生真實手寫筆記與課輔講義庫 (130+ 份 PDF，名師體系與百題爭點)
├── 📖 六法/                     # 實體法學八大門類分類檔案夾 (憲法、民法、刑法、訴訟法等)
├── 🧠 training_data/            # 模型微調 (SFT) 訓練資料集 (14 份加權平衡之法學 Instruction JSON/JSONL)
├── 📊 evaluation_reports/       # 手寫試卷評分診斷歷程報告 (Mode 1 產出之詳細診斷 JSON)
├── 🗄️ data/                     # 大規模資料庫儲存庫 (406萬判解母庫、立法理由快取、Google Drive 索引清單)
├── 🛠️ scratch/                  # 工程測試與自動化驗證腳本目錄 (編譯檢查、端到端回歸測試)
└── ⚙️ .vscode/                  # 編輯器全域開發設定檔
```

### 1. `code/` —— 核心程式碼庫與發布目錄
- **專案的核心心臟**，同時也是直連 GitHub (`https://github.com/FDfrankie/law-exam-evaluator.git`) 與 Streamlit Cloud 自動部署的 Git 儲存庫。
- 包含主介面程式 [`app.py`](file:///g:/我的雲端硬碟/LawExamData/code/app.py)（九大模式調度中心）、各後端法學引擎（六法引擎、函釋引擎、判解關聯引擎、評分引擎等）以及相依環境清單 `requirements.txt`。

### 2. `national_laws/` —— 全國法規與行政命令法典庫
- **`ChLaw.json`**：收錄立法院三讀通過、總統公布之全國中央法律條文全文。
- **`ChOrder.json`**：收錄全台行政院各部會之法規命令、施行細則、要點、規程、標準等，共計 **10,452 部法規全文**。六法穿透查詢法規命令（如訴願審議委員會審議規則）即源於此。
- **`core_exam_laws_articles.json`**：收錄司律考科高頻 61 部核心主法、**64,162 條結構化法定條文**。
- **`law_histories_catalog.json`** 與 **`law_amendments_history.json`**：整部法典之官方立法沿革時間軸、歷次修正公布令號與修法紀錄。

### 3. `constitutional_cases/` —— 憲法法庭裁判與釋字專庫
- 收錄 **827 則** 憲法法庭判決（111 年至最新憲判字）與司法院大法官解釋（釋字第 1 號至第 813 號）結構化 JSON 檔案。
- 內含：案號、審級、公布日期、主文要旨、合憲/違憲宣告、涉入基本權、審查標準（嚴格/中度/合理）以及大法官協同與不同意見書。

### 4. `raw_exams/` —— 歷屆國考與法研所真題庫
- 收錄近 30 年考選部司律一二試、司法特考（法警、書記官、檢察事務官、司法事務官）試題。
- 收錄台大、政大、北北桃頂大法研所各組試題。
- 包含 `exams_catalog.json`（真題總目錄）、`admin_law_300_mcqs.json`（行政法 300 題爭點選擇題庫）、`precedents_catalog.json`（核心判例目錄）與試卷原始 PDF。

### 5. `scoring_standards/` —— 實務判決真實樣本與評分基準庫
- 存放 **1,636 份真實法院判決與裁定書 JSON**（`jud_臺灣*.json`）。
- 用於 Mode 1（試卷評分）之事實比對、官方涵攝基準錨定，以及作為 AI 評分模型校準與判解分析的實體樣本。

### 6. `SamsungNotes/` —— 名師講義、課輔與考生手寫體系筆記
- 存放 **130+ 份高價值法學教材 PDF**。
- 包含許恒達教授刑法總則、民法百題爭點演練、刑法百題、債總債各課輔講義、物權與身分法體系筆記。
- 透過 `drive_notes_manifest.json` 與六法條文直接串接（例如點進民法第 184 條即可直接閱讀/下載對應章節的課輔講義 PDF）。

### 7. `六法/` —— 實體法學八大門類分類夾
- 依據 `憲法`、`民法`、`刑法`、`民事訴訟法`、`刑事訴訟法`、`商事法`、`智慧財產權法`、`行政法` 分門別類。
- 供離線歸納、實體檔案同步與手動條目管理。

### 8. `training_data/` —— 法學專用 LLM 微調 (SFT) 訓練資料集
- 存放 **14 份專業法律指令微調資料集**（`law_exam_*_sft.json / jsonl`）。
- 涵蓋：憲法訴訟題、百題爭點解析、上位卷標準答題範本、真實法院爭議案件蒸餾資料，供 Unsloth、Colab 或 Kaggle 進行模型二次預訓練與 SFT 微調。

### 9. `evaluation_reports/` —— 試卷評分診斷成果庫
- Mode 1 執行手寫試卷批改後自動存檔之詳細診斷報告（JSON 格式）。
- 記錄考生的得分維度（爭點辨識度、三段論法嚴謹度、法條引註精確度）、扣分原因與專屬補強建議。

### 10. `data/` —— 大規模資料庫與快取中心
- **`judicial_authority.db`** 與 **`judicial_1m_db/`**：收錄高達 **406 萬筆司法院裁判書**之全文檢索索引庫與裁判案號樹。
- **`statute_reasons_cache.json`**：全國法條官方三讀立法理由與修正對照快取，實現 0 秒載入、0 Token 消耗。
- **`drive_notes_manifest.json`**：Google Drive 700+ 份學習檔案資產之結構化映射字典。

### 11. `scratch/` —— 工程除錯與回歸測試工具箱
- 存放全專案的自動化檢查腳本，包含：
  - `verify_compile.py`：全模組語法編譯檢查工具。
  - `test_six_codes_comprehensive.py`：8 大核心功能端到端回歸測試腳本。
  - 專案案號檢索、條號對照排查工具。

### 12. `.vscode/` —— 編輯器組態
- Visual Studio Code 開發環境之全域設定 (`settings.json`)。

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
   - `data/judicial_authority.db`、`data/judicial_1m_db/`、`data/judgements/` 等含有數百萬筆真實判解索引與裁判書全文。
   - 任何資料遷移或新增欄位，必須採 `ALTER TABLE` 或增量寫入，**嚴禁執行 DROP TABLE、清空或覆寫現有 db 檔案**。
2. **保護法定全量典藏庫**：
   - `national_laws/ChOrder.json`（收錄全國 10,452 部行政命令）與 `core_exam_laws_articles.json` 為核心靜態資產，切勿覆蓋或刪除。

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
