"""
司律高階 AI 爭點查詢與權威判解・學說速查引擎 (Legal Issue & Precedent Query Engine)
整合本機 824+ 份權威判解庫 (最高法院大法庭裁定全集、憲法法庭判決與大法官解釋、最高法院精選裁判)
與 Gemini 2.0 Flash 深度法學推論模型。
功能：
1. 精準引出相關實體法與程序法法條（條號、構成要件與法律效果）
2. 列出核心法律爭點（爭執核心與規範疑義）
3. 嚴格依權威位階列出司法裁判（憲判字/釋字 > 大法庭裁定 > 最高法院精選裁判/判例）
4. 全面深入對照通說與學者有力說（肯否兩說）
"""
import os
import sys
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from google import genai
    from google.genai import types as genai_types
    USE_MODERN_GENAI = True
except ImportError:
    import google.generativeai as legacy_genai
    USE_MODERN_GENAI = False

from config import get_gemini_api_key, DEFAULT_GEMINI_MODEL, RAW_DATA_DIR, DATA_DIR, get_gemini_models_to_try

CATALOG_PATHS = [
    Path(RAW_DATA_DIR) / "precedents_catalog.json",
    Path(__file__).resolve().parent / "data" / "raw_exams" / "precedents_catalog.json",
    Path(DATA_DIR) / "raw_exams" / "precedents_catalog.json"
]

_CACHED_CATALOG: Optional[List[Dict[str, Any]]] = None

def get_precedents_catalog() -> List[Dict[str, Any]]:
    """載入權威裁判目錄庫 (含最高法院民刑大法庭、憲法法庭與大法官解釋)"""
    global _CACHED_CATALOG
    if _CACHED_CATALOG is not None:
        return _CACHED_CATALOG

    for p in CATALOG_PATHS:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list) and len(data) > 0:
                    _CACHED_CATALOG = data
                    return _CACHED_CATALOG
            except Exception:
                pass
    return []

def generate_judicial_search_urls(query: str, subject: str = "") -> Dict[str, str]:
    """生成通往七法、法源、月旦與司法院 30 年法院判決資料庫的即時直連查詢連結（七法/法源多庫矩陣）"""
    import urllib.parse
    clean_q = re.sub(r'[\r\n\t]+', ' ', query).strip()
    tokens = [t for t in re.split(r'[\s,，、。！？]+', clean_q) if len(t) >= 2]
    search_keyword = " ".join(tokens[:3]) if tokens else clean_q[:20]
    encoded_k = urllib.parse.quote(search_keyword)

    return {
        "⚖️ 七法 Lawsnote 智慧法學語意搜尋": f"https://www.lawsnote.com/search?keyword={encoded_k}",
        "🏛️ 司法院 30 年裁判書全文檢索 (全台地院/高院/最高院)": f"https://judgment.judicial.gov.tw/FJUD/default.aspx?k={encoded_k}",
        "📚 法源法律網 LawBank 裁判與法規檢索": f"https://www.lawbank.com.tw/treatise/pl_search.aspx?keyword={encoded_k}",
        "📜 憲法法庭裁判與司法院大法官解釋系統": f"https://cons.judicial.gov.tw/jcc/zh-tw/jep01?q={encoded_k}",
        "🎓 月旦知識庫 法學論文與期刊論著索引": f"http://lawdata.com.tw/anglelaw/lawdata_search.aspx?keyword={encoded_k}",
        "🏢 智慧財產及商業法院裁判全文檢索": "https://ipc.judicial.gov.tw/tw/lp-66-071.html"
    }

def search_local_precedents(query: str, subject: str = "", top_k: int = 6) -> List[Dict[str, Any]]:
    """從 824+ 份權威判解庫中高速篩選最相關之判決/大法庭裁定（支援多維雙向語義匹配與科目保底）"""
    catalog = get_precedents_catalog()
    if not catalog:
        return []

    # 1. 拆分原始 tokens
    raw_tokens = [t.strip() for t in re.split(r'[\s,，、。！？]+', query) if len(t.strip()) >= 2]
    if not raw_tokens:
        raw_tokens = [query.strip()]

    # 2. 提取 2-gram / 3-gram 關鍵字，提升自然語言長句查詢命中率
    ngram_tokens = set(raw_tokens)
    for raw in raw_tokens:
        if len(raw) > 2:
            for n in [2, 3, 4]:
                for i in range(len(raw) - n + 1):
                    ngram_tokens.add(raw[i:i+n])
    tokens = list(ngram_tokens)

    # 3. 提取法條條號與數字
    numbers = re.findall(r'\d+', query)

    scored_items = []
    for item in catalog:
        score = 0
        case_id = item.get("case_id", "")
        title = item.get("title", "")
        sub_cat = item.get("sub_category", "")
        issue = item.get("issue", "")
        holding = item.get("holding", "")
        laws_cited = item.get("laws_cited", [])

        text_pool = f"{case_id} {title} {sub_cat} {issue} {holding} {' '.join(laws_cited)}"

        # 大法庭與憲法裁判權重加成
        level = item.get("level", "")
        if "大法庭" in level:
            score += 15
        elif "憲法" in level or "大法官" in level:
            score += 10

        # 科目匹配加成
        item_sub = item.get("subject", "")
        if subject and "全部" not in subject:
            sub_keywords = [w.strip() for w in re.split(r'[\s（）()【】/・、,，]+', subject) if len(w.strip()) >= 2]
            if any(k in item_sub or k in title for k in sub_keywords):
                score += 15

        # 雙向匹配 A：查詢 token 是否出現在判決文字池
        for tok in tokens:
            if tok in text_pool:
                score += 8
                if tok in title or tok in sub_cat:
                    score += 16
                if tok in case_id:
                    score += 25

        # 雙向匹配 B：判決的關鍵爭點/次分類名稱是否出現在使用者的查詢句子中 (逆向命中)
        if sub_cat and len(sub_cat) >= 2 and sub_cat in query:
            score += 35
        if title and len(title) >= 4 and any(title[i:i+4] in query for i in range(len(title)-3)):
            score += 25

        # 法條完全命中計分
        for law in laws_cited:
            if any(tok in law for tok in raw_tokens):
                score += 25
            if any(num in law for num in numbers if len(num) >= 2):
                score += 15

        # 判決字號數字命中（例如 1719、16）
        if any(num in case_id for num in numbers if len(num) >= 2):
            score += 30

        if score > 0:
            scored_items.append((score, item))

    scored_items.sort(key=lambda x: -x[0])

    # 智慧保底機制：若特殊冷僻爭點未直接命中，優先篩選同科目最高權威的大法庭/憲法裁判，絕不讓結果留空
    if not scored_items and subject and "全部" not in subject:
        sub_fallback = [
            it for it in catalog
            if any(k in it.get("subject", "") for k in re.split(r'[\s（）()【】/・、,，]+', subject) if len(k) >= 2)
        ]
        if sub_fallback:
            return sub_fallback[:top_k]

    return [x[1] for x in scored_items[:top_k]]

def get_precedent_by_id(case_id: str) -> Optional[Dict[str, Any]]:
    """根據案號（精確、包含或關鍵字）從裁判庫中獲取裁判卡片"""
    catalog = get_precedents_catalog()
    if not catalog or not case_id:
        return None
    clean_id = re.sub(r'[\s\-_]+', '', case_id).lower()
    
    # 1. 完全或前綴/後綴匹配
    for r in catalog:
        cid = re.sub(r'[\s\-_]+', '', r.get("case_id", "")).lower()
        if cid == clean_id:
            return r
            
    # 2. 包含匹配
    for r in catalog:
        cid = re.sub(r'[\s\-_]+', '', r.get("case_id", "")).lower()
        if clean_id in cid or cid in clean_id:
            return r
            
    # 3. 案號核心數字與中文字號比對 (例如 108台上大1719)
    nums = re.findall(r'\d+', clean_id)
    chars = re.findall(r'[\u4e00-\u9fa5]+', clean_id)
    if nums and chars:
        for r in catalog:
            cid = re.sub(r'[\s\-_]+', '', r.get("case_id", "")).lower()
            if all(n in cid for n in nums) and any(c in cid for c in chars if len(c) >= 2):
                return r
    return None

def get_all_precedent_options() -> List[str]:
    """獲取供 UI 下拉選單快速挑選之裁判格式標籤（依審級與重要性排序）"""
    catalog = get_precedents_catalog()
    options = []
    for r in catalog:
        cid = r.get("case_id", "")
        court = r.get("court", "")
        lvl = r.get("level", "")
        tit = r.get("title", "")
        if cid:
            tag = f"{cid} ｜ {court} ｜ {tit[:22]}"
            options.append(tag)
    return options


class LegalIssueQueryEngine:
    def __init__(self, model_name=DEFAULT_GEMINI_MODEL):
        self.api_key = get_gemini_api_key()
        if not self.api_key:
            raise ValueError("未檢測到 GEMINI_API_KEY！請在 Streamlit Secrets 或 .env 中設定您的 API Key。")
        self.model_name = model_name
        if USE_MODERN_GENAI:
            self.client = genai.Client(api_key=self.api_key)
        else:
            legacy_genai.configure(api_key=self.api_key)
            self.model = legacy_genai.GenerativeModel(model_name=model_name)

    def _call_model(self, prompt: str) -> str:
        models_to_try = get_gemini_models_to_try(self.model_name)
        last_err = None
        for m_name in models_to_try:
            try:
                if USE_MODERN_GENAI:
                    cfg = genai_types.GenerateContentConfig(
                        temperature=0.2
                    )
                    resp = self.client.models.generate_content(
                        model=m_name,
                        contents=prompt,
                        config=cfg
                    )
                    return resp.text
                else:
                    cur_model = legacy_genai.GenerativeModel(model_name=m_name)
                    resp = cur_model.generate_content(
                        prompt,
                        generation_config=legacy_genai.types.GenerationConfig(temperature=0.2)
                    )
                    return resp.text
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"Gemini API 查詢調用失敗: {last_err}")

    def query_legal_issue(self, query: str, subject: str = "全部科目") -> Dict[str, Any]:
        """
        執行深度法學爭點查詢
        返回包含法條構成要件、最高位階實務判決、學說肯否兩說及作答開標示範的完整字典
        """
        matched_precedents = search_local_precedents(query, subject=subject, top_k=5)

        precedent_context_str = ""
        if matched_precedents:
            precedent_context_str = "【本機權威判解庫即時檢索命中資料（供對照精確引述）】：\n"
            for idx, p in enumerate(matched_precedents, 1):
                precedent_context_str += f"""
--- 命中裁判 {idx} ---
- 裁判字號：{p.get('case_id')}
- 審級權威：{p.get('level')}
- 爭點領域：{p.get('title')} ({p.get('sub_category')})
- 核心要旨：{p.get('holding')}
- 引用法規：{', '.join(p.get('laws_cited', []))}
- 學說實務對比：{p.get('scholarly_views')}
"""

        prompt = f"""
你是一位台灣「司法官暨律師高等考試」講座名師兼前最高法院研究法官。
現在使用者提出了一項法律爭點、關鍵字或案件情境進行【AI 爭點查詢】：
查詢內容：【{query}】
指定考科：【{subject}】

{precedent_context_str}

請嚴謹、精準且完整地輸出以下五大結構化區塊（請務必依標題編排）：

### 一、📜 核心法條依據與構成要件
- 條號與法規全稱（例如：民法第184條第1項前段、保險法第64條第3項）
- 法條客觀與主觀構成要件剖析
- 法律效果說明

### 二、⚖️ 核心法律爭點所在
- 簡要提煉 1~3 個最關鍵的法律爭議核心（衝突所在與規範漏洞或解釋疑義）
- 說明爭點在國家考試與實務實務上的重要性

### 三、🏛️ 權威司法實務裁判見解（最高法院、高等法院與各審級法院代表判決）
1. **憲法法庭判決 / 大法官解釋**（若有涉基本權或違憲審查，引出案由、字號與核心主文）
2. **最高法院大法庭裁定 / 最高行政法院大法庭裁定**（引出完整年度字號，如最高法院108年度台上大字第1719號，並詳述主文與核心法理）
3. **最高法院精選裁判 / 具有參考價值裁判 / 經典判例 / 決議**（引出代表性字號與裁判要旨）
4. **高等法院 / 智慧財產及商業法院 / 高等行政法院代表性裁判**（補充具重要指標意義或事實認定典型之審級裁判與字號）

### 四、📚 學說見解深度對照（肯否兩說）
- **甲說（通說 / 實務主流見解）**：立論依據、法理基礎、代表學者（如王澤鑑、林山田、黃榮堅、陳敏、姜世明、葉啟洲教授等）
- **乙說（有力說 / 批判見解）**：立論依據、對甲說之質疑與實務適用反思
- **評析與折衷說**：法理之衡平與當前考選部命題評閱之採擇傾向

### 五、✍️ 國考二試上位卷 IRAC 作答示範（開標與涵攝指引）
- **俐落開標示範**：（例如：（一）乙移轉A屋所有權予丙，屬有權處分，丙取得所有權：）
- **大前提確立示範**：如何融合法條、大法庭裁定字號與學說見解
- **事實涵攝與結論**：如何將具體事實嚴密代入構成要件

### 六、⚠️ 裁判效力狀態與違憲警示（七法 Lawsnote 特色功能）
- 標註本爭點涉及裁判之有效性狀態，提醒考生與實務嚴格防禦：
  - 🟢 **【現行有效主流】**：最高法院現行穩健見解或大法庭裁定
  - 🟡 **【見解歧異/變更中】**：各庭間尚有爭議、大法庭提案中
  - 🔴 **【已廢止/違憲停止適用】**：經大法庭裁定廢止、停止適用或經憲法法庭宣告違憲失效（絕對禁止在國考或訴訟中援用！）

### 七、📈 爭點實務見解演進時間軸（七法歷程脈絡樹）
- 以清晰時間箭頭流程呈現本爭點之實務演進軌跡：
  `【早期傳統舊判例】➔ 【實務紛歧與學說反思】➔ 【最高法院大法庭裁定定錨】➔ 【憲法法庭最新人權審查趨勢】`

請直接以格式清晰之 Markdown 文本輸出，內容必須專業、精準、足堪作為司律榜首等級之法學寶典！
"""
        response_text = self._call_model(prompt)

        return {
            "query": query,
            "subject": subject,
            "matched_local_precedents": matched_precedents,
            "markdown_result": response_text,
            "external_search_urls": generate_judicial_search_urls(query, subject)
        }

    def summarize_judgment(
        self,
        case_id: str,
        judgment_text: str = "",
        subject: str = ""
    ) -> Dict[str, Any]:
        """
        AI 判決深度摘要：
        依使用者需求，嚴格產出以下核心區塊：
        1. 裁判基本資訊
        2. 一、主文 (Disposition)
        3. 二、案例事實 (Case Facts)
        4. 三、案件爭點 (Legal Issues)
        5. 四、雙方所述 (Parties' Contentions: 原告/上訴人主張 vs 被告/被上訴人答辯)
        6. 五、法院心證與裁判論理 (Court's Ratio Decidendi)
        7. 六、專業評析、相似實務對照與國考作答要領 (Analysis & Exam Relevance)
        """
        local_rec = get_precedent_by_id(case_id)
        local_context = ""
        if local_rec:
            local_context = f"""
【本機權威庫已收錄之本裁判核心卡片】：
- 裁判字號：{local_rec.get('case_id')}
- 法院與審級：{local_rec.get('court')} ({local_rec.get('level')})
- 爭點領域：{local_rec.get('title')} ({local_rec.get('sub_category')})
- 核心要旨：{local_rec.get('holding')}
- 引用法規：{', '.join(local_rec.get('laws_cited', []))}
- 學說評析：{local_rec.get('scholarly_views')}
- 國考作答提示：{local_rec.get('exam_application_hint')}
"""
        user_text_context = ""
        if judgment_text.strip():
            user_text_context = f"\n【使用者提供之裁判全文或事實節錄】：\n{judgment_text.strip()[:8000]}\n"

        prompt = f"""
你是一位台灣「司法院前最高法院研究法官」兼「律師司法官高等考試權威講座名師」，擅長精準解構各級法院裁判書。
現在請針對以下司法裁判進行極致嚴謹、體系分明、高度可讀的【AI 判決精華深度摘要】：

裁判案號/字號：【{case_id}】
所屬科目領域：【{subject or '司法實務綜合'}】

{local_context}
{user_text_context}

請務必嚴格遵循以下六大標題區塊輸出完整 Markdown 報告：

### 🏛️ 裁判基本資訊
- **裁判字號**：完整案號（例：最高法院108年度台上大字第1719號民事裁定、臺灣臺南地方法院106年度亡字第40號民事裁定、臺灣高等法院115年度上字第620號判決）
- **管轄法院與審級**：所屬法院（最高法院、高等法院、高等行政法院、最高行政法院、智慧財產及商業法院或地方法院）與審級權威定位
- **涉及核心法規條號**：具體法規全稱與條項（例如：民法第184條第1項前段、第767條第1項、保險法第64條等）

### 一、📜 裁判主文 (Disposition)
- 請以清晰格式列出本案之「裁判主文」（例如：原判決廢棄，發回臺灣高等法院；上訴駁回；原告之訴駁回；宣告被繼承人於某年某月某日死亡等）。

### 二、🔍 案例客觀事實 (Case Facts)
- 當事人法律關係背景與起因（原委、契約締結、借名登記、物之交付、侵權損害發生經過或行政處分作成歷程）。
- 雙方紛爭爆發之具體時空經過與關鍵客觀事實細節。

### 三、⚖️ 案件核心法律爭點 (Legal Issues)
- 簡要提煉 1~3 項繫屬於法院的核心法律爭端（例如：借名登記出名人擅自將不動產移轉第三人是否屬無權處分？死亡宣告在特定重大空難浩劫時如何計算特別災難失蹤期間？）。

### 四、🗣️ 雙方當事人所述與攻防焦點 (Parties' Contentions)
- **原告 / 上訴人主張**：其起訴/上訴之訴訟標的、請求權基礎、主要事實陳述、為何主張他方違約/違法/侵權、援引之法理與法條。
- **被告 / 被上訴人答辯**：對事實之抗辯（如否認借名關係、抗辯善意受讓取得、消滅時效抗辯、過失相抵或不可抗力抗辯）。

### 五、⚖️ 法院心證與裁判論理 (Court's Ratio Decidendi)
- **事實認定與舉證責任分配**：法院如何認定雙方爭執之事實真相、舉證責任如何歸屬。
- **認事用法與法條涵攝**：法院對關鍵法規與制度目的之權威解釋（文義、體系、歷史與客觀目的解釋）。
- **法院心證形成的判決理由**：為何法院採信某方、駁回另一方之抗辯？關鍵之心證論理轉折為何？

### 六、🎓 專業評析、相似實務對照與國考作答要領 (Analysis & Exam Relevance)
- **法理與學說評析**：本案裁判在法學體系上的重要地位（符合通說、少數說、或是突破舊實務之劃時代定錨見解）。
- **相似權威裁判對照**：對比最高法院相關大法庭裁定、判例或其他法院之相似/相異判決（分析其同中之異、異中之同）。
- **司律二試上位卷作答要領**：若國考二試出題以此事實為藍本，考生應如何精準「開標、確立大前提、事實涵攝並下結論」，達到閱卷委員給予上位卷之高分標準！

請直接以標準、專業且結構完整的繁體中文 Markdown 輸出。
"""
        result_md = self._call_model(prompt)
        return {
            "case_id": case_id,
            "subject": subject,
            "local_record": local_rec,
            "markdown_result": result_md,
            "external_search_urls": generate_judicial_search_urls(case_id, subject)
        }

    def compare_precedents(
        self,
        case_a: str,
        case_b: str,
        text_a: str = "",
        text_b: str = "",
        topic: str = ""
    ) -> Dict[str, Any]:
        """
        AI 案例橫向比對與分歧研析：
        對比兩則裁判/大法庭裁定/判例之間的事實差異、爭點、法條、主張、心證與見解分歧
        """
        rec_a = get_precedent_by_id(case_a)
        rec_b = get_precedent_by_id(case_b)

        ctx_a = f"【裁判 A 庫存資訊】：案號={case_a} | 審級={rec_a.get('level')} | 要旨={rec_a.get('holding')} | 學說={rec_a.get('scholarly_views')}" if rec_a else f"【裁判 A】：案號={case_a}"
        ctx_b = f"【裁判 B 庫存資訊】：案號={case_b} | 審級={rec_b.get('level')} | 要旨={rec_b.get('holding')} | 學說={rec_b.get('scholarly_views')}" if rec_b else f"【裁判 B】：案號={case_b}"

        if text_a.strip():
            ctx_a += f"\n裁判 A 內容/節錄：\n{text_a.strip()[:4000]}"
        if text_b.strip():
            ctx_b += f"\n裁判 B 內容/節錄：\n{text_b.strip()[:4000]}"

        prompt = f"""
你是一位台灣「司法院法官學院講座」兼「律師司法官高等考試典試委員」，擅長裁判區別技術 (Case Distinguishing) 與實務見解脈絡比較。
現在請針對以下兩則重要司法裁判進行全方位、深度橫向對比分析：

【裁判 A】：{case_a}
【裁判 B】：{case_b}
核心比對主題/領域：【{topic or '法律爭點橫向對比'}】

{ctx_a}
{ctx_b}

請以結構分明之 Markdown 產出專業比對報告，務必包含以下各大區塊：

### ⚖️ 兩大裁判核心對照綜整矩陣
請使用 Markdown 表格，精準對比以下維度：
| 比對維度 | 🏛️ 【裁判 A】({case_a}) | 🏛️ 【裁判 B】({case_b}) |
| :--- | :--- | :--- |
| **管轄法院與審級** | ... | ... |
| **裁判結果 / 主文** | ... | ... |
| **核心法律爭點** | ... | ... |
| **關鍵適用法條** | ... | ... |
| **採納之學說/理論** | ... | ... |
| **實務拘束力定位** | （如：現行大法庭定錨裁定 / 歷史判例 / 事實審獨立見解） | ... |

### 一、🔍 案例客觀事實異同剖析 (Fact Differences & Distinguishing)
- 兩案在當事人關係、行為態樣、法律事實細節（如善意/惡意、登記外觀、契約約定條款）之關鍵異同。
- 說明為何兩案看似雷同，卻可能因為特定細微事實而有不同判決走向（案例區別技術）。

### 二、🗣️ 雙方當事人主張與攻防焦點對比
- 【裁判 A】中雙方爭執要點 vs 【裁判 B】中雙方攻防要點。

### 三、⚖️ 法院心證與裁判論理核心對比
- 兩案承審法官/法庭在事實認定、法意探求、法益權衡與價值判斷上的心證差異。

### 四、📚 法律見解核心分歧（肯否兩說 / 見解變遷）
- 剖析兩案所代表的法學思潮與見解分歧：
  - 【裁判 A 代表之法理】：立論基礎、採納學者
  - 【裁判 B 代表之法理】：立論基礎、採納學者
  - 兩者是否存在「見解衝突（肯否兩說）」抑或「不同類型案件之區別對待」？

### 五、📈 司法實務發展趨勢與現行有效見解定錨
- 目前最高法院民刑事大法庭、最高行政法院或憲法法庭之終局立場為何？
- 哪一個裁判代表了目前司法實務的穩健主流通說？

### 六、✍️ 司律二試作答高分策略（事實區別與開標涵攝心法）
- 考生在二試申論題中，若題設事實出現類似情境，應如何：
  1. 俐落開標，並同時引述這兩則指標裁判之案號。
  2. 展現高級的「案例區別 (Distinguishing)」法學論述技術。
  3. 大前提確立與事實涵攝的最佳得分範本。

請以清晰、嚴謹之繁體中文 Markdown 輸出。
"""
        result_md = self._call_model(prompt)
        return {
            "case_a": case_a,
            "case_b": case_b,
            "topic": topic,
            "rec_a": rec_a,
            "rec_b": rec_b,
            "markdown_result": result_md,
            "external_search_urls": {
                f"⚖️ 七法搜尋【{case_a}】": generate_judicial_search_urls(case_a).get("⚖️ 七法 Lawsnote 智慧法學語意搜尋", ""),
                f"⚖️ 七法搜尋【{case_b}】": generate_judicial_search_urls(case_b).get("⚖️ 七法 Lawsnote 智慧法學語意搜尋", "")
            }
        }

    def unified_legal_search(self, query: str, subject: str = "全部科目") -> Dict[str, Any]:
        """
        全方位法學統一檢索樞紐：
        多維度即時查詢：
        1. 本地權威判解庫 (1,256 筆裁判/大法庭/憲判字/高院/筆記地院)
        2. 司律核心法條庫 (六法全書關聯條號)
        3. 外部七法 / 法源 / 司法院 30 年判決跨庫直連
        """
        clean_q = query.strip()
        precedents = search_local_precedents(clean_q, subject=subject, top_k=8)
        
        matched_articles = []
        try:
            from six_codes_engine import search_articles
            all_arts = search_articles(clean_q)
            matched_articles = all_arts[:6]
        except Exception:
            pass

        ext_urls = generate_judicial_search_urls(clean_q, subject)

        return {
            "query": clean_q,
            "subject": subject,
            "precedents": precedents,
            "articles": matched_articles,
            "external_urls": ext_urls
        }
