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

from config import DATA_DIR, get_gemini_api_key, DEFAULT_GEMINI_MODEL, get_gemini_models_to_try

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

def normalize_article_no(ano_str: str) -> str:
    """標準化條號字串，例如 '第 184 條' -> '184', '第 10-1 條' -> '10-1', '第 10 之 1 條' -> '10-1'"""
    if not ano_str:
        return ""
    clean = re.sub(r'[第條\s]', '', str(ano_str))
    clean = clean.replace('之', '-')
    return clean

def parse_article_query(keyword: str, known_laws: List[str] = None):
    """
    從關鍵字精準解析法規名稱、條號與文字關鍵字。
    支援範例：
    - '184' / '第184條' -> target_no='184', is_pure_no=True
    - '184-1' / '184之1' -> target_no='184-1', is_pure_no=True
    - '民法184' / '民法第184條' -> detected_law='民法', target_no='184', is_pure_no=True
    - '純粹經濟上損失' -> target_no=None, is_pure_no=False, text_kw='純粹經濟上損失'
    """
    kw = keyword.strip()
    detected_law = ""
    
    if known_laws:
        for l in sorted(known_laws, key=len, reverse=True):
            if kw.startswith(l):
                detected_law = l
                kw = kw[len(l):].strip()
                break
            elif l in kw:
                detected_law = l
                kw = kw.replace(l, "").strip()
                break

    m_no = re.search(r'(?:第\s*)?(\d+)(?:\s*(?:條\s*)?之\s*(\d+)|\s*-\s*(\d+))?(?:\s*條)?', kw)
    target_no = None
    is_pure_no = False
    text_kw = kw
    
    if m_no:
        main_no = m_no.group(1)
        sub_no = m_no.group(2) or m_no.group(3)
        target_no = f"{main_no}-{sub_no}" if sub_no else main_no
        
        rem = re.sub(r'(?:第\s*)?\d+(?:\s*(?:條\s*)?之\s*\d+|\s*-\s*\d+)?(?:\s*條)?', '', kw).strip()
        rem = re.sub(r'[\s,，、/]+', '', rem)
        if len(rem) == 0:
            is_pure_no = True
            text_kw = ""
        else:
            text_kw = rem
            
    return detected_law, target_no, is_pure_no, text_kw

def search_articles(keyword: str, selected_law: str = "", selected_branch: str = "") -> List[Dict[str, Any]]:
    """依據關鍵字、條號或法規精準搜尋條文（杜絕子字串誤判，如搜尋 184 不得匹配 1184）"""
    articles, meta, law_map = load_six_codes_data()
    raw_kw = keyword.strip()

    detected_law, target_no, is_pure_no, text_kw = parse_article_query(raw_kw, list(law_map.keys()))
    
    # 決定目標法典（關鍵字內偵測到的法名優先，如「民法184」優先鎖定民法）
    target_law = detected_law or selected_law
    
    # 決定搜尋母體
    pool = []
    if target_law and target_law in law_map:
        pool = law_map[target_law]
    elif selected_branch:
        laws = get_laws_in_branch(selected_branch)
        for l in laws:
            pool.extend(law_map.get(l, []))
    else:
        pool = articles

    prec_index = meta.get("precedents_article_index", {})
    scored_results = []
    
    for a in pool:
        ano = a.get("article_no", "")
        content = a.get("content", "")
        lname = a.get("law_name", "")
        norm_ano = normalize_article_no(ano)
        
        score = 0
        
        # 1. 條號精確邊界比對（184 絕不得誤配 1184、2184 等）
        if target_no:
            if norm_ano == target_no:
                # 條號完全精準一致
                score += 300
            elif "-" not in target_no and (norm_ano.startswith(f"{target_no}-") or norm_ano.startswith(f"{target_no}之")):
                # 附帶呈現該主條之枝條（如查 184 時呈現 184-1）
                score += 150
            elif is_pure_no:
                # 若為純條號查詢，非指定條號者一律排除
                continue
                
        # 2. 文字關鍵字比對
        if text_kw:
            if text_kw in content:
                score += 100
            if text_kw in lname:
                score += 80
            # 支援爭點/裁判庫聯查（例如「純粹經濟損失」直接定位第 184 條）
            clean_no = norm_ano.replace("-", "之")
            key = f"{lname}_第{clean_no}條"
            if key in prec_index:
                for p in prec_index[key]:
                    p_text = f"{p.get('title', '')} {p.get('holding', '')} {p.get('sub_category', '')}"
                    if text_kw in p_text:
                        score += 60
                        break
        elif not raw_kw:
            # 無搜尋詞時依序瀏覽法典條文
            score = 1
            
        if score > 0:
            scored_results.append((score, a))

    # 完全精準命中條號者優先置頂
    scored_results.sort(key=lambda x: -x[0])
    return [x[1] for x in scored_results[:50]]

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

### 六、🔗 法源式跨法規關聯條文網絡（Cross-Statutory Network）
- 列出與本條文最常**「共同連動援用」**之高頻實體法與程序法關聯條文（例如：請求權基礎競合、抗辯權、代位、時效或特別法條號）
- 說明各關聯條文在實例題中如何相互牽動、開標組裝
"""
        models_to_try = get_gemini_models_to_try(self.model_name)
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
