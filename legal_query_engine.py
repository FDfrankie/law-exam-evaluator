"""
司律高階 AI 爭點查詢與權威判解・學說速查引擎 (Legal Issue & Precedent Query Engine)
整合本機 824+ 份權威判解庫 (最高法院大法庭裁定全集、憲法法庭判決與大法官解釋、最高法院精選裁判)
與 Gemini 2.0 Flash 深度法學推論模型。
功能：
1. 精準引出相關實體法與程序法法條（條號、構成要件與法律效果）
2. 列出核心法律爭點（爭執核心與規範疑義）
3. 嚴格依權威位階列出司法裁判（憲判字/釋字 > 大法庭裁定 > 最高法院精選裁判/判例）
4. 全面深入對照通說與學者有力說（肯否兩說）
5. 生成國考二試上位卷 IRAC 開標與作答涵攝指引
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

def search_local_precedents(query: str, subject: str = "", top_k: int = 6) -> List[Dict[str, Any]]:
    """從 824+ 份權威判解庫中高速篩選最相關之判決/大法庭裁定"""
    catalog = get_precedents_catalog()
    if not catalog:
        return []

    tokens = [t.strip() for t in re.split(r'[\s,，、。！？]+', query) if len(t.strip()) >= 2]
    if not tokens:
        tokens = [query.strip()]

    scored_items = []
    for item in catalog:
        score = 0
        text_pool = " ".join([
            item.get("case_id", ""),
            item.get("title", ""),
            item.get("sub_category", ""),
            item.get("issue", ""),
            item.get("holding", ""),
            " ".join(item.get("laws_cited", []))
        ])

        # 大法庭與憲法裁判權重加成
        level = item.get("level", "")
        if "大法庭" in level:
            score += 15
        elif "憲法" in level or "大法官" in level:
            score += 10

        # 科目匹配加成
        if subject and "全部" not in subject:
            item_sub = item.get("subject", "")
            sub_keywords = [w.strip() for w in re.split(r'[\s（）()【】/・、,，]+', subject) if len(w.strip()) >= 2]
            if any(k in item_sub or k in item.get("title", "") for k in sub_keywords):
                score += 12

        # 關鍵字命中計分
        for tok in tokens:
            if tok in text_pool:
                score += 10
                if tok in item.get("title", "") or tok in item.get("sub_category", ""):
                    score += 15
                if tok in item.get("case_id", ""):
                    score += 20

        # 法條完全命中計分
        for law in item.get("laws_cited", []):
            if any(tok in law for tok in tokens):
                score += 20

        if score > 0:
            scored_items.append((score, item))

    scored_items.sort(key=lambda x: -x[0])
    return [x[1] for x in scored_items[:top_k]]


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

### 三、🏛️ 權威司法實務裁判見解（最高權威位階）
【注意】：必須嚴格依照司法位階最高原則列出，嚴禁引用普通地方法院或高等法院裁判作為主要論據！
1. **憲法法庭判決 / 大法官解釋**（若有涉基本權或違憲審查，引出案由、字號與核心主文）
2. **最高法院大法庭裁定 / 最高行政法院大法庭裁定**（引出完整年度字號，如最高法院108年度台上大字第1719號，並詳述主文與核心法理）
3. **最高法院精選裁判 / 具有參考價值裁判 / 經典判例 / 決議**（引出代表性字號與裁判要旨）

### 四、📚 學說見解深度對照（肯否兩說）
- **甲說（通說 / 實務主流見解）**：立論依據、法理基礎、代表學者（如王澤鑑、林山田、黃榮堅、陳敏、姜世明、葉啟洲教授等）
- **乙說（有力說 / 批判見解）**：立論依據、對甲說之質疑與實務適用反思
- **評析與折衷說**：法理之衡平與當前考選部命題評閱之採擇傾向

### 五、✍️ 國考二試上位卷 IRAC 作答示範（開標與涵攝指引）
- **俐落開標示範**：（例如：（一）乙移轉A屋所有權予丙，屬有權處分，丙取得所有權：）
- **大前提確立示範**：如何融合法條、大法庭裁定字號與學說見解
- **事實涵攝與結論**：如何將具體事實嚴密代入構成要件

請直接以格式清晰之 Markdown 文本輸出，內容必須專業、精準、足堪作為司律榜首等級之法學寶典！
"""
        response_text = self._call_model(prompt)

        return {
            "query": query,
            "subject": subject,
            "matched_local_precedents": matched_precedents,
            "markdown_result": response_text
        }
