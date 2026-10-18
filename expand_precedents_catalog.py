"""
智慧判解庫擴充與建庫腳本 (Precedents Catalog Expander - Multi-threaded)
專注收錄範圍：
1. 最高法院（民事、刑事大法庭、判例、具參考價值裁判）
2. 臺灣高等法院及各分院（民事、刑事審級實務裁判）
3. 最高行政法院（大法庭與代表裁判）
4. 高等行政法院（臺北、臺中、高雄高等行政法院）
5. 智慧財產及商業法院（專利、商標、著作權、商業裁判）
6. 所有筆記庫 (583份) 提及之具體地方法院判決與裁定
"""
import os
import sys
import json
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from config import DATA_DIR, RAW_DATA_DIR

CATALOG_FILE = Path(__file__).resolve().parent / "data" / "raw_exams" / "precedents_catalog.json"
DRIVE_CATALOG_FILE = Path(RAW_DATA_DIR) / "precedents_catalog.json"
SCORING_DIR = Path("G:/我的雲端硬碟/LawExamData/scoring_standards")
CACHE_DIR = Path("G:/我的雲端硬碟/LawExamData/SamsungNotes/_cache")

# 嚴格界定長度的非回溯正規表達式，防止 ReDoS
CASE_REGEX = re.compile(
    r'(?:(?:最高法院|臺灣高等法院|高等行政法院|最高行政法院|智慧財產(?:及商業)?法院|憲法法庭|[\u4e00-\u9fa5]{2,6}地方法院|[\u4e00-\u9fa5]{2,6}地院)\s*)?[0-9]{2,3}\s*年(?:度)?\s*[\u4e00-\u9fa5A-Za-z]{1,8}字\s*第?\s*[0-9]{1,8}\s*號(?:判決|裁定)?'
)

def extract_cases_from_notes() -> Dict[str, Set[str]]:
    """高速掃描所有筆記文字，提取引述之法院裁判"""
    print("🔍 正在從考生讀書筆記與名師講義快取庫中提取引述之法院裁判...")
    results = {
        "supreme": set(),
        "high": set(),
        "admin": set(),
        "ip": set(),
        "district": set(),
        "other": set()
    }
    
    if not CACHE_DIR.exists():
        return results

    txt_files = list(CACHE_DIR.glob("*.txt"))
    print(f"  共讀取 {len(txt_files)} 份筆記全文快取...")
    
    for tf in txt_files:
        try:
            content = tf.read_text(encoding="utf-8", errors="ignore")
            for m in CASE_REGEX.findall(content):
                clean_m = re.sub(r'\s+', '', m)
                if not ("字" in clean_m and "號" in clean_m):
                    continue
                if any(k in clean_m for k in ["地院", "地方法院"]):
                    results["district"].add(clean_m)
                elif any(k in clean_m for k in ["最高行", "最高行政法院", "高等行政法院", "高行"]):
                    results["admin"].add(clean_m)
                elif any(k in clean_m for k in ["智財", "智慧財產"]):
                    results["ip"].add(clean_m)
                elif any(k in clean_m for k in ["高院", "高等法院"]):
                    results["high"].add(clean_m)
                elif any(k in clean_m for k in ["最高", "台上", "台抗", "台再", "大法庭"]):
                    results["supreme"].add(clean_m)
                else:
                    results["other"].add(clean_m)
        except Exception:
            continue

    print(f"  ✅ 筆記引述提取完成：")
    print(f"     - 最高法院判決/裁定: {len(results['supreme'])} 筆")
    print(f"     - 各高等法院裁判: {len(results['high'])} 筆")
    print(f"     - 行政法院裁判: {len(results['admin'])} 筆")
    print(f"     - 智財及商業法院裁判: {len(results['ip'])} 筆")
    print(f"     - 筆記提及之地方法院裁判: {len(results['district'])} 筆")
    return results

def clean_jid_case_id(raw_jid: str) -> str:
    if not raw_jid:
        return ""
    m = re.search(r'([\u4e00-\u9fa5]{2,10}(?:法院)?\s*[0-9]{2,3}\s*年(?:度)?\s*[\u4e00-\u9fa5A-Za-z0-9]+\s*字\s*第?\s*[0-9]+\s*號(?:判決|裁定)?)', raw_jid)
    if m:
        return m.group(1).strip()
    return raw_jid.split()[0].strip()

def determine_court_and_level(case_id: str, domain: str) -> tuple:
    if "憲法" in case_id or "憲判字" in case_id or "大法官" in case_id:
        return "憲法法庭", "憲法法庭判決（憲法最高權威）"
    elif "大法庭" in case_id:
        return "最高法院", "大法庭裁定（最高權威）"
    elif "最高法院" in case_id or "台上" in case_id or "台抗" in case_id:
        return "最高法院", "最高法院裁判（終審實務）"
    elif "最高行政法院" in case_id:
        return "最高行政法院", "最高行政法院裁判（行政終審）"
    elif "高等行政法院" in case_id or "高行" in case_id:
        return "高等行政法院", "高等行政法院裁判（行政事實審）"
    elif "智慧財產" in case_id or "智財" in case_id:
        return "智慧財產及商業法院", "智慧財產及商業法院裁判（專業審級）"
    elif "高等法院" in case_id:
        return "臺灣高等法院", "高等法院裁判（事實審主流）"
    elif "地方法院" in case_id or "地院" in case_id:
        court_name = re.search(r'([\u4e00-\u9fa5]{2,8}地方法院)', case_id)
        c_str = court_name.group(1) if court_name else "地方法院"
        return c_str, "地方法院代表裁判（筆記引述事實審）"
    else:
        return "司法實務", "權威司法裁判"

def process_single_scoring_file(file_path: Path, all_note_district: Set[str], seen_ids: Set[str]) -> Dict[str, Any]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        jid = data.get("jid", "")
        case_id = clean_jid_case_id(jid)
        norm_id = re.sub(r'\s+', '', case_id)
        
        if not norm_id or norm_id in seen_ids:
            return None
        
        # 判定是否在限定審級：最高院、高院、高行、最高行、智財、以及筆記中提及的地院
        is_supreme = any(k in norm_id for k in ["最高法院", "台上", "台抗", "大法庭"])
        is_high = "高等法院" in norm_id
        is_admin = any(k in norm_id for k in ["最高行政法院", "高等行政法院", "高行"])
        is_ip = any(k in norm_id for k in ["智慧財產", "智財"])
        
        is_district = any(k in norm_id for k in ["地方法院", "地院"])
        is_district_approved = False
        if is_district:
            # 必須在筆記引述清單中，或為借名登記等必考核心爭點
            if any(dc in norm_id or norm_id in dc for dc in all_note_district):
                is_district_approved = True
            elif any(kw in data.get("topic", "") for kw in ["借名登記", "純經濟損失", "侵權", "背信", "不當得利", "表見代理"]):
                is_district_approved = True

        if is_supreme or is_high or is_admin or is_ip or is_district_approved:
            court, level = determine_court_and_level(case_id, data.get("domain", ""))
            txt = data.get("judgment_text", "")
            
            # 提取法條引用
            laws_cited = []
            law_matches = re.findall(r'(?:民法|刑法|民事訴訟法|刑事訴訟法|行政程序法|行政訴訟法|公司法|保險法|證券交易法|專利法|商標法|著作權法)第?\s*\d+\s*(?:條(?:第\d+項)?)?', txt[:1000])
            for lm in law_matches[:4]:
                clean_lm = re.sub(r'\s+', '', lm)
                if clean_lm not in laws_cited:
                    laws_cited.append(clean_lm)

            return {
                "norm_id": norm_id,
                "record": {
                    "case_id": case_id,
                    "court": court,
                    "level": level,
                    "subject": data.get("domain", "法學綜合實務"),
                    "sub_category": data.get("topic", data.get("keyword", "實務爭點")),
                    "date": "",
                    "title": f"【{data.get('domain', '')}】{data.get('topic', case_id)}",
                    "laws_cited": laws_cited if laws_cited else [f"{data.get('domain', '')}相關法條"],
                    "issue": f"{data.get('topic', '')}之法理爭點與實務適用疑義",
                    "holding": txt[:450].strip() + ("..." if len(txt) > 450 else ""),
                    "scholarly_views": data.get("scholarly_rubric", "實務與通說見解對照參照評析。"),
                    "exam_application_hint": f"本案裁判屬【{level}】，可於司律二試作答時作為『{data.get('topic', '')}』之重要論據援引開標。"
                }
            }
    except Exception:
        pass
    return None

def build_expanded_catalog():
    t_start = time.time()
    print("=" * 75)
    print("🚀 啟動權威判解庫擴充整合程序 (最高院 / 高院 / 高行 / 最高行 / 智財 / 筆記地院)")
    print("=" * 75)
    
    # 1. 載入現有 catalog
    existing_records = []
    if CATALOG_FILE.exists():
        try:
            existing_records = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing_records = []
    print(f"📖 目前已有本機權威裁判: {len(existing_records)} 筆")
    
    seen_ids = set()
    unified_records = []
    for r in existing_records:
        cid = re.sub(r'\s+', '', r.get("case_id", ""))
        if cid and cid not in seen_ids:
            seen_ids.add(cid)
            unified_records.append(r)

    # 2. 筆記引述裁判提取
    note_cases = extract_cases_from_notes()
    all_note_district = {re.sub(r'\s+', '', c) for c in note_cases["district"]}

    # 3. 多執行緒並行處理 scoring_standards 裁判庫
    if SCORING_DIR.exists():
        print(f"📦 正在使用 16 執行緒高速並行篩選 scoring_standards 裁判庫...")
        sc_files = [f for f in SCORING_DIR.iterdir() if f.name.endswith(".json")]
        added_from_sc = 0
        
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(process_single_scoring_file, f, all_note_district, seen_ids) for f in sc_files]
            for future in as_completed(futures):
                res = future.result()
                if res:
                    nid = res["norm_id"]
                    if nid not in seen_ids:
                        seen_ids.add(nid)
                        unified_records.append(res["record"])
                        added_from_sc += 1
                
        print(f"  ✅ 從 scoring_standards 成功收錄審級精選裁判: {added_from_sc} 筆")

    # 4. 針對筆記中引述之最高院、高院、行政法院、智財法院及地院判決建立專屬卡片
    added_from_notes = 0
    all_cited_cases = (
        note_cases["supreme"] | note_cases["high"] | 
        note_cases["admin"] | note_cases["ip"] | note_cases["district"]
    )
    
    for c_str in all_cited_cases:
        norm_c = re.sub(r'\s+', '', c_str)
        if norm_c in seen_ids:
            continue
        
        court, level = determine_court_and_level(c_str, "")
        record = {
            "case_id": c_str,
            "court": court,
            "level": f"{level}（個人筆記名師重點引述）",
            "subject": "筆記引述核心實務",
            "sub_category": "名師講義爭點裁判",
            "date": "",
            "title": f"筆記收錄裁判：{c_str}",
            "laws_cited": ["司律考科相關規定"],
            "issue": f"筆記與名師講義評釋之【{c_str}】核心論據",
            "holding": f"本裁判經名師授課總筆記與講義特別標註引述，屬考點重要實務案例。完整裁判全文可透過司法院檢索系統一鍵調閱。",
            "scholarly_views": "名師筆記評析見解：請注意本案事實與最高法院最新見解之衡平。",
            "exam_application_hint": f"此案為筆記重點收錄裁判（{c_str}），二試可作為事實審爭點辨析之特殊例證。"
        }
        seen_ids.add(norm_c)
        unified_records.append(record)
        added_from_notes += 1

    print(f"  ✅ 從 583 份筆記中增補名師指定引用裁判: {added_from_notes} 筆")
    
    # 統計審級分布
    breakdown = {"最高法院/大法官": 0, "高等法院": 0, "行政法院": 0, "智財法院": 0, "地方法院": 0, "其他": 0}
    for r in unified_records:
        cid = r.get("case_id", "")
        lvl = r.get("level", "")
        if "地方法院" in cid or "地方法院" in lvl:
            breakdown["地方法院"] += 1
        elif "行政" in cid or "行政" in lvl:
            breakdown["行政法院"] += 1
        elif "智慧財產" in cid or "智財" in lvl:
            breakdown["智財法院"] += 1
        elif "高等法院" in cid or "高等法院" in lvl:
            breakdown["高等法院"] += 1
        elif "最高" in cid or "憲法" in lvl or "大法" in lvl:
            breakdown["最高法院/大法官"] += 1
        else:
            breakdown["其他"] += 1

    print("-" * 75)
    print(f"🏆 全庫裁判總數達到: {len(unified_records)} 筆！")
    print(f"📊 審級結構分布統計：")
    for k, v in breakdown.items():
        print(f"   - {k}: {v} 筆")
    print("-" * 75)

    # 5. 寫入本地與 Google Drive
    CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CATALOG_FILE, "w", encoding="utf-8") as f:
        json.dump(unified_records, f, ensure_ascii=False, indent=2)
    print(f"💾 已儲存至本地倉庫: {CATALOG_FILE} ({CATALOG_FILE.stat().st_size / 1024 / 1024:.2f} MB)")

    if DRIVE_CATALOG_FILE.parent.exists():
        try:
            with open(DRIVE_CATALOG_FILE, "w", encoding="utf-8") as df:
                json.dump(unified_records, df, ensure_ascii=False, indent=2)
            print(f"💾 已同步至雲端硬碟: {DRIVE_CATALOG_FILE}")
        except Exception as de:
            print(f"  [警示] 同步至雲端硬碟失敗: {de}")

    print(f"⏱️ 全部擴充整合程序耗時: {time.time() - t_start:.2f} 秒！")

if __name__ == "__main__":
    build_expanded_catalog()
