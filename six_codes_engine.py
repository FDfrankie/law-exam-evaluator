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

_CACHED_ARTICLES: Optional[List[Dict[str, Any]]] = None
_CACHED_META: Optional[Dict[str, Any]] = None
_CACHED_LAW_MAP: Optional[Dict[str, List[Dict[str, Any]]]] = None
_CACHED_HISTORIES: Optional[Dict[str, Any]] = None
_CACHED_LEGISLATIVE: Optional[Dict[str, Any]] = None

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
        from lawbank_engine import BooleanQueryParser, evaluate_boolean_query
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

def get_precise_relevant_notes(law_name: str, article_no: str, content: str = "", notes_cat: dict = None) -> List[Dict[str, Any]]:
    """
    依據法典編章結構、條號區間與實體法考點關鍵字，精準過濾關聯之個人讀書筆記。
    嚴格防範「全科全部灌入（例如民法184條灌入離婚親屬筆記）」的問題，只返回高精確度相關之筆記（最多 3~5 篇）。
    """
    if not notes_cat:
        return []
    
    # 統整對應考科筆記清單
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
                if "民總_" in fn:
                    score += 50
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
                if "刑總_" in fn:
                    score += 50
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
                if "刑分_" in fn or "各論" in fn:
                    score += 50
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
            n_copy = dict(n)
            n_copy["match_reason"] = match_reason
            n_copy["score"] = score
            scored.append(n_copy)

    scored.sort(key=lambda x: -x["score"])
    return scored[:5]

def get_article_annotations(law_name: str, article_no: str, content: str = "") -> Dict[str, Any]:
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
    
    # 結合行政命令全文大庫與主管機關函釋引擎
    try:
        from admin_rulings_engine import get_law_key_regulations, get_admin_rulings_for_article
        key_regs = get_law_key_regulations(law_name)
        admin_rulings = get_admin_rulings_for_article(law_name, clean_no)
    except Exception:
        key_regs = []
        admin_rulings = []
    
    # 個人讀書筆記 (改採精準編章考點過濾，嚴防全科灌入)
    notes_cat = meta.get("notes_catalog", {})
    if not content:
        for a in law_map.get(law_name, []):
            if normalize_article_no(a.get("article_no", "")) == normalize_article_no(article_no):
                content = a.get("content", "")
                break
    matched_notes = get_precise_relevant_notes(law_name=law_name, article_no=article_no, content=content, notes_cat=notes_cat)

    # 立法修正理由與歷史條文演革
    legislative_details = get_article_legislative_details(law_name=law_name, article_no=article_no, content=content)

    return {
        "law_name": law_name,
        "article_no": article_no,
        "precedents": matched_precedents,
        "orders": matched_orders,
        "key_regulations": key_regs,
        "admin_rulings": admin_rulings,
        "notes": matched_notes,
        "legislative_details": legislative_details
    }


def parse_law_history_entries(raw_text: str) -> List[Dict[str, Any]]:
    """將法規沿革文字（1. 中華民國... 2. 中華民國...）解析為結構化時間軸"""
    if not raw_text:
        return []
    lines = raw_text.strip()
    raw_entries = re.split(r'\n(?=\d+\.)', lines)
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
    """精準檢驗某條號是否受該次立法/修法公報影響（支援連號範圍如 204～206 及枝條如 759-1）"""
    clean_no = normalize_article_no(art_no)
    if not clean_no:
        return False
    # 邊界完全匹配
    pattern = r'(?:第\s*)?' + re.escape(clean_no) + r'(?:\s*條|[、，,\s]|$)'
    if re.search(pattern, entry_text):
        return True
    
    # 範圍匹配，例如 204～206, 200～210, 197-205
    if '-' not in clean_no and clean_no.isdigit():
        target_int = int(clean_no)
        ranges = re.findall(r'(\d+)\s*[～~至到-]\s*(\d+)', entry_text)
        for r_start, r_end in ranges:
            if int(r_start) <= target_int <= int(r_end):
                return True
    return False

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
    獲取特定法條之完整立法修法理由與歷史新舊條文對照：
    1. 檢索人工精選之國考核心考點庫 (article_legislative_catalog.json)
    2. 自動從全國法規歷史沿革 (law_histories_catalog.json) 篩選該條文經歷之歷次官方修正公報
    """
    clean_no = normalize_article_no(article_no)
    leg_cat = load_article_legislative_catalog()
    
    candidate_keys = [
        f"{law_name}_第{clean_no}條",
        f"{law_name}_{clean_no}",
        f"{law_name}_第{clean_no}條文"
    ]
    if "中華民國刑法" in law_name:
        candidate_keys.append(f"刑法_第{clean_no}條")
    elif law_name == "刑法":
        candidate_keys.append(f"中華民國刑法_第{clean_no}條")
    elif "中華民國憲法" in law_name:
        candidate_keys.append(f"憲法_第{clean_no}條")
    elif law_name == "憲法":
        candidate_keys.append(f"中華民國憲法_第{clean_no}條")
        
    curated_data = None
    for k in candidate_keys:
        if k in leg_cat:
            curated_data = leg_cat[k]
            break
            
    law_hist = get_law_legislative_history(law_name)
    timeline_hits = []
    for entry in law_hist.get("timeline", []):
        if is_article_in_history_entry(clean_no, entry.get("content", "")):
            timeline_hits.append(entry)
            
    return {
        "law_name": law_name,
        "article_no": clean_no,
        "has_curated_data": bool(curated_data),
        "legislative_intent": curated_data.get("legislative_intent", "") if curated_data else "",
        "summary_reasons": curated_data.get("summary_reasons", "") if curated_data else "",
        "curated_amendments": curated_data.get("amendments", []) if curated_data else [],
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
