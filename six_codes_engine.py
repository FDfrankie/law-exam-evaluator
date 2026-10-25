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
    try:
        import google.generativeai as legacy_genai
    except ImportError:
        legacy_genai = None
    USE_MODERN_GENAI = False

__all__ = [
    "SIX_CODES_TAXONOMY",
    "get_laws_in_branch",
    "search_articles",
    "get_article_annotations",
    "SixCodesDeepAnnotator",
    "get_law_legislative_history",
    "get_article_legislative_details",
    "synthesize_article_legislative_details",
    "clear_six_codes_cache",
    "load_six_codes_data",
    "format_legal_article_text",
    "render_formatted_article_quote",
    "get_law_articles",
    "normalize_article_no",
    "parse_article_query"
]

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

DATA_PATHS_HISTORIES = [
    Path(DATA_DIR) / "national_laws" / "law_histories_catalog.json",
    Path(__file__).resolve().parent / "data" / "national_laws" / "law_histories_catalog.json"
]

DATA_PATHS_LEGISLATIVE = [
    Path(DATA_DIR) / "national_laws" / "article_legislative_catalog.json",
    Path(__file__).resolve().parent / "data" / "national_laws" / "article_legislative_catalog.json"
]

DATA_PATHS_REASONS_CACHE = [
    Path(DATA_DIR) / "statute_reasons_cache.json",
    Path(__file__).resolve().parent / "data" / "statute_reasons_cache.json",
    Path(DATA_DIR) / "national_laws" / "statute_reasons_cache.json"
]

_CACHED_ARTICLES: Optional[List[Dict[str, Any]]] = None
_CACHED_META: Optional[Dict[str, Any]] = None
_CACHED_LAW_MAP: Optional[Dict[str, List[Dict[str, Any]]]] = None
_CACHED_HISTORIES: Optional[Dict[str, Any]] = None
_CACHED_LEGISLATIVE: Optional[Dict[str, Any]] = None
_CACHED_STATUTE_REASONS: Optional[Dict[str, Any]] = None

def load_statute_reasons_cache() -> Dict[str, Any]:
    """載入比照法源法律網標準之歷次官方立法理由與歷史新舊條文持久快取庫"""
    global _CACHED_STATUTE_REASONS
    if _CACHED_STATUTE_REASONS is not None:
        return _CACHED_STATUTE_REASONS
    catalog = {}
    for p in DATA_PATHS_REASONS_CACHE:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    catalog = json.load(f)
                if catalog:
                    break
            except Exception:
                pass
    _CACHED_STATUTE_REASONS = catalog
    return _CACHED_STATUTE_REASONS

def load_law_histories() -> Dict[str, Any]:
    """載入全國 11,803 部法律與法規命令之完整立法沿革與修正紀錄"""
    global _CACHED_HISTORIES
    if _CACHED_HISTORIES is not None:
        return _CACHED_HISTORIES
    catalog = {}
    for p in DATA_PATHS_HISTORIES:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    catalog = json.load(f)
                if catalog:
                    break
            except Exception:
                pass
    _CACHED_HISTORIES = catalog
    return _CACHED_HISTORIES

def load_article_legislative_catalog() -> Dict[str, Any]:
    """載入司律核心爭點條文之官方立法理由與歷史舊條文對照庫"""
    global _CACHED_LEGISLATIVE
    if _CACHED_LEGISLATIVE is not None:
        return _CACHED_LEGISLATIVE
    catalog = {}
    for p in DATA_PATHS_LEGISLATIVE:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    catalog = json.load(f)
                if catalog:
                    break
            except Exception:
                pass
    _CACHED_LEGISLATIVE = catalog
    return _CACHED_LEGISLATIVE

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

def clear_six_codes_cache():
    """清除六法條文與標註快取，強制重新載入最新資料庫"""
    global _CACHED_ARTICLES, _CACHED_META, _CACHED_LAW_MAP, _CACHED_HISTORIES, _CACHED_LEGISLATIVE
    _CACHED_ARTICLES = None
    _CACHED_META = None
    _CACHED_LAW_MAP = None
    _CACHED_HISTORIES = None
    _CACHED_LEGISLATIVE = None

def get_laws_in_branch(branch_name: str) -> List[str]:
    """獲取指定法學門類下的所有法規名稱（核心主法優先，法規命令隨後，涵蓋全部典藏庫）"""
    articles, meta, law_map = load_six_codes_data()
    expected_laws = list(SIX_CODES_TAXONOMY.get(branch_name, []))
    available = [l for l in expected_laws if l in law_map]
    
    # 1. 結合 metadata 中的全量分類
    meta_tax = meta.get("taxonomy", {})
    matched_meta_laws = []
    for br_k, br_list in meta_tax.items():
        if any(c in br_k for c in ["商事", "公司", "金融"]) and any(c in branch_name for c in ["商事", "財經"]):
            matched_meta_laws.extend(br_list)
        elif any(c in br_k for c in ["智慧財產", "勞動"]) and any(c in branch_name for c in ["智慧財產", "勞動"]):
            matched_meta_laws.extend(br_list)
        elif br_k == branch_name:
            matched_meta_laws.extend(br_list)

    for l in matched_meta_laws:
        if l in law_map and l not in available:
            available.append(l)

    # 2. 結合使用者 300+ 部法規典藏庫 (user_uploaded_laws_catalog)
    user_laws = meta.get("user_uploaded_laws_catalog", {})
    branch_clean = branch_name.replace("🏛️", "").replace("📜", "").replace("⚖️", "").replace("⚔️", "").replace("🛡️", "").replace("🏢", "").replace("💼", "").replace("💡", "").strip()
    branch_keywords = []
    if "憲法" in branch_clean or "公法" in branch_clean:
        branch_keywords = ["憲法", "公法"]
    elif "民事實體" in branch_clean or "民法" in branch_clean:
        branch_keywords = ["民法", "民事"]
    elif "民事程序" in branch_clean or "訴訟" in branch_clean:
        branch_keywords = ["民事程序", "民事訴訟", "非訟"]
    elif "刑事實體" in branch_clean or "刑法" in branch_clean:
        branch_keywords = ["刑事實體", "刑法"]
    elif "刑事程序" in branch_clean:
        branch_keywords = ["刑事程序", "刑事訴訟", "偵審"]
    elif "行政" in branch_clean:
        branch_keywords = ["行政法", "行政", "公法"]
    elif "商事" in branch_clean or "財經" in branch_clean:
        branch_keywords = ["商事", "公司", "證交", "保險", "票據", "銀行", "金融"]
    elif "智慧財產" in branch_clean or "勞動" in branch_clean:
        branch_keywords = ["智財", "智慧財產", "專利", "商標", "著作", "勞動", "社會法"]

    for u_law_name, u_info in user_laws.items():
        u_branch = u_info.get("branch", "")
        if any(kw in u_branch for kw in branch_keywords):
            if u_law_name in law_map and u_law_name not in available:
                available.append(u_law_name)

    # 3. 掃描 law_map 中的所有條文，若其 branch 屬性符合本門類
    for l_name, l_arts in law_map.items():
        if l_name not in available and l_arts:
            art_br = l_arts[0].get("branch", "")
            if any(kw in art_br for kw in branch_keywords):
                available.append(l_name)

    # 4. 補充 regulations_map
    reg_map = meta.get("regulations_map", {})
    for parent_l, ords in reg_map.items():
        if parent_l in available:
            for ord_item in ords:
                ord_name = ord_item.get("name")
                if ord_name and ord_name not in available:
                    available.append(ord_name)

    if not available:
        for l in law_map.keys():
            if any(k in l for k in branch_clean.split("與")[0].split("及")[0]):
                if l not in available:
                    available.append(l)

    return available or list(law_map.keys())[:10]

def get_law_articles(law_name: str) -> List[Dict[str, Any]]:
    """獲取指定法典或法規命令的全部法定條文全文"""
    articles, meta, law_map = load_six_codes_data()
    if law_name in law_map:
        return law_map[law_name]
    reg_map = meta.get("regulations_map", {})
    for parent_l, ords in reg_map.items():
        for ord_item in ords:
            if ord_item.get("name") == law_name and ord_item.get("articles"):
                return [
                    {
                        "law_name": law_name,
                        "article_no": a.get("article_no", ""),
                        "content": a.get("content", ""),
                        "category": ord_item.get("category", "")
                    }
                    for a in ord_item.get("articles", [])
                ]
    return []

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

    # 支援專業布林邏輯精確篩選 (Boolean Query)
    is_bool_query = False
    try:
        from legal_summarizer_engine import BooleanQueryParser, evaluate_boolean_query
        if BooleanQueryParser.is_boolean_query(raw_kw):
            is_bool_query = True
    except Exception:
        is_bool_query = False

    if is_bool_query:
        scored_results = []
        for a in pool:
            ano = a.get("article_no", "")
            content = a.get("content", "")
            lname = a.get("law_name", "")
            chap = a.get("chapter", "")
            full_text = f"{lname} 第{ano}條 {chap} {content}"
            if evaluate_boolean_query(raw_kw, full_text):
                score = 100
                if selected_law and lname == selected_law:
                    score += 50
                scored_results.append((score, a))
        scored_results.sort(key=lambda x: -x[0])
        return [item[1] for item in scored_results]

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
                    p_text = f"{p.get('title', '')} {p.get('holding', '')} {p.get('scholarly_views', '')} {p.get('exam_application_hint', '')} {p.get('case_id', '')}"
                    if text_kw in p_text:
                        score += 60
                        break
        elif not text_kw and not target_no:
            # 無額外文字搜尋詞或純輸入法規名稱時，依序呈現該法規全部條文
            score = 1
            
        if score > 0:
            scored_results.append((score, a))

    # 完全精準命中條號者優先置頂
    scored_results.sort(key=lambda x: -x[0])
    return [x[1] for x in scored_results[:50]]

def classify_document_nature(filename: str, path: str = "") -> Dict[str, Any]:
    """
    精準識別法學文檔之性質，嚴格區隔：
    - 'question': 實戰試題 / 百題爭點演練 / 考古題 / 模擬考題
    - 'handout': 課輔講義 / 授課教材 / 專題課程講義
    - 'note': 個人讀書筆記 / 體系總筆記 / 手寫心智圖
    """
    s = (filename + " " + path).lower()
    is_question = False
    q_tag = "【實戰試題】"

    if "百題" in s:
        is_question = True
        if any(k in s for k in ["刑", "刑總", "刑分", "刑法"]):
            q_tag = "【刑法百題爭點演練】"
        elif any(k in s for k in ["民", "民總", "債", "物權", "身分", "民法"]):
            q_tag = "【民法百題爭點演練】"
        else:
            q_tag = "【百題爭點演練】"
    elif "考古題" in s or "考古" in s:
        is_question = True
        q_tag = "【歷屆考古題】"
    elif any(k in s for k in ["模擬試題", "模擬考", "總複習模擬"]):
        is_question = True
        q_tag = "【模擬試題演練】"
    elif any(k in s for k in ["試題演練", "實例題演練", "課輔演練", "期末課輔題目", "課輔題目"]):
        is_question = True
        q_tag = "【課輔實例演練題】"
    elif any(k in s for k in ["期末考_試題", "期中考_試題", "期末考試", "期中考試", "試題說明"]):
        is_question = True
        q_tag = "【期中/期末考題】"
    elif any(k in s for k in ["試題", "考題", "題目", "題庫", "真題", "測驗"]):
        is_question = True
        q_tag = "【實戰試題】"

    if is_question:
        return {
            "doc_nature": "question",
            "nature_name": "🎯 實例試題與百題演練",
            "badge_icon": "🎯",
            "tag": q_tag,
            "is_question": True,
            "is_handout": False,
            "is_note": False
        }

    is_handout = False
    h_tag = "【課輔講義】"
    if any(k in s for k in ["講義", "課輔", "教材", "課程", "投影片", "ppt", "釋義與適用"]):
        is_handout = True
        if "課輔" in s:
            h_tag = "【課輔講義】"
        elif "課程" in s or "專題" in s:
            h_tag = "【專題課程教材】"
        else:
            h_tag = "【法學講義】"

    if is_handout:
        return {
            "doc_nature": "handout",
            "nature_name": "📘 課輔與授課講義",
            "badge_icon": "📘",
            "tag": h_tag,
            "is_question": False,
            "is_handout": True,
            "is_note": False
        }

    return {
        "doc_nature": "note",
        "nature_name": "📝 個人讀書筆記",
        "badge_icon": "📝",
        "tag": "【體系總筆記】" if "體系" in s else "【個人讀書筆記】",
        "is_question": False,
        "is_handout": False,
        "is_note": True
    }


def get_unified_materials_catalog(meta_notes_cat: dict = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    動態整合六法標註目錄與 Google Drive 最新 580+ 份講義、筆記與試題大庫
    並將檔案依考科分流建立索引
    """
    unified = {}
    if meta_notes_cat:
        for k, v in meta_notes_cat.items():
            unified[k] = list(v)

    # 嘗試讀取 drive_notes_manifest.json
    manifest_paths = [
        Path(DATA_DIR) / "drive_notes_manifest.json",
        Path(__file__).resolve().parent / "data" / "drive_notes_manifest.json",
        Path(DATA_DIR).parent / "drive_notes_manifest.json"
    ]
    manifest_items = []
    for mp in manifest_paths:
        if mp.exists():
            try:
                with open(mp, "r", encoding="utf-8") as f:
                    manifest_items = json.load(f)
                if manifest_items:
                    break
            except Exception:
                pass

    if manifest_items:
        # 分類群組映射
        SUB_TO_LAWS = {
            "民總": ["民法"], "債總": ["民法"], "債各": ["民法"], "物權": ["民法"], "身分法": ["民法"], "民法": ["民法"], "民法考古題": ["民法"],
            "刑總": ["刑法", "中華民國刑法"], "刑分": ["刑法", "中華民國刑法"], "刑法各論": ["刑法", "中華民國刑法"], "刑法考古題": ["刑法", "中華民國刑法"],
            "憲法": ["憲法", "中華民國憲法"], "行政法": ["行政法"],
            "商事法": ["公司法", "保險法", "證券交易法"], "公司法": ["公司法"], "保險法": ["保險法"], "證交法": ["證券交易法"], "證券交易法": ["證券交易法"],
            "民訴": ["民事訴訟法"], "民事訴訟法": ["民事訴訟法"],
            "智慧財產權法": ["專利法", "商標法", "著作權法"], "專利法": ["專利法"], "商標法": ["商標法"], "著作權法": ["著作權法"]
        }

        for item in manifest_items:
            sub = item.get("subject", "")
            target_laws = SUB_TO_LAWS.get(sub, [sub])
            fn = item.get("filename", "")
            
            for t_law in target_laws:
                if t_law not in unified:
                    unified[t_law] = []
                # 查重 (避免同檔名重複加入)
                if not any(x.get("filename") == fn for x in unified[t_law]):
                    unified[t_law].append({
                        "filename": fn,
                        "subject": sub,
                        "author": item.get("author", ""),
                        "path": item.get("path", ""),
                        "size_kb": round(float(item.get("size_mb", 0.0)) * 1024, 1)
                    })

    return unified


def get_precise_relevant_notes(law_name: str, article_no: str, content: str = "", notes_cat: dict = None) -> List[Dict[str, Any]]:
    """
    依據法典編章結構、條號區間與實體法考點關鍵字，精準過濾關聯之個人讀書筆記、實戰試題與課輔講義。
    嚴格防範「全科全部灌入」或「把題目誤認為筆記」之問題。
    """
    if not notes_cat:
        return []
    
    # 統整對應考科文檔清單
    candidate_notes = []
    if "刑法" in law_name:
        candidate_notes = notes_cat.get("刑法", []) or notes_cat.get("中華民國刑法", [])
    elif "民法" in law_name:
        candidate_notes = notes_cat.get("民法", [])
    elif "憲法" in law_name:
        candidate_notes = notes_cat.get("憲法", []) or notes_cat.get("中華民國憲法", [])
    elif "公司法" in law_name:
        candidate_notes = notes_cat.get("公司法", [])
    elif "保險法" in law_name:
        candidate_notes = notes_cat.get("保險法", [])
    elif "證券交易法" in law_name or "證交法" in law_name:
        candidate_notes = notes_cat.get("證券交易法", [])
    elif "民事訴訟法" in law_name or "民訴" in law_name:
        candidate_notes = notes_cat.get("民事訴訟法", [])
    else:
        candidate_notes = notes_cat.get(law_name, [])

    if not candidate_notes:
        return []

    # 提取條號數值
    m = re.search(r'\d+', str(article_no))
    art_num = int(m.group(0)) if m else None

    scored = []
    for n in candidate_notes:
        fn = n.get("filename", "")
        score = 0
        match_reason = ""

        # ------------------ 民法過濾規則 ------------------
        if "民法" in law_name and art_num is not None:
            # 1. 民總 (1~152 條)
            if 1 <= art_num <= 152:
                if "身分法_" in fn or "債各_" in fn or "債編" in fn:
                    continue  # 嚴格排除身分法與債各筆記
                if "民總_" in fn or "民法總則" in fn or "百題" in fn:
                    score += 50

                    # 民法百題爭點系列實例演練精準條文映射
                    if "百題" in fn:
                        score += 30
                        if 1 <= art_num <= 24 and any(b in fn for b in ["（一）", "(一)", "（1）", "(1)"]):
                            score += 180
                            match_reason = "民法百題爭點演練：自然人權利能力與死亡宣告"
                        elif 25 <= art_num <= 58 and any(b in fn for b in ["（四）", "(四)", "（4）", "(4)"]):
                            score += 180
                            match_reason = "民法百題爭點演練：法人侵權責任與董事代表權"
                        elif 66 <= art_num <= 70 and any(b in fn for b in ["（七）", "(七)", "（7）", "(7)"]):
                            score += 180
                            match_reason = "民法百題爭點演練：權利客體（物）與主物從物"
                        elif 71 <= art_num <= 85 and any(b in fn for b in ["（十一）", "(十一)", "（11）", "(11)"]):
                            score += 180
                            match_reason = "民法百題爭點演練：法律行為標的妥當性與暴利行為"
                        elif 86 <= art_num <= 98 and any(b in fn for b in ["（十二）", "(十二)", "（12）", "(12)"]):
                            score += 180
                            match_reason = "民法百題爭點演練：意思表示瑕疵（通謀虛偽/錯誤/詐欺）"
                        elif 103 <= art_num <= 118 and any(b in fn for b in ["（十五）", "(十五)", "（15）", "(15)"]):
                            score += 180
                            match_reason = "民法百題爭點演練：代理、無權代理與無權處分"

                    # 課輔實例試題演練
                    if "試題演練" in fn or "期末試題演練" in fn:
                        score += 120
                        match_reason = "民法總則：實務期末與課輔試題演練"

                    if 1 <= art_num <= 24 and ("自然人" in fn or "權利主體" in fn):
                        score += 150
                        match_reason = "民法總則：權利主體（自然人）專題"
                    elif 66 <= art_num <= 70 and ("物" in fn or "權利客體" in fn):
                        score += 150
                        match_reason = "民法總則：權利客體（物）專題"
                    elif 71 <= art_num <= 118 and "法律行為" in fn:
                        score += 120
                        match_reason = "民法總則：法律行為專題"
                        if 86 <= art_num <= 98 and "意思表示" in fn:
                            score += 80
                            match_reason = "民法總則：意思表示專題"
                        elif (12 <= art_num <= 15 or 99 <= art_num <= 102) and ("行為能力" in fn or "條件" in fn):
                            score += 80
                            match_reason = "民法總則：行為能力與條件期限"
                    elif 103 <= art_num <= 118 and "代理" in fn:
                        score += 180
                        match_reason = "民法總則：代理與無權處分專題"
                    elif 125 <= art_num <= 147 and "消滅時效" in fn:
                        score += 180
                        match_reason = "民法總則：消滅時效專題"

            # 2. 債編 (153~756 條)
            elif 153 <= art_num <= 756:
                if "身分法_" in fn or "民總_" in fn:
                    continue  # 嚴格排除身分法與民總筆記
                if "債" in fn:
                    score += 50
                    if 184 <= art_num <= 198:  # 侵權行為
                        if "債總二" in fn:
                            score += 150
                            match_reason = "民法債編：債總二（侵權行為損害賠償專題）"
                        elif "侵權" in fn:
                            score += 180
                            match_reason = "民法債編：侵權行為責任專題"
                    elif 179 <= art_num <= 183:  # 不當得利
                        if "債總二" in fn or "不當得利" in fn:
                            score += 150
                            match_reason = "民法債編：不當得利專題"
                    elif 345 <= art_num <= 756:  # 債各
                        if "債各" in fn:
                            score += 150
                            match_reason = "民法債編各論課輔與各契約專題"

            # 3. 物權編 (757~966 條)
            elif 757 <= art_num <= 966:
                if "身分法_" in fn or "民總_" in fn or "債各_" in fn:
                    continue
                if "物權" in fn:
                    score += 150
                    match_reason = "民法物權編體系"

            # 4. 身分法親屬編 (967~1137 條)
            elif 967 <= art_num <= 1137:
                if "民總_" in fn or "債各_" in fn:
                    continue  # 嚴格排除民總與債各
                if "身分法_" in fn:
                    score += 40
                    if 972 <= art_num <= 979 and "婚約" in fn:
                        score += 160
                        match_reason = "身分法親屬編：婚約專題"
                    elif 980 <= art_num <= 1003 and "三、婚姻" in fn:
                        score += 160
                        match_reason = "身分法親屬編：婚姻成立與效力專題"
                    elif 1004 <= art_num <= 1048 and "夫妻財產制" in fn:
                        score += 180
                        match_reason = "身分法親屬編：夫妻財產制與剩餘財產差額分配專題"
                    elif 1049 <= art_num <= 1058 and "離婚" in fn:
                        score += 180
                        match_reason = "身分法親屬編：離婚與法律效果專題"
                    elif 1059 <= art_num <= 1070 and "自然血親" in fn:
                        score += 160
                        match_reason = "身分法親屬編：父母子女與自然血親專題"
                    elif 1072 <= art_num <= 1083 and "收養" in fn:
                        score += 160
                        match_reason = "身分法親屬編：收養制度專題"
                    elif 1084 <= art_num <= 1090 and "父母子女" in fn:
                        score += 160
                        match_reason = "身分法親屬編：親權行使與權利義務專題"
                    elif 1091 <= art_num <= 1113 and "監護" in fn:
                        score += 160
                        match_reason = "身分法親屬編：監護與輔助專題"
                    elif 1114 <= art_num <= 1121 and "扶養" in fn:
                        score += 160
                        match_reason = "身分法親屬編：扶養義務專題"
                    elif 1122 <= art_num <= 1128 and "家" in fn:
                        score += 160
                        match_reason = "身分法親屬編：家長家屬專題"
                    elif 1129 <= art_num <= 1137 and "親屬會議" in fn:
                        score += 160
                        match_reason = "身分法親屬編：親屬會議專題"
                    elif 967 <= art_num <= 971 and "親屬總論" in fn:
                        score += 160
                        match_reason = "身分法親屬編：親屬編通則專題"

            # 5. 身分法繼承編 (1138~1225 條)
            elif 1138 <= art_num <= 1225:
                if "民總_" in fn or "債各_" in fn:
                    continue
                if "身分法_" in fn:
                    score += 40
                    if art_num == 1140 and "代位繼承" in fn:
                        score += 200
                        match_reason = "身分法繼承編：代位繼承專題"
                    elif art_num in [1141, 1142, 1143, 1144] and "應繼分" in fn:
                        score += 200
                        match_reason = "身分法繼承編：法定應繼分計算專題"
                    elif art_num == 1145 and "喪失繼承權" in fn:
                        score += 200
                        match_reason = "身分法繼承編：喪失繼承權要件專題"
                    elif art_num == 1146 and "繼承回復請求權" in fn:
                        score += 200
                        match_reason = "身分法繼承編：繼承回復請求權專題"
                    elif 1147 <= art_num <= 1153 and ("效力" in fn or "概括與拋棄" in fn):
                        score += 160
                        match_reason = "身分法繼承編：繼承效力與限定責任專題"
                    elif 1151 <= art_num <= 1163 and "共同繼承" in fn:
                        score += 180
                        match_reason = "身分法繼承編：共同繼承與遺產公同共有"
                    elif 1174 <= art_num <= 1185 and "拋棄繼承" in fn:
                        score += 180
                        match_reason = "身分法繼承編：拋棄繼承要件與程序專題"
                    elif 1186 <= art_num <= 1222 and "遺囑" in fn:
                        score += 180
                        match_reason = "身分法繼承編：遺囑之方式與效力專題"
                    elif 1200 <= art_num <= 1208 and "遺贈" in fn:
                        score += 180
                        match_reason = "身分法繼承編：遺贈專題"
                    elif 1223 <= art_num <= 1225 and ("特留分" in fn or "扣減" in fn):
                        score += 200
                        match_reason = "身分法繼承編：特留分與扣減權專題"
                    elif 1138 <= art_num <= 1146 and ("繼承總論" in fn or "遺產繼承人" in fn):
                        score += 150
                        match_reason = "身分法繼承編：法定繼承人順位專題"

        # ------------------ 刑法過濾規則 ------------------
        elif "刑法" in law_name and art_num is not None:
            if 1 <= art_num <= 100:
                if "刑分_" in fn or "各論" in fn:
                    continue  # 排除分則
                if "刑總_" in fn or "刑法總則" in fn or "百題" in fn:
                    score += 50
                    
                    # 刑法百題爭點系列實例演練精準條文映射
                    if "百題" in fn or "釋義與適用" in fn:
                        score += 30
                        # （一）刑法之效力與罪刑法定原則 (第 1~11 條)
                        if 1 <= art_num <= 11 and any(b in fn for b in ["（一）", "(一)", "（1）", "(1)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：罪刑法定原則與時地效力（第1~11條）"
                        # （二）犯罪論體系與行為概念 (第 1~12 條)
                        elif 1 <= art_num <= 12 and any(b in fn for b in ["（二）", "(二)", "（2）", "(2)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：犯罪論體系與行為概念"
                        # （三）客觀構成要件與因果關係 (第 12~14 條)
                        elif 12 <= art_num <= 14 and any(b in fn for b in ["（三）", "(三)", "（3）", "(3)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：因果關係與客觀構成要件"
                        # （四）構成要件該當性、因果關係與客觀歸責、過失 (第 12~14 條)
                        elif 12 <= art_num <= 14 and any(b in fn for b in ["（四）", "(四)", "（4）", "(4)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：構成要件該當性、客觀歸責與過失犯（第12~14條）"
                        # （五）故意、不作為犯 (第 13~15 條)
                        elif 13 <= art_num <= 15 and any(b in fn for b in ["（五）", "(五)", "（5）", "(5)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：故意論與不純正不作為犯保證人地位（第13~15條）"
                        # （六）阻卻違法事由：正當防衛、緊急避難、依法令之行為 (第 21~24 條)
                        elif 21 <= art_num <= 24 and any(b in fn for b in ["（六）", "(六)", "（6）", "(6)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：違法性阻卻事由（正當防衛/緊急避難/依法令行為）"
                        # （七）超法規阻卻違法事由：被害人承諾、推定的承諾 (第 21~24 條)
                        elif 21 <= art_num <= 24 and any(b in fn for b in ["（七）", "(七)", "（7）", "(7)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：超法規阻卻違法事由（承諾與義務衝突）"
                        # （八）責任論與罪責原則 (第 18~20 條)
                        elif 18 <= art_num <= 20 and any(b in fn for b in ["（八）", "(八)", "（8）", "(8)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：責任論與罪責原則"
                        # （九）心神喪失與原因自由行為 (第 19 條)
                        elif art_num == 19 and any(b in fn for b in ["（九）", "(九)", "（9）", "(9)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：心神喪失與原因自由行為（第19條）"
                        # （十）責任能力與原因自由行為 (第 18~20 條)
                        elif 18 <= art_num <= 20 and any(b in fn for b in ["（十）", "(十)", "（10）", "(10)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：責任能力判斷與不法意識（第18~20條）"
                        # （十一）錯誤理論：事實錯誤、禁止錯誤、容許構成要件錯誤 (第 16~17 條)
                        elif 16 <= art_num <= 17 and any(b in fn for b in ["（十一）", "(十一)", "（11）", "(11)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：錯誤論（禁止錯誤/容許構成要件錯誤）"
                        # （十二）未遂犯論：著手實行、不能未遂、中止未遂 (第 25~27 條)
                        elif 25 <= art_num <= 27 and any(b in fn for b in ["（十二）", "(十二)", "（12）", "(12)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：未遂犯論（著手認定/中止未遂/不能未遂）"
                        # （十三）正犯與共犯：共同正犯、間接正犯、身分犯 (第 28、31 條)
                        elif art_num in [28, 31] and any(b in fn for b in ["（十三）", "(十三)", "（13）", "(13)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：正犯論（共同正犯之成立與脫離/間接正犯）"
                        # （十四）狹義共犯：教唆犯、幫助犯 (第 29、30 條)
                        elif art_num in [29, 30] and any(b in fn for b in ["（十四）", "(十四)", "（14）", "(14)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：共犯論（教唆犯逾越與幫助犯之因果關係）"
                        # （十五）題型總合實例演練與競合沒收 (第 15、24、38、50~55 條)
                        elif (art_num in [15, 24, 38, 39, 40] or 50 <= art_num <= 55) and any(b in fn for b in ["（十五）", "(十五)", "（15）", "(15)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：重大總合實例題（不純正不作為＋緊急避難＋義務衝突＋競合沒收）"

                    if 28 <= art_num <= 31 and ("正犯" in fn or "共犯" in fn or "身分犯" in fn):
                        score += 180
                        match_reason = "刑法總則：正犯與共犯專題"
                    elif art_num == 14 and "過失" in fn:
                        score += 180
                        match_reason = "刑法總則：過失犯專題"
                    elif 25 <= art_num <= 27 and "未遂" in fn:
                        score += 180
                        match_reason = "刑法總則：未遂犯理論專題"
                    elif art_num == 15 and "不作為" in fn:
                        score += 180
                        match_reason = "刑法總則：不作為犯專題"
                    elif art_num == 16 and "錯誤" in fn:
                        score += 180
                        match_reason = "刑法總則：錯誤理論專題"
                    elif 50 <= art_num <= 55 and "競合" in fn:
                        score += 180
                        match_reason = "刑法總則：競合理論專題"
            elif 101 <= art_num <= 363:
                if "刑總_" in fn:
                    continue  # 排除總則
                if "刑分_" in fn or "各論" in fn or "百題" in fn:
                    score += 50
                    
                    # 刑法分則百題爭點系列實例演練精準條文映射
                    if "百題" in fn or "釋義與適用" in fn:
                        score += 30
                        # （一）、（二）竊盜罪章 (第 320~324 條)
                        if 320 <= art_num <= 324 and any(b in fn for b in ["（一）", "(一)", "（1）", "(1)", "（二）", "(二)", "（2）", "(2)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：竊盜罪章（動產、竊取行為與所有意圖）"
                        # （三）、（四）詐欺罪章 (第 339~341 條)
                        elif 339 <= art_num <= 341 and any(b in fn for b in ["（三）", "(三)", "（3）", "(3)", "（四）", "(四)", "（4）", "(4)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：詐欺罪章（施用詐術、財產處分與三角詐欺）"
                        # （五）侵占與背信罪章 (第 335~342 條)
                        elif (335 <= art_num <= 338 or art_num == 342) and any(b in fn for b in ["（五）", "(五)", "（5）", "(5)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：侵占罪與背信罪（財產保護身分與違背任務）"
                        # （六）恐嚇取財與擄人勒贖罪章 (第 346~348 條)
                        elif 346 <= art_num <= 348 and any(b in fn for b in ["（六）", "(六)", "（6）", "(6)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：恐嚇取財罪與擄人勒贖罪（索款既遂與擄人意圖）"
                        # （七）贓物罪章 (第 349~351 條)
                        elif 349 <= art_num <= 351 and any(b in fn for b in ["（七）", "(七)", "（7）", "(7)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：贓物罪章（收受/搬運/寄藏/故買與準贓物罪）"
                        # （八）殺人與過失致死罪章 (第 271~276 條)
                        elif 271 <= art_num <= 276 and any(b in fn for b in ["（八）", "(八)", "（8）", "(8)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：殺人罪與過失致死罪（PUA、教唆自殺與客觀歸責）"
                        # （九）傷害罪章 (第 277~287 條)
                        elif 277 <= art_num <= 287 and any(b in fn for b in ["（九）", "(九)", "（9）", "(9)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：傷害罪章（傷害他人身體或健康法益）"
                        # （十）妨害自由罪章 (第 296~308 條，強制罪)
                        elif 296 <= art_num <= 308 and any(b in fn for b in ["（十）", "(十)", "（10）", "(10)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：妨害自由罪章（強制罪第304條、強暴脅迫與違法性審查）"
                        # （十一）妨害名譽及信用罪章 (第 309~314 條)
                        elif 309 <= art_num <= 314 and any(b in fn for b in ["（十一）", "(十一)", "（11）", "(11)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：妨害名譽罪章（公然侮辱與誹謗罪、真實惡意原則）"
                        # （十二）妨害性自主罪章 (第 221~229 條)
                        elif 221 <= art_num <= 229 and any(b in fn for b in ["（十二）", "(十二)", "（12）", "(12)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：妨害性自主罪章（強制性交/猥褻與積極同意權）"
                        # （十五）妨害司法罪章 (第 161~172 條，脫逃、藏匿人犯、偽證誣告)
                        elif 161 <= art_num <= 172 and any(b in fn for b in ["（十五）", "(十五)", "（15）", "(15)"]):
                            score += 180
                            match_reason = "刑法百題爭點演練：妨害司法罪章（脫逃罪、藏匿人犯與偽證誣告）"

                    if 271 <= art_num <= 276 and ("殺人" in fn or "生命" in fn):
                        score += 180
                        match_reason = "刑法分則：侵害生命法益（殺人罪章）"
                    elif 277 <= art_num <= 287 and ("傷害" in fn or "身體" in fn):
                        score += 180
                        match_reason = "刑法分則：侵害身體健康法益（傷害罪章）"
                    elif 288 <= art_num <= 292 and "墮胎" in fn:
                        score += 180
                        match_reason = "刑法分則：墮胎罪章"
                    elif 293 <= art_num <= 295 and "遺棄" in fn:
                        score += 180
                        match_reason = "刑法分則：遺棄罪章"
                    elif 296 <= art_num <= 308 and ("妨害自由" in fn or "自由" in fn):
                        score += 180
                        match_reason = "刑法分則：妨害自由罪章"
                    elif 315 <= art_num <= 319 and "妨害秘密" in fn:
                        score += 180
                        match_reason = "刑法分則：妨害秘密罪章"

        # ------------------ 保險法過濾規則 ------------------
        elif "保險法" in law_name and art_num is not None:
            if "保險法_" in fn:
                score += 30
                if 14 <= art_num <= 20 and "保險利益" in fn:
                    score += 180
                    match_reason = "保險利益專題"
                elif 21 <= art_num <= 28 and "保險費" in fn:
                    score += 180
                    match_reason = "保險費義務專題"
                elif 29 <= art_num <= 34 and "保險人之義務" in fn:
                    score += 180
                    match_reason = "保險人之義務專題"
                elif 35 <= art_num <= 42 and "複保險" in fn:
                    score += 180
                    match_reason = "複保險與再保險專題"
                elif 55 <= art_num <= 69 and "要保人之義務" in fn:
                    score += 180
                    match_reason = "要保人之義務與告知義務專題"
                elif art_num == 53 and "保險代位" in fn:
                    score += 200
                    match_reason = "保險代位權專題"
                elif art_num == 65 and "消滅時效" in fn:
                    score += 200
                    match_reason = "保險法消滅時效專題"
                elif art_num in [54, 54-1] and "契約條款" in fn:
                    score += 180
                    match_reason = "保險契約條款解釋原則"
                elif 70 <= art_num <= 99 and "損害保險" in fn:
                    score += 150
                    match_reason = "損害保險總論"
                elif 90 <= art_num <= 95 and "責任保險" in fn:
                    score += 180
                    match_reason = "責任保險專題"
                elif 95 <= art_num <= 98 and "保證保險" in fn:
                    score += 180
                    match_reason = "保證保險專題"

        # ------------------ 公司法過濾規則 ------------------
        elif "公司法" in law_name and art_num is not None:
            if "商事法" in fn:
                score += 30
                if 1 <= art_num <= 97 and "商事法一、二" in fn:
                    score += 160
                    match_reason = "公司法總則、負責人與設立"
                elif (98 <= art_num <= 113 or 370 <= art_num <= 386) and "有限公司" in fn:
                    score += 160
                    match_reason = "有限公司與外國公司"
                elif 128 <= art_num <= 245 and "股份有限公司" in fn:
                    score += 160
                    match_reason = "股份有限公司專題"
                elif 246 <= art_num <= 276 and ("公司債" in fn or "新股發行" in fn):
                    score += 180
                    match_reason = "公司債與新股發行"
                elif 356 <= art_num <= 357 and "閉鎖性" in fn:
                    score += 190
                    match_reason = "閉鎖性股份有限公司專題"

        # ------------------ 憲法過濾規則 ------------------
        elif "憲法" in law_name and art_num is not None:
            if "憲法" in fn:
                score += 30
                if 1 <= art_num <= 6 and ("導論" in fn or "基本原則" in fn):
                    score += 160
                    match_reason = "憲法總綱與憲法基本原則"
                elif 7 <= art_num <= 24 and "基本權" in fn:
                    score += 180
                    match_reason = "基本權利保障與限制合憲審查"
                elif 25 <= art_num <= 106 and "權力分立" in fn:
                    score += 180
                    match_reason = "國家機關組織與權力分立原則"
                elif 171 <= art_num <= 175 and ("釋字" in fn or "修憲" in fn):
                    score += 180
                    match_reason = "司法院大法官解釋與違憲審查"

        # 內文關鍵字精準加分
        if content:
            keywords_to_check = [
                '侵權行為', '消滅時效', '意思表示', '代理', '代位繼承', '夫妻財產',
                '剩餘財產', '特留分', '不當得利', '正犯', '共犯', '未遂', '過失',
                '保險代位', '告知義務', '善意受讓', '利益迴避'
            ]
            for kw in keywords_to_check:
                if kw in content and kw in fn:
                    score += 100
                    if not match_reason:
                        match_reason = f"命中條文法理關鍵字【{kw}】"

        if score >= 100:
            nat_info = classify_document_nature(fn, n.get("path", ""))
            n_copy = dict(n)
            n_copy["match_reason"] = match_reason
            n_copy["score"] = score
            n_copy["doc_nature"] = nat_info["doc_nature"]
            n_copy["nature_name"] = nat_info["nature_name"]
            n_copy["badge_icon"] = nat_info["badge_icon"]
            n_copy["tag"] = nat_info["tag"]
            scored.append(n_copy)

    scored.sort(key=lambda x: -x["score"])
    return scored[:15]

def get_article_annotations(law_name: str, article_no: str, content: str = "") -> Dict[str, Any]:
    """獲取特定條文的跨庫綜合註記（實務裁判、相關命令、實戰試題、課輔講義與純讀書筆記）"""
    articles, meta, law_map = load_six_codes_data()
    
    # 標準化條號鍵
    clean_no = str(article_no).replace(" ", "").replace("第", "").replace("條", "")
    key = f"{law_name}_第{clean_no}條"
    
    prec_index = meta.get("precedents_article_index", {})
    matched_precedents = prec_index.get(key, [])
    
    # 相關命令與細則
    reg_map = meta.get("regulations_map", {})
    matched_orders = reg_map.get(law_name, [])
    
    # 結合行政命令全文大庫與主管機關函釋引擎
    try:
        from admin_rulings_engine import get_law_key_regulations, get_admin_rulings_for_article
        key_regs = get_law_key_regulations(law_name)
        admin_rulings = get_admin_rulings_for_article(law_name, clean_no)
    except Exception:
        key_regs = []
        admin_rulings = []
    
    # 整合六法標註目錄與雲端最新 580+ 份講義、筆記與試題大庫
    unified_cat = get_unified_materials_catalog(meta.get("notes_catalog", {}))
    if not content:
        for a in law_map.get(law_name, []):
            if normalize_article_no(a.get("article_no", "")) == normalize_article_no(article_no):
                content = a.get("content", "")
                break
    anno_materials = get_precise_relevant_notes(law_name=law_name, article_no=article_no, content=content, notes_cat=unified_cat)

    # 嚴格分流：將題目、講義、個人筆記三者徹底區隔，絕不把題目當成筆記！
    matched_questions = [x for x in anno_materials if x.get("doc_nature") == "question"]
    matched_handouts = [x for x in anno_materials if x.get("doc_nature") == "handout"]
    matched_pure_notes = [x for x in anno_materials if x.get("doc_nature") == "note"]

    # 立法修正理由與歷史條文演革
    legislative_details = get_article_legislative_details(law_name=law_name, article_no=article_no, content=content)

    return {
        "law_name": law_name,
        "article_no": article_no,
        "precedents": matched_precedents,
        "orders": matched_orders,
        "key_regulations": key_regs,
        "admin_rulings": admin_rulings,
        "questions": matched_questions[:5],   # 🎯 關聯實戰試題與百題爭點演練
        "handouts": matched_handouts[:5],     # 📘 關聯課輔講義與授課教材
        "notes": matched_pure_notes[:5],      # 📝 純個人讀書筆記
        "all_materials": anno_materials,
        "legislative_details": legislative_details
    }


def clean_history_text(text: str) -> str:
    """修復跨行斷裂的條號與數字（例如 '9 \n 85' -> '985', '102 \n 4~1030' -> '1024~1030'）"""
    if not text:
        return ""
    t = re.sub(r'(\d+)\s*[\r\n]+\s*(\d+)', r'\1\2', text)
    t = re.sub(r'([、，,～~至到\-之])\s*[\r\n]+\s*', r'\1', t)
    t = re.sub(r'\s*[\r\n]+\s*([、，,～~至到\-之])', r'\1', t)
    return t

def parse_enactment_year_from_text(raw_text: str) -> str:
    """從法規歷史沿革首筆紀錄解析制定公布之民國年份"""
    if not raw_text:
        return ""
    cn_nums = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '百': 100}
    m = re.search(r'中華民國\s*([0-9]+)\s*年', raw_text)
    if m:
        return m.group(1)
    m_cn = re.search(r'中華民國\s*([一二三四五六七八九十百零]+)\s*年', raw_text)
    if m_cn:
        cn_str = m_cn.group(1)
        val = 0
        if '百' in cn_str:
            parts = cn_str.split('百')
            h = cn_nums.get(parts[0], 1) if parts[0] else 1
            val += h * 100
            rem = parts[1]
        else:
            rem = cn_str
        if '十' in rem:
            parts = rem.split('十')
            t = cn_nums.get(parts[0], 1) if parts[0] else 1
            val += t * 10
            u = cn_nums.get(parts[1], 0) if parts[1] else 0
            val += u
        elif rem:
            val += cn_nums.get(rem, 0)
        if val > 0:
            return str(val)
    return ""

def parse_law_history_entries(raw_text: str) -> List[Dict[str, Any]]:
    """將法規沿革文字（1. 中華民國... 2. 中華民國...）解析為結構化時間軸"""
    if not raw_text:
        return []
    cleaned_raw = clean_history_text(raw_text.strip())
    raw_entries = re.split(r'\n(?=\d+\.)', cleaned_raw)
    parsed = []
    for entry in raw_entries:
        clean = ' '.join(entry.split())
        m = re.match(r'^(\d+)\.\s*(.+)', clean)
        if not m:
            continue
        seq = int(m.group(1))
        content = m.group(2)
        m_date = re.search(r'(中華民國[^\s]+日)', content)
        date_str = m_date.group(1) if m_date else ''
        m_decree = re.search(r'((?:國民政府|總統|行政院|經濟部|法務部|金融監督管理委員會|司法院|內政部|勞動部|財政部)[^\s]+令)', content)
        decree_str = m_decree.group(1) if m_decree else ''
        
        action = "修正公布"
        if "制定公布" in content or "訂定發布" in content:
            action = "制定發布"
        elif "廢止" in content:
            action = "廢止"
            
        parsed.append({
            'seq': seq,
            'date': date_str,
            'decree': decree_str,
            'action': action,
            'content': content
        })
    return parsed

def is_article_in_history_entry(art_no: str, entry_text: str) -> bool:
    """精準檢驗某條號是否受該次立法/修法公報影響（杜絕模糊比對，精準支援範圍與枝條）"""
    clean_no = normalize_article_no(art_no)
    if not clean_no:
        return False
        
    # 1. 獨立條號直接邊界匹配：例如「修正第10條條文」或「修正第 10 條」，前後嚴禁有數字、之、連字號
    direct_pat = rf'(?<![之\d\-])第\s*{re.escape(clean_no)}\s*條(?![之\d\-])'
    if re.search(direct_pat, entry_text):
        return True

    # 2. 匹配條號列舉區塊：例如「修正第 1007、1008...條」
    article_blocks = re.findall(r'第\s*([^條]+?)\s*條', entry_text)
    for block in article_blocks:
        tokens = re.split(r'[、，,\s及與]+', block)
        for token in tokens:
            t = normalize_article_no(token)
            if t == clean_no:
                return True
            # 範圍比對：5 至 15, 5～15, 5~15, 5到15 (嚴格排除連字號 -，因那是枝條如 1055-1)
            m_range = re.match(r'^(\d+)\s*(?:至|～|~|到)\s*(\d+)$', token.strip())
            if m_range and '-' not in clean_no and clean_no.isdigit():
                start, end = int(m_range.group(1)), int(m_range.group(2))
                if min(start, end) <= int(clean_no) <= max(start, end):
                    return True

    # 3. 跨條區間：第 5 條至第 15 條 或 第 5 條到第 15 條
    cross_range = re.findall(r'第\s*(\d+)\s*條\s*(?:至|～|~|到)\s*第\s*(\d+)\s*條', entry_text)
    if '-' not in clean_no and clean_no.isdigit():
        target_int = int(clean_no)
        for r_start, r_end in cross_range:
            if min(int(r_start), int(r_end)) <= target_int <= max(int(r_start), int(r_end)):
                return True

    return False

# 設置別名以支援多模組呼叫
is_article_targeted_in_decree = is_article_in_history_entry

def get_law_legislative_history(law_name: str) -> Dict[str, Any]:
    """獲取指定法規（法律、法規命令、施行細則）之完整官方立法沿革與歷次修正公報"""
    hist_cat = load_law_histories()
    item = hist_cat.get(law_name)
    matched_name = law_name
    if not item:
        for k, v in hist_cat.items():
            if k == law_name or (len(law_name) >= 3 and law_name in k):
                item = v
                matched_name = k
                break
    if not item:
        return {
            "law_name": law_name,
            "type": "法規",
            "category": "",
            "pcode": "",
            "histories_raw": "",
            "timeline": [],
            "total_amendments": 0
        }
    
    raw = item.get("histories", "")
    timeline = parse_law_history_entries(raw)
    return {
        "law_name": matched_name,
        "type": item.get("type", "法規"),
        "category": item.get("category", ""),
        "pcode": item.get("pcode", ""),
        "histories_raw": raw,
        "timeline": timeline,
        "total_amendments": len(timeline)
    }

def get_article_legislative_details(law_name: str, article_no: str, content: str = "") -> Dict[str, Any]:
    """
    獲取特定法條之完整立法修法理由與歷史新舊條文對照（比照法源法律網依年份降冪倒序呈現）：
    1. 優先檢索本地專屬快取庫 (statute_reasons_cache.json)
    2. 檢索國考核心考點庫 (article_legislative_catalog.json)
    3. 自動從全國法規歷史沿革 (law_histories_catalog.json) 篩選該條文經歷之歷次官方修正公報
    4. 若暫無官方條文明細，自動根據法規沿革與條文內容合成標準沿革卡片，確保前端絕無空泛狀態
    """
    clean_no = normalize_article_no(article_no)
    
    # 候選鍵名
    candidate_keys = [
        f"{law_name}_第{clean_no}條",
        f"{law_name}_{clean_no}",
        f"{law_name}_第{clean_no}條文"
    ]
    if "中華民國刑法" in law_name:
        candidate_keys.append(f"刑法_第{clean_no}條")
        candidate_keys.append(f"刑法_{clean_no}")
    elif law_name == "刑法":
        candidate_keys.append(f"中華民國刑法_第{clean_no}條")
        candidate_keys.append(f"中華民國刑法_{clean_no}")
    elif "中華民國憲法" in law_name:
        candidate_keys.append(f"憲法_第{clean_no}條")
    elif law_name == "憲法":
        candidate_keys.append(f"中華民國憲法_第{clean_no}條")
        
    # Step A: 優先命中 statute_reasons_cache.json (法源法律網標準格式)
    statute_cache = load_statute_reasons_cache()
    curated_data = None
    for k in candidate_keys:
        if k in statute_cache:
            curated_data = statute_cache[k]
            break
            
    # Step B: 檢索 article_legislative_catalog.json
    if not curated_data:
        leg_cat = load_article_legislative_catalog()
        for k in candidate_keys:
            if k in leg_cat:
                curated_data = leg_cat[k]
                break

    # 檢索全法沿革
    law_hist = get_law_legislative_history(law_name)
    timeline_hits = []
    for entry in law_hist.get("timeline", []):
        if is_article_in_history_entry(clean_no, entry.get("content", "")):
            timeline_hits.append(entry)

    # 整理歷次修正列表，嚴格依年份倒序（降冪，由新至舊）排列
    raw_amends = curated_data.get("amendments", []) if curated_data else []
    enactment_card = curated_data.get("enactment_card") if curated_data else None
    
    # 區分真實修正 (amendments) 與初次制定 (enactment)
    formatted_amends = []
    if raw_amends:
        for idx_a, a in enumerate(raw_amends):
            is_enact = (
                ("制定" in a.get("date", "") and "修正" not in a.get("date", ""))
                or ("初次制定" in a.get("previous_text", ""))
                or ("未曾修正" in a.get("key_changes", ""))
                or ("未曾修改" in a.get("key_changes", ""))
            )
            card = {
                "date": a.get("date", ""),
                "gazette": a.get("gazette", ""),
                "is_current": a.get("is_current", (idx_a == 0)),
                "version_tag": a.get("version_tag", ""),
                "previous_text": a.get("previous_text", ""),
                "current_text": a.get("current_text", content if a.get("is_current", (idx_a == 0)) else ""),
                "key_changes": a.get("key_changes", ""),
                "reason": a.get("reason", a.get("summary_reasons", "")),
                "exam_impact": a.get("exam_impact", "")
            }
            if is_enact:
                if not enactment_card:
                    enactment_card = card
            else:
                if not card["version_tag"]:
                    date_s = a.get("date", "最新修正")
                    card["version_tag"] = f"民國 {date_s} 修正（現行有效條文）" if (len(formatted_amends) == 0) else f"民國 {date_s} 修正"
                formatted_amends.append(card)
    elif timeline_hits:
        # Step C: 若無專屬理由但有公報紀錄，自動無縫合成歷次沿革卡片，確保前端絕非空白且絕無罐頭廢話
        for idx_t, h in enumerate(reversed(timeline_hits)):
            is_cur = (idx_t == 0)
            seq_str = f"第 {h.get('seq', '')} 次修正" if h.get('seq', 0) > 1 else "制定公布"
            v_tag = f"民國 {h.get('date', '')} {seq_str}（現行有效條文）" if is_cur else f"民國 {h.get('date', '')} {seq_str}"
            decree_title = h.get('decree', '') or f"{law_name}公布令"
            formatted_amends.append({
                "date": h.get("date", ""),
                "gazette": decree_title,
                "is_current": is_cur,
                "version_tag": v_tag,
                "previous_text": f"（修正前歷史條文，發布字號：{decree_title}）",
                "current_text": content if is_cur else "（修正條文文字如公報記載）",
                "key_changes": h.get("action", f"{seq_str}條文"),
                "reason": f"立法院三讀及總統令公布紀錄：{h.get('content', '')}",
                "exam_impact": f"生效施行原則：除法律別有規定施行日期外，自{h.get('date', '')}公布或發布日起算至第三日起發生效力。"
            })
    
    # 若為未曾修正之條文（0次修正），自動裝配真實制定沿革卡片，但保持 curated_amendments 為空 ([]) 以確保修正次數為 0
    enact_year = parse_enactment_year_from_text(law_hist.get("histories_raw", ""))
    enact_str = f"民國 {enact_year} 年" if enact_year else "初次制定公布"
    first_entry = law_hist.get("timeline", [{}])[0] if law_hist.get("timeline") else {}
    first_decree = first_entry.get("decree", f"{law_name}制定公布令")
    if not enactment_card and len(formatted_amends) == 0:
        enactment_card = {
            "date": f"{enact_str}制定公布",
            "gazette": first_decree,
            "is_current": True,
            "version_tag": f"{law_name} 現行有效條文（制定公布迄今未曾修改）",
            "previous_text": f"（{enact_str}制定公布全文，施行迄今未曾修正）",
            "current_text": content,
            "key_changes": "制定公布全文（歷久彌新未曾修正）",
            "reason": f"一、本條自{enact_str}制定公布施行迄今未曾修改，文字歷久彌新，為我國法秩序之基石規範。\n二、司法審判與國考實務適用上，以現行完整法條文字為準，並參酌歷年司法判解與大法庭裁定之實務見解。",
            "exam_impact": "本條施行迄今未曾修正，無新舊法過渡適用問題，直接適用現行有效條文。"
        }

    default_intent = ""
    default_summary = ""
    if timeline_hits:
        latest_date = timeline_hits[-1].get('date', '')
        latest_decree = timeline_hits[-1].get('decree', '')
        default_intent = f"🎯 立法意旨：本條歷經立法院修法三讀程序修正通過，最新修正發布於民國 {latest_date}。"
        default_summary = f"本條於立法院沿革中查有 {len(timeline_hits)} 次官方公布/修正紀錄，最新發布令號為：{latest_decree}。"
    else:
        default_intent = f"🎯 立法意旨：本條於{enact_str}制定公布，文字歷久彌新未曾修改。"
        default_summary = f"本條自{enact_str}制定公布施行迄今未曾修正，維持原制定條文內容完整適用。"

    is_initial = (len(formatted_amends) == 0 and len(timeline_hits) == 0)
    return {
        "law_name": law_name,
        "article_no": clean_no,
        "has_curated_data": bool(curated_data),
        "legislative_intent": curated_data.get("legislative_intent", default_intent) if curated_data else default_intent,
        "summary_reasons": curated_data.get("summary_reasons", default_summary) if curated_data else default_summary,
        "curated_amendments": formatted_amends,
        "enactment_card": enactment_card,
        "is_initial_enactment": is_initial,
        "timeline_hits": timeline_hits,
        "total_official_hits": len(timeline_hits)
    }

def synthesize_article_legislative_details(law_name: str, article_no: str, content: str) -> Dict[str, Any]:
    """
    呼叫 Gemini 3.8 / 2.0 Flash 即時提煉深度立法理由、新舊條文對照與修法沿革，
    並自動存入本地持久化 catalog 供日後秒級調閱。
    """
    clean_no = normalize_article_no(article_no)
    api_key = get_gemini_api_key()
    if not api_key:
        raise ValueError("未檢測到 GEMINI_API_KEY！")

    prompt = f"""
你是一位司律典試委員兼立法院法制局法學專家。
請針對【{law_name}】第 {clean_no} 條進行權威、專業之「立法理由與歷史條文演變」全面釋析。

【條文內容】：
{content}

請嚴謹產出 JSON 格式，包含以下欄位：
{{
  "legislative_intent": "原始立法意旨與規範目的（說明立法院立法時所欲保護之法益與制度設計）",
  "summary_reasons": "歷次修正總說明與核心法理演變",
  "amendments": [
    {{
      "date": "修正公布日期（例如：107年08月01日）",
      "gazette": "總統令/部會令號（例如：總統華總一經字第 10700083291 號令）",
      "reason": "詳細立法修正理由（官方立法院公報/提案部會說明理由）",
      "previous_text": "本次修正前之歷史舊條文內容（若為初次制定請註明「制定公布全文」）",
      "current_text": "本次修正後之條文內容",
      "key_changes": "核心修法要點與條文文字變更說明",
      "exam_impact": "國考實務影響與新舊法適用要點（如不溯及既往、程序從新實體從舊）"
    }}
  ]
}}
請僅輸出標準 JSON，不得包含 Markdown 程式碼區塊外多餘說明。
"""
    models_to_try = get_gemini_models_to_try(DEFAULT_GEMINI_MODEL)
    last_err = None
    raw_json_str = ""

    for m_name in models_to_try:
        try:
            if USE_MODERN_GENAI:
                client = genai.Client(api_key=api_key)
                cfg = genai_types.GenerateContentConfig(temperature=0.2)
                resp = client.models.generate_content(model=m_name, contents=prompt, config=cfg)
                raw_json_str = resp.text
            else:
                legacy_genai.configure(api_key=api_key)
                cur_model = legacy_genai.GenerativeModel(model_name=m_name)
                resp = cur_model.generate_content(
                    prompt, generation_config=legacy_genai.types.GenerationConfig(temperature=0.2)
                )
                raw_json_str = resp.text
            if raw_json_str:
                break
        except Exception as e:
            last_err = e
            continue

    if not raw_json_str:
        raise RuntimeError(f"立法理由提煉失敗: {last_err}")

    m = re.search(r'\{.*\}', raw_json_str, re.DOTALL)
    if not m:
        raise ValueError("Gemini 未返回合規 JSON 格式")
    
    parsed = json.loads(m.group(0))
    key = f"{law_name}_第{clean_no}條"
    
    leg_cat = load_article_legislative_catalog()
    leg_cat[key] = {
        "law_name": law_name,
        "article_no": clean_no,
        "current_article_text": content,
        "legislative_intent": parsed.get("legislative_intent", ""),
        "summary_reasons": parsed.get("summary_reasons", ""),
        "amendments": parsed.get("amendments", [])
    }
    
    for p in DATA_PATHS_LEGISLATIVE:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(leg_cat, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return get_article_legislative_details(law_name, clean_no, content)


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

### 六、🔗 專業跨法規關聯條文網絡（Cross-Statutory Network）
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


def format_legal_article_text(text: str) -> str:
    """
    將法律條文內容進行標準法學結構化排版（段落、款項分離縮排）。
    """
    if not text or not isinstance(text, str):
        return ""
    t = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    t = re.sub(r'(?<=[。；:：\n])\s*(?=[一二三四五六七八九十百]+[、\s])', '\n  ', t)
    t = re.sub(r'(?<=[。；:：\n])\s*(?=[（(][一二三四五六七八九十百]+[)）])', '\n    ', t)
    return t


def render_formatted_article_quote(content: str, title: str = "📜 條文全文") -> str:
    """
    將條文內容轉為美觀之 Markdown 引用區塊格式。
    """
    formatted = format_legal_article_text(content)
    lines = [f"> {line}  " for line in formatted.split('\n')]
    return f"> **{title}**：  \n" + '\n'.join(lines)

