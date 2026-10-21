"""
legal_judgment_analyzer.py
裁判法律爭點檢驗、程序駁回實質排除與歷審裁判脈絡鏈提取核心引擎

核心任務：
1. 【爭點實質性檢驗 (Legal Issue Substance Filtering)】：
   - 自動檢驗輸入之裁判書全文是否包含真實之「實體法律爭點 (Substantive Legal Issues)」。
   - 自動辨識並排除 (Discard) 純程序駁回裁定（如上訴未繳裁判費、上訴逾期、未委任律師、程式不合駁回、管轄移轉等）
     與無法律爭點之通常例行裁定（如單純定應執行刑、易科罰金、延長羈押等）。
   - 防止 AI 在無實體爭點之程序裁定上虛構或幻覺 IRAC 法學要旨。

2. 【歷審裁判脈絡鏈溯源 (Judicial Instance History & Chain Extraction)】：
   - 自動自裁判書內文中正則萃取所有關聯之「歷審裁判案號」（第一審地院事實審、第二審高院上訴審、更審及最高院）。
   - 剖析本裁判對歷審之處分動作（廢棄發回、駁回上訴、自為改判、廢棄原裁定）。
   - 若本裁定為最高法院程序駁回，自動定位並導引使用者查閱承載「真實法律爭點」之【原審實體判決】！
"""
import re
from typing import Dict, Any, List, Optional, Tuple

# 純程序駁回裁定特徵特徵庫 (欠缺實體法律爭點之指標)
PROCEDURAL_DISMISSAL_PATTERNS = [
    r"未繳納(?:第一審|第二審|第三審)?裁判費",
    r"未繳納訴訟費用",
    r"逾期(?:提起)?上訴",
    r"上訴逾期",
    r"逾期(?:提起)?抗告",
    r"未委任律師為訴訟代理人",
    r"未補正委任律師",
    r"程式顯?有不符",
    r"程式不合",
    r"程式不合法",
    r"起訴不合程式",
    r"未具體指摘原判決",
    r"未具體指明原判決",
    r"本件上訴難認合法",
    r"上訴(?:為)?不合法",
    r"抗告(?:為)?不合法",
    r"再抗告(?:為)?不合法",
    r"聲請(?:為)?不合法",
    r"無管轄權.*移送",
    r"公示送達",
    r"公示催告"
]

# 通常例行性無實體法理爭執裁定特徵庫
ROUTINE_FACTUAL_PATTERNS = [
    r"定(?:其)?應執行(?:之)?刑",
    r"(?:聲請|准予)?易科罰金",
    r"(?:定其)?易服勞役",
    r"(?:准予|予以|聲請)?延長羈押",
    r"(?:准予|予以|聲請)?停止羈押",
    r"沒入保證金",
    r"公示送達",
    r"公示催告",
    r"本票(?:准予)?強制執行",
    r"支付命令"
]

# 實體法學爭點之陽性特徵庫 (具備實質爭點指標)
SUBSTANTIVE_ISSUE_KEYWORDS = [
    "爭點", "法律問題", "見解歧異", "提案大法庭", "大法庭", "憲判字", "司法院解釋", "判例",
    "有權處分", "無權處分", "善意受讓", "不當得利", "侵權行為", "債務不履行", "契約解釋",
    "構成要件", "違法性", "罪責", "阻卻違法", "正當防衛", "緊急避難", "自首", "共同正犯",
    "法律保留", "比例原則", "正當法律程序", "不確定法律概念", "行政裁量", "信賴保護",
    "既判力", "爭點效", "遮斷效", "舉證責任", "傳聞法則", "證據能力", "合法聽審"
]

# 台灣法院正規名稱庫
COURT_NAME_PATTERN = r"(臺灣[^\s0-9]+?法院|福建[^\s0-9]+?法院|最高法院|最高行政法院|臺北高等行政法院|台北高等行政法院|臺中高等行政法院|台中高等行政法院|高雄高等行政法院|智慧財產及商業法院|智慧財產法院)"


def evaluate_judgment_substance(
    text: str,
    title: str = "",
    doc_type: str = ""
) -> Dict[str, Any]:
    """
    【爭點實質性評鑑核心】：
    判定輸入之裁判文書是否具備「實質法律爭點」。
    若屬純程序性駁回或無實體爭鳴之通常裁定，予以排除標記並提取其歷審裁判案號。
    """
    clean_text = str(text or "").strip()
    if not clean_text:
        return {
            "has_legal_issue": False,
            "is_procedural_dismissal": True,
            "is_routine_factual_order": False,
            "discard_reason": "輸入文字為空，無法提取法律爭點。",
            "substantive_score": 0,
            "issue_density": "無",
            "extracted_history_instances": [],
            "substantive_prior_instance": None,
            "legal_citations_detected": []
        }

    # 1. 萃取涉案法條
    citations = re.findall(
        r'(?:憲法|民法|刑法|民事訴訟法|刑事訴訟法|行政程序法|行政訴訟法|公司法|證券交易法|保險法|行政罰法|國家賠償法)第\s*[0-9\-]+(?:之[0-9]+)?\s*條',
        clean_text
    )
    citations = list(dict.fromkeys(citations))

    # 2. 檢測歷審裁判案號 (Prior & Successive Instances)
    history_instances = extract_instance_history(clean_text, current_case_id=title)

    # 3. 檢測純程序性駁回 (Procedural Dismissal)
    matched_proc_patterns = []
    for pat in PROCEDURAL_DISMISSAL_PATTERNS:
        if re.search(pat, clean_text):
            matched_proc_patterns.append(pat)

    is_dismissal_phrase = bool(re.search(r"(上訴|抗告|聲請|再抗告)(為不合法|不合法)?(，|\s*)(應予|即應|爰予|逕予)?駁回", clean_text))
    has_substantive_terms = any(kw in clean_text for kw in SUBSTANTIVE_ISSUE_KEYWORDS)

    # 4. 檢測通常例行裁定 (Routine Factual Order)
    matched_routine_patterns = [pat for pat in ROUTINE_FACTUAL_PATTERNS if re.search(pat, clean_text)]
    is_routine_order = bool(matched_routine_patterns) and not has_substantive_terms

    # 判定是否為純程序駁回 (無法律爭點)
    is_procedural = False
    discard_reason = ""

    # 情境 A: 明確符合法定程序駁回條款且主文或文末駁回
    if matched_proc_patterns and (is_dismissal_phrase or "應予駁回" in clean_text or "上訴駁回" in clean_text):
        # 若通篇字數短 (< 800 字) 且缺乏實體爭點詞彙
        if len(clean_text) < 1500 or not has_substantive_terms or "大法庭" not in clean_text:
            is_procedural = True
            if "未繳納" in clean_text and "裁判費" in clean_text:
                discard_reason = "【純程序駁回】未依法繳納訴訟或裁判費，經裁定命補正逾期未補正，屬程式欠缺之純程序裁定，無實體法學爭點。"
            elif "未委任律師" in clean_text:
                discard_reason = "【純程序駁回】民事或刑事訴訟提起第三審未依法委任律師為代理人，程式不合法逕予駁回，欠缺實體法學爭點。"
            elif "未具體指摘" in clean_text:
                discard_reason = "【程序駁回】上訴理由僅就原審取捨證據為指摘，未具體表明原判決違背法令要件，上訴不合法駁回。真實實體法律爭點位於【原審實體判決】中。"
            elif "逾期" in clean_text and ("上訴" in clean_text or "抗告" in clean_text):
                discard_reason = "【純程序駁回】上訴或抗告已逾法定不變期間，程式不合法駁回，無實體爭點。"
            else:
                discard_reason = "【純程序駁回】本件裁判屬法定程式不合之形式駁回裁定，欠缺實體法律爭點論辯。"

    # 情境 B: 單純例行量刑或處分裁定
    elif is_routine_order:
        is_procedural = True
        discard_reason = "【例行性事實裁定】屬於通常定應執行刑、易科罰金或無法律爭議之通常裁量，通篇欠缺實體法條要件涵攝與爭鳴價值。"

    # 情境 C: 字數極短 (< 350 字) 且通篇為駁回或無實體條文
    elif len(clean_text) < 350 and ("駁回" in clean_text or "不合法" in clean_text) and not citations:
        is_procedural = True
        discard_reason = "【篇幅過短/欠缺爭點】內文字數過短且無實體法規論理，不具備法學實體爭點與 IRAC 實質分析價值。"

    # 綜合評分 (0 ~ 100)
    substantive_score = 80
    if is_procedural:
        substantive_score = 15 if history_instances else 5
    else:
        if has_substantive_terms:
            substantive_score += 15
        if len(citations) >= 2:
            substantive_score += 10
        if len(clean_text) > 1500:
            substantive_score += 10
        substantive_score = min(100, substantive_score)

    has_legal_issue = not is_procedural

    # 尋找承載真實爭點之歷審判決 (Substantive Prior Instance)
    substantive_prior = None
    if history_instances:
        for inst in history_instances:
            if "高等" in inst.get("court", "") or "第二審" in inst.get("role", "") or "原審" in inst.get("role", ""):
                substantive_prior = inst
                break
        if not substantive_prior:
            substantive_prior = history_instances[0]

    issue_density = "無 (純程序性裁判)" if not has_legal_issue else ("高 (具備多項核心實體法學爭點)" if substantive_score >= 85 else "中 (具備基礎爭點法理)")

    return {
        "has_legal_issue": has_legal_issue,
        "is_procedural_dismissal": is_procedural,
        "is_routine_factual_order": is_routine_order,
        "discard_reason": discard_reason,
        "substantive_score": substantive_score,
        "issue_density": issue_density,
        "extracted_history_instances": history_instances,
        "substantive_prior_instance": substantive_prior,
        "legal_citations_detected": citations
    }


def extract_instance_history(text: str, current_case_id: str = "") -> List[Dict[str, Any]]:
    """
    從裁判書內文或案號中，全自動萃取「歷審裁判案號」(Instance History Chain)：
    包括第一審 (地院)、第二審 (高院)、更審與第三審 (最高院)，以及大法庭/憲判字。
    """
    if not text or len(text.strip()) < 15:
        return []

    results = []
    seen_keys = set()
    clean_cur = re.sub(r'[\s\-_，,。號字第（）()]+', '', str(current_case_id)).lower()

    cur_year, cur_track, cur_no = "", "", ""
    if current_case_id:
        m_cur = re.search(r"([0-9]{1,3})\s*年度?\s*([^0-9\s，,。]{1,8}?)\s*字?\s*第?\s*([0-9]+)\s*號", str(current_case_id))
        if m_cur:
            cur_year, cur_track, cur_no = m_cur.group(1), m_cur.group(2).replace("字", "").replace("第", ""), m_cur.group(3)

    # 模式 A: 法院全名 + 年度 + 字軌 + 號數 + 判決/裁定
    pattern_standard = re.compile(
        rf'{COURT_NAME_PATTERN}[^\n\r]{{0,35}}?([0-9]{{1,3}})\s*年度?\s*([^0-9\s，,。]{{1,8}}?)\s*字?\s*第?\s*([0-9]+)\s*號\s*(判決|裁定)?'
    )
    for m in pattern_standard.finditer(text):
        court_raw = m.group(1).strip()
        year = m.group(2).strip()
        track = m.group(3).strip().replace("字", "").replace("第", "")
        no = m.group(4).strip()
        doc_type = m.group(5) or ("裁定" if "裁" in track else "判決")

        clean_match = f"{court_raw}{year}{track}{no}".lower()
        if clean_cur and (clean_match == clean_cur or clean_match in clean_cur or clean_cur in clean_match):
            continue
        if cur_year and cur_no and year == cur_year and no == cur_no and (track in cur_track or cur_track in track):
            continue
        if clean_match in seen_keys:
            continue

        seen_keys.add(clean_match)

        # 判定歷審審級角色
        role = _determine_instance_role(court_raw, track, doc_type, m.start(), text)
        action = _determine_instance_action(m.start(), text)

        full_cid = f"{court_raw} {year} 年度{track}字第 {no} 號{doc_type}"
        results.append({
            "case_id": full_cid,
            "court": court_raw,
            "year": year,
            "track": track,
            "no": no,
            "doc_type": doc_type,
            "role": role,
            "action": action,
            "snippet": text[max(0, m.start() - 40):min(len(text), m.end() + 60)].replace("\n", " ").strip()
        })

    # 模式 B: 括號中之案號，例如「原審判決（108年度上字第567號）」
    pattern_paren = re.compile(
        r'(原審|第一審|前審|二審|本院前次發回)[^\n\r]{0,25}?[（(]\s*([0-9]{1,3})\s*年度?\s*([^0-9\s，,。]{1,8}?)\s*字?\s*第?\s*([0-9]+)\s*號\s*[)）]'
    )
    for m in pattern_paren.finditer(text):
        ctx_word = m.group(1)
        year = m.group(2).strip()
        track = m.group(3).strip().replace("字", "").replace("第", "")
        no = m.group(4).strip()

        # 依字軌推導法院與書類
        court_inferred = "臺灣高等法院" if any(k in track for k in ["上", "重上", "抗"]) else "臺灣臺北地方法院"
        doc_type = "裁定" if "裁" in track or "抗" in track else "判決"
        clean_match = f"{court_inferred}{year}{track}{no}".lower()
        if clean_cur and clean_match == clean_cur:
            continue
        if clean_match in seen_keys:
            continue

        seen_keys.add(clean_match)
        role = "原審裁判 (第二審上訴審)" if "原審" in ctx_word else ("第一審裁判 (事實審)" if "第一審" in ctx_word else "歷審相關裁判")
        action = _determine_instance_action(m.start(), text)

        results.append({
            "case_id": f"{court_inferred} {year} 年度{track}字第 {no} 號{doc_type}",
            "court": court_inferred,
            "year": year,
            "track": track,
            "no": no,
            "doc_type": doc_type,
            "role": role,
            "action": action,
            "snippet": text[max(0, m.start() - 30):min(len(text), m.end() + 50)].replace("\n", " ").strip()
        })

    return results


def _determine_instance_role(court: str, track: str, doc_type: str, pos: int, text: str) -> str:
    """判定該案號於歷審脈絡鏈中之審級定位"""
    nearby_context = text[max(0, pos - 50):min(len(text), pos + 50)]
    if "更審" in nearby_context or "更一" in track or "更二" in track or "更" in track:
        return "更審裁判 (高等法院更審)"
    if "大法庭" in court or "大字" in track:
        return "大法庭終局定錨裁定"
    if "第一審" in nearby_context or "原起訴" in nearby_context:
        if "地方法院" in court or not any(k in track for k in ["上", "抗"]):
            return "第一審裁判 (事實審初審)"
    if "原審" in nearby_context or "第二審" in nearby_context:
        return "原審裁判 (上一審級/事實審)"
    if "最高" in court:
        return "第三審法律審裁判"
    if "高等" in court or any(k in track for k in ["上", "重上", "上易"]):
        return "第二審上訴審裁判"
    if "地方法院" in court or any(k in track for k in ["訴", "重訴", "易", "簡"]):
        return "第一審事實審裁判"
    return "歷審關聯裁判"


def _determine_instance_action(pos: int, text: str) -> str:
    """判定本案對該歷審裁判之審理處分結論"""
    nearby_context = text[max(0, pos - 100):min(len(text), pos + 200)]
    if re.search(r"原判決廢棄[，,\s]*發回", nearby_context) or "發回更審" in nearby_context:
        return "廢棄發回更審"
    if re.search(r"原判決廢棄[，,\s]*改判", nearby_context) or "自為改判" in nearby_context:
        return "廢棄自為改判"
    if "上訴駁回" in nearby_context or "維持原判" in nearby_context:
        return "維持原判 (駁回上訴)"
    if "抗告駁回" in nearby_context or "維持原裁定" in nearby_context:
        return "維持原裁定 (駁回抗告)"
    if "原處分撤銷" in nearby_context:
        return "撤銷原處分"
    return "審級審理中"


def format_instance_evolution_markdown(instances: List[Dict[str, Any]], current_case_id: str = "") -> str:
    """生成歷審裁判審級脈絡鏈 (Judgement History Pipeline) 之標準 Markdown 表格與流程圖"""
    if not instances:
        return "本裁判內文中未直接引述其他審級案號（可能為初審裁判或獨立終局審裁判）。"

    rows = []
    pipeline_parts = []

    for i, inst in enumerate(instances, 1):
        cid = inst.get("case_id", "")
        role = inst.get("role", "關聯審級")
        action = inst.get("action", "審理")
        court = inst.get("court", "")
        rows.append(f"| {i} | **{role}** | `{cid}` | {court} | :blue[{action}] |")
        pipeline_parts.append(f"【{role}：{cid[:18]}】")

    if current_case_id:
        pipeline_parts.append(f"🌟 **【當前研析：{current_case_id[:18]}】**")

    pipeline_str = " ➔ ".join(pipeline_parts)

    table_header = """
| 審級序 | 審級角色 | 歷審裁判案號 | 承審法院 | 裁判結果 / 審理關係 |
| :---: | :--- | :--- | :--- | :--- |
"""
    return f"#### 🌿 裁判審級更迭脈絡鏈 (Judgement History Pipeline)\n\n`{pipeline_str}`\n\n{table_header}\n" + "\n".join(rows) + "\n"
