"""
智慧六法全書與條文爭點判解註記引擎 (Annotated Six Codes & Judicial Interpretations Engine)
收錄全台 61 部核心司律考科法規、10,183 條法定條文，全面打通：
1. 條文項款目結構與法條全文
2. 立法修法理由與歷次修正沿革
3. 權威司法裁判（憲判字/釋字、最高法院大法庭裁定、精選裁判）
4. 核心法律爭點與學說見解（通說 vs. 有力說）
5. 相關法規命令、行政函釋與施行細則
6. 考生個人手寫筆記與考科講義檔案連結
7. Gemini 2.0 Flash 即時深度條文解析與主管機關函釋剖析
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

from config import DATA_DIR, get_gemini_api_key, DEFAULT_GEMINI_MODEL

# 八大法學門類體系分類
SIX_CODES_TAXONOMY: Dict[str, List[str]] = {
    "🏛️ 憲法與憲政法規": [
        "中華民國憲法", "中華民國憲法增修條文", "憲法訴訟法"
    ],
    "📜 民事實體法典": [
        "民法", "消費者保護法", "信託法", "涉外民事法律適用法", 
        "民法總則施行法", "民法債編施行法", "民法物權編施行法", "民法親屬編施行法", "民法繼承編施行法"
    ],
    "⚖️ 民事程序法典": [
        "民事訴訟法", "民事訴訟法施行法", "家事事件法", "強制執行法", "非訟事件法", "勞動事件法"
    ],
    "⚔️ 刑事實體法典": [
        "中華民國刑法", "中華民國刑法施行法", "貪污治罪條例", "毒品危害防制條例", "洗錢防制法"
    ],
    "🛡️ 刑事程序法典": [
        "刑事訴訟法", "刑事訴訟法施行法", "國民法官法", "少年事件處理法", "通訊保障及監察法"
    ],
    "🏢 公法與行政法典": [
        "行政程序法", "行政訴訟法", "訴願法", "國家賠償法", "行政罰法", "行政執行法", "公務員懲戒法", "公務人員保障法"
    ],
    "💼 商事與財經法典": [
        "公司法", "保險法", "證券交易法", "票據法", "金融消費者保護法", "銀行法"
    ],
    "💡 智慧財產與勞動法典": [
        "專利法", "商標法", "著作權法", "營業秘密法", "勞動基準法", "工會法"
    ]
}

DATA_PATHS_ARTICLES = [
    Path(DATA_DIR) / "national_laws" / "core_exam_laws_articles.json",
    Path(__file__).resolve().parent / "data" / "national_laws" / "core_exam_laws_articles.json"
]

DATA_PATHS_META = [
    Path(DATA_DIR) / "national_laws" / "six_codes_annotated_metadata.json",
    Path(__file__).resolve().parent / "data" / "national_laws" / "six_codes_annotated_metadata.json"
]

_CACHED_ARTICLES: Optional[List[Dict[str, Any]]] = None
_CACHED_META: Optional[Dict[str, Any]] = None
_CACHED_LAW_MAP: Optional[Dict[str, List[Dict[str, Any]]]] = None

def load_six_codes_data() -> tuple:
    """載入六法條文與標註關聯目錄"""
    global _CACHED_ARTICLES, _CACHED_META, _CACHED_LAW_MAP
    if _CACHED_ARTICLES is not None and _CACHED_META is not None:
        return _CACHED_ARTICLES, _CACHED_META, _CACHED_LAW_MAP

    articles = []
    for p in DATA_PATHS_ARTICLES:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    articles = json.load(f)
                if articles:
                    break
            except Exception:
                pass

    meta = {}
    for p in DATA_PATHS_META:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta:
                    break
            except Exception:
                pass

    law_map = {}
    for a in articles:
        lname = a.get("law_name", "")
        if lname not in law_map:
            law_map[lname] = []
        law_map[lname].append(a)

    _CACHED_ARTICLES = articles
    _CACHED_META = meta
    _CACHED_LAW_MAP = law_map
    return _CACHED_ARTICLES, _CACHED_META, _CACHED_LAW_MAP

def get_laws_in_branch(branch_name: str) -> List[str]:
    """獲取指定法學門類下的所有法規名稱"""
    articles, meta, law_map = load_six_codes_data()
    expected_laws = SIX_CODES_TAXONOMY.get(branch_name, [])
    # 僅返回實際收錄有條文者
    available = [l for l in expected_laws if l in law_map]
    if not available:
        # 若分類無直接對應，返回該門類關鍵字包含者
        for l in law_map.keys():
            if any(k in l for k in branch_name.replace("🏛️", "").replace("📜", "").replace("⚖️", "").replace("⚔️", "").replace("🛡️", "").replace("🏢", "").replace("💼", "").replace("💡", "").split("與")[0].split("及")[0]):
                if l not in available:
                    available.append(l)
    return available or list(law_map.keys())[:10]

def search_articles(keyword: str, selected_law: str = "", selected_branch: str = "") -> List[Dict[str, Any]]:
    """依據關鍵字、條號或法規搜尋條文"""
    articles, meta, law_map = load_six_codes_data()
    kw = keyword.strip()

    # 提取條號數字
    m_no = re.search(r'(?:第\s*)?(\d+(?:之\d+)?)(?:\s*條)?', kw)
    target_no = m_no.group(1) if m_no else None

    results = []
    
    # 決定搜尋範圍
    pool = []
    if selected_law and selected_law in law_map:
        pool = law_map[selected_law]
    elif selected_branch:
        laws = get_laws_in_branch(selected_branch)
        for l in laws:
            pool.extend(law_map.get(l, []))
    else:
        pool = articles

    for a in pool:
        ano = a.get("article_no", "")
        content = a.get("content", "")
        lname = a.get("law_name", "")

        matched = False
        # 1. 條號精確匹配
        if target_no and (f"第 {target_no} 條" in ano or f"第{target_no}條" in ano or ano == f"第 {target_no} 條"):
            matched = True
        # 2. 關鍵字模糊匹配
        elif kw and (kw in content or kw in ano or kw in lname):
            matched = True
        elif not kw:
            matched = True

        if matched:
            results.append(a)
            if len(results) >= 50:
                break

    return results

def get_article_annotations(law_name: str, article_no: str) -> Dict[str, Any]:
    """獲取特定條文的跨庫綜合註記（實務裁判、相關命令、個人筆記）"""
    articles, meta, law_map = load_six_codes_data()
    
    # 標準化條號鍵
    clean_no = article_no.replace(" ", "").replace("第", "").replace("條", "")
    key = f"{law_name}_第{clean_no}條"
    
    prec_index = meta.get("precedents_article_index", {})
    matched_precedents = prec_index.get(key, [])
    
    # 相關命令與細則
    reg_map = meta.get("regulations_map", {})
    matched_orders = reg_map.get(law_name, [])
    
    # 個人讀書筆記
    notes_cat = meta.get("notes_catalog", {})
    matched_notes = notes_cat.get(law_name, [])

    return {
        "law_name": law_name,
        "article_no": article_no,
        "precedents": matched_precedents,
        "orders": matched_orders,
        "notes": matched_notes
    }

class SixCodesDeepAnnotator:
    """呼叫 Gemini 2.0 Flash 針對特定法條進行深度立法理由、函釋與爭點實戰釋析"""
    def __init__(self, model_name=DEFAULT_GEMINI_MODEL):
        self.api_key = get_gemini_api_key()
        if not self.api_key:
            raise ValueError("未檢測到 GEMINI_API_KEY！")
        self.model_name = model_name
        if USE_MODERN_GENAI:
            self.client = genai.Client(api_key=self.api_key)
        else:
            legacy_genai.configure(api_key=self.api_key)
            self.model = legacy_genai.GenerativeModel(model_name=model_name)

    def annotate_article(self, law_name: str, article_no: str, content: str) -> str:
        prompt = f"""
你是一位司律典試委員兼立法院法制局法學專家。
請針對【{law_name}】{article_no}進行「智慧六法全書・條文深度註釋」：

【條文全文】：
{content}

請嚴謹、精確輸出以下五大專業法學註解板塊（請排版為工整 Markdown）：

### 一、📜 立法意旨、修法理由與規範沿革
- 立法院原始立法之立法目的與保護法益
- 歷次重大修法之時代背景、修正要點與新舊法比較（若無重大修正則分析現行規範結構）

### 二、🏛️ 權威司法實務裁判與核心主文
- 憲法法庭判決 / 大法官解釋（涉基本權或審查密度）
- 最高法院大法庭裁定 / 具有參考價值裁判 / 經典判例
- 列出權威字號、裁判要旨與適用原則

### 三、📚 國考二試必考爭點與學說對照（肯否二說）
- 核心法律爭點（規範漏洞、要件解釋疑義或請求權競合）
- 【甲說（通說/實務主流）】：立論論據與代表學者
- 【乙說（有力說/批評見解）】：立論論據與批判點

### 四、📋 主管機關重要行政函釋與法規命令
- 法務部、金管會或中央主管機關之代表性解釋函釋要旨
- 相關法規命令、施行細則之關鍵關聯規定

### 五、✍️ 國考申論作答開標與涵攝示範 (IRAC)
- 示範一段漂亮俐落之二試答題開標與三段論法涵攝
"""
        models_to_try = [self.model_name]
        for m in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-3.1-pro-preview", "gemini-2.0-flash-lite", "gemini-2.5-flash"]:
            if m not in models_to_try:
                models_to_try.append(m)
        last_err = None
        for m_name in models_to_try:
            try:
                if USE_MODERN_GENAI:
                    cfg = genai_types.GenerateContentConfig(temperature=0.2)
                    resp = self.client.models.generate_content(
                        model=m_name, contents=prompt, config=cfg
                    )
                    return resp.text
                else:
                    cur_model = legacy_genai.GenerativeModel(model_name=m_name)
                    resp = cur_model.generate_content(
                        prompt, generation_config=legacy_genai.types.GenerationConfig(temperature=0.2)
                    )
                    return resp.text
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"條文深度註釋生成失敗: {last_err}")
