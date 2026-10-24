"""
社群考生共享題庫、講義與筆記實時典藏引擎 (Community Archive Engine)
實作功能：
1. 使用者上傳之所有題目（試卷/真題/手寫題），自動新建獨立檔案收藏至社群題庫，並實時連動至 App。
2. 使用者上傳之所有講義與筆記（手寫/PDF/Word），自動新建獨立檔案收藏至社群筆記庫，並實時注入六法條文註記與筆記大庫。
3. 支援跨考科分類檢索、即時匯入作答、一鍵命題與二試評分聯動。
"""
import os
import sys
import json
import time
import uuid
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from config import DATA_DIR, GOOGLE_DRIVE_DATA_DIR, RAW_DATA_DIR

ARCHIVE_BASE_DIR = Path(DATA_DIR) / "community_archives"
QUESTIONS_DIR = ARCHIVE_BASE_DIR / "questions"
NOTES_DIR = ARCHIVE_BASE_DIR / "notes"
MCQS_DIR = ARCHIVE_BASE_DIR / "mcqs"

QUESTIONS_CATALOG_FILE = ARCHIVE_BASE_DIR / "community_questions_catalog.json"
NOTES_CATALOG_FILE = ARCHIVE_BASE_DIR / "community_notes_catalog.json"
MCQS_CATALOG_FILE = ARCHIVE_BASE_DIR / "community_mcqs_catalog.json"

def init_community_archives():
    """初始化社群典藏庫目錄與清單檔案"""
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    MCQS_DIR.mkdir(parents=True, exist_ok=True)

    if not QUESTIONS_CATALOG_FILE.exists():
        with open(QUESTIONS_CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

    if not NOTES_CATALOG_FILE.exists():
        with open(NOTES_CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

    if not MCQS_CATALOG_FILE.exists():
        with open(MCQS_CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

init_community_archives()

def load_community_questions() -> List[Dict[str, Any]]:
    """讀取所有社群考生上傳收藏之試題"""
    init_community_archives()
    try:
        if QUESTIONS_CATALOG_FILE.exists():
            with open(QUESTIONS_CATALOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return []
    return []

def load_community_notes() -> List[Dict[str, Any]]:
    """讀取所有社群考生上傳收藏之講義筆記（自動過濾 0 KB 測試廢棄檔）"""
    init_community_archives()
    try:
        if NOTES_CATALOG_FILE.exists():
            with open(NOTES_CATALOG_FILE, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
                cleaned = [
                    item for item in raw_list
                    if float(item.get("size_kb", 0.0) or 0.0) > 0.0
                    and "test_note" not in str(item.get("filename", "")).lower()
                    and "test_note" not in str(item.get("original_name", "")).lower()
                ]
                return cleaned
    except Exception:
        return []
    return []

def archive_uploaded_question(
    title: str,
    content: str,
    subject: str = "跨領域綜合",
    rubric: str = "",
    uploader: str = "考生共享",
    source: str = "使用者上傳"
) -> Dict[str, Any]:
    """
    實時新建檔案收藏使用者上傳的試題，並即時納入社群題庫供後人使用。
    """
    init_community_archives()
    if not content or len(content.strip()) < 5:
        return {}

    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    q_id = f"q_{uuid.uuid4().hex[:8]}_{timestamp_str}"

    clean_title = title.strip() if title else ""
    if not clean_title or clean_title == "未命名題目":
        first_line = content.strip().splitlines()[0]
        clean_title = first_line[:30] + ("..." if len(first_line) > 30 else "")

    q_file_path = QUESTIONS_DIR / f"{q_id}.json"
    record = {
        "question_id": q_id,
        "title": clean_title,
        "content": content.strip(),
        "subject": subject or "跨領域綜合",
        "rubric": rubric.strip() if rubric else "",
        "uploader": uploader,
        "source": source,
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "uploaded_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "word_count": len(content.strip()),
        "path": str(q_file_path),
        "file_path": str(q_file_path)
    }

    # 1. 寫入獨立收藏檔案 (供備份與後續下載)
    try:
        with open(q_file_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to write single question file: {e}")

    # 2. 追加至社群總題庫索引
    catalog = load_community_questions()
    # 避免完全相同內容重複寫入
    if not any(c.get("content") == record["content"] for c in catalog):
        catalog.insert(0, record)
        try:
            with open(QUESTIONS_CATALOG_FILE, "w", encoding="utf-8") as f:
                json.dump(catalog, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to update questions catalog: {e}")

    return record

def archive_uploaded_note(
    file_bytes: bytes,
    filename: str,
    subject: str = "民法",
    summary: str = "",
    uploader: str = "社群考生"
) -> Dict[str, Any]:
    """
    實時新建檔案收藏使用者上傳的講義筆記，並即時注入六法標註與全民共享大庫。
    """
    init_community_archives()
    if not file_bytes:
        return {}

    now = datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    note_id = f"n_{uuid.uuid4().hex[:8]}_{timestamp_str}"

    orig_ext = Path(filename).suffix.lower()
    if not orig_ext:
        orig_ext = ".pdf"
    stem_name = Path(filename).stem
    safe_stem = re.sub(r'[\\/*?:"<>|]', '_', stem_name)
    archive_filename = f"{subject}_{safe_stem}_{timestamp_str}{orig_ext}"

    target_path = NOTES_DIR / archive_filename

    # 1. 保存獨立二進位筆記檔案
    try:
        with open(target_path, "wb") as f:
            f.write(file_bytes)
    except Exception as e:
        print(f"Failed to save archived note file: {e}")
        return {}

    size_kb = round(len(file_bytes) / 1024, 1)

    record = {
        "note_id": note_id,
        "filename": archive_filename,
        "original_name": filename,
        "subject": subject,
        "size_kb": size_kb,
        "summary": summary,
        "uploader": uploader,
        "path": str(target_path),
        "file_path": str(target_path),
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "uploaded_at": now.strftime("%Y-%m-%d %H:%M:%S")
    }

    # 2. 追加至社群筆記總表 (輕量快速寫入，嚴格禁止阻塞覆寫 69MB 六法 metadata)
    notes_catalog = load_community_notes()
    notes_catalog.insert(0, record)
    try:
        with open(NOTES_CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump(notes_catalog, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to update community notes catalog: {e}")

    return record

def search_community_questions(
    subject_or_kw: str = "全部科目",
    kw_or_subject: str = "",
    subject: Optional[str] = None,
    keyword: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    篩選檢索社群題目，全方位相容 search_community_questions(cq_kw) 與 (subject, keyword) 調用方式
    """
    common_subjects = {"民法", "民事訴訟法", "刑法", "刑事訴訟法", "行政法", "憲法", "公司法", "證券交易法", "保險法", "智慧財產權法", "勞動與社會法", "勞動法", "公法", "商事法", "全部科目", "跨領域綜合"}
    if subject is None:
        if subject_or_kw in common_subjects:
            subject = subject_or_kw
            keyword = kw_or_subject if keyword is None else keyword
        else:
            if not kw_or_subject and keyword is None:
                keyword = subject_or_kw
                subject = "全部科目"
            else:
                subject = subject_or_kw
                keyword = kw_or_subject if keyword is None else keyword
    if keyword is None:
        keyword = kw_or_subject

    questions = load_community_questions()
    results = []
    for q in questions:
        if subject and subject not in ["全部科目", "跨領域綜合"]:
            if q.get("subject") != subject and subject not in q.get("subject", ""):
                continue
        if keyword:
            kw = keyword.strip()
            if kw and (kw not in q.get("title", "") and kw not in q.get("content", "") and kw not in q.get("subject", "")):
                continue
        results.append(q)
    return results

def search_community_notes(
    subject_or_kw: str = "全部科目",
    kw_or_subject: str = "",
    subject: Optional[str] = None,
    keyword: Optional[str] = None
) -> List[Dict[str, Any]]:
    """篩選檢索社群筆記，全方位相容 (keyword) 與 (subject, keyword) 調用方式"""
    common_subjects = {"民法", "民事訴訟法", "刑法", "刑事訴訟法", "行政法", "憲法", "公司法", "證券交易法", "保險法", "智慧財產權法", "勞動與社會法", "勞動法", "公法", "商事法", "全部科目"}
    if subject is None:
        if subject_or_kw in common_subjects:
            subject = subject_or_kw
            keyword = kw_or_subject if keyword is None else keyword
        else:
            if not kw_or_subject and keyword is None:
                keyword = subject_or_kw
                subject = "全部科目"
            else:
                subject = subject_or_kw
                keyword = kw_or_subject if keyword is None else keyword
    if keyword is None:
        keyword = kw_or_subject

    notes = load_community_notes()
    results = []
    for n in notes:
        if subject and subject != "全部科目":
            if n.get("subject") != subject and subject not in n.get("subject", ""):
                continue
        if keyword:
            kw = keyword.strip()
            if kw and (kw not in n.get("filename", "") and kw not in n.get("original_name", "") and kw not in n.get("summary", "")):
                continue
        results.append(n)
    return results


def get_major_domain_for_subject(subject: str) -> str:
    """自動對應考科至一試四大/專題法學領域"""
    sub = (subject or "").strip()
    if any(k in sub for k in ["民法", "民訴", "家事", "非訟"]):
        return "民法與民事訴訟法"
    if any(k in sub for k in ["刑法", "刑訴", "保安處分"]):
        return "刑法與刑事訴訟法"
    if any(k in sub for k in ["憲法", "行政法", "行政訴訟", "國家賠償"]):
        return "憲法與行政法"
    if any(k in sub for k in ["商事", "公司", "證券", "證交", "保險", "票據", "海商"]):
        return "商事法與綜合領域"
    if any(k in sub for k in ["智慧財產", "專利", "商標", "著作", "營業秘密"]):
        return "智慧財產權法"
    if any(k in sub for k in ["勞動", "勞基", "工會", "社會", "勞工"]):
        return "勞動法與社會法"
    if any(k in sub for k in ["強制執行"]):
        return "強制執行法與家事事件法"
    if any(k in sub for k in ["國際私法", "國私"]):
        return "國際私法與選試領域"
    return "綜合領域"


def get_stage1_bank_filepaths() -> List[Path]:
    """獲取一試跨科題庫可能的所有存檔實體路徑（包含雲端根目錄與本機 repo）"""
    candidates = [
        Path(RAW_DATA_DIR) / "stage1_multi_subject_mcq_bank.json",
        Path(__file__).resolve().parent.parent / "data" / "raw_exams" / "stage1_multi_subject_mcq_bank.json",
        Path(__file__).resolve().parent.parent.parent / "raw_exams" / "stage1_multi_subject_mcq_bank.json"
    ]
    seen = set()
    result = []
    for c in candidates:
        norm = str(c.resolve()) if c.exists() else str(c)
        if norm not in seen:
            seen.add(norm)
            result.append(c)
    return result


def load_stage1_bank_questions() -> List[Dict[str, Any]]:
    """自磁碟載入當前跨科一試題庫檔案"""
    for p in get_stage1_bank_filepaths():
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
            except Exception:
                pass
    return []


def parse_raw_mcq_text(text: str, default_subject: str = "民法") -> List[Dict[str, Any]]:
    """
    智慧長文貼入正則解析引擎：
    支援單題或多題（以題號、空行或第X題分隔），自動萃取：
    - 題幹情境案件事實
    - 四大選項 (A)(B)(C)(D)
    - 正確解答 (A/B/C/D)
    - 詳解與法條爭點說明
    """
    if not text or not text.strip():
        return []

    clean_text = text.strip()

    # 切分多題：匹配題號開頭 (例如 1. 或 第1題 或 (1))
    split_pattern = r'(?=(?:^|\n)\s*(?:第\s*\d+\s*題[\s:：、.]*|\d+[\.、:：\s]+|\(\d+\)\s*))'
    raw_blocks = re.split(split_pattern, clean_text)
    blocks = [b.strip() for b in raw_blocks if b.strip()]

    # 若無法由題號切分但含有多個 (A)，嘗試以空行段落切分
    if len(blocks) <= 1 and clean_text.count('(A)') > 1:
        parts = clean_text.split('\n\n')
        if len(parts) > 1:
            blocks = [p.strip() for p in parts if p.strip()]

    parsed_questions = []

    for blk in blocks:
        # 尋找選項 A 的位置
        m_a = re.search(r'(?:^|\n|\s)(?:\(|\[)?A(?:\)|\]|\.|\、|\:|\s)\s*', blk)
        if not m_a:
            continue

        raw_q = blk[:m_a.start()].strip()
        # 清除開頭題號
        raw_q = re.sub(r'^(?:第\s*\d+\s*題[\s:：、.]*|\d+[\.、:：\s]+|\(\d+\)\s*)', '', raw_q).strip()

        # 擷取答案
        ans_m = re.search(r'(?:【?\s*(?:正確)?(?:答案|解答|解答為|Ans|Answer)\s*】?[：:\s]*\(?([A-D])\)?)', blk, re.I)
        answer = ans_m.group(1).upper() if ans_m else "A"

        # 擷取詳解說明
        exp_m = re.search(r'(?:【?\s*(?:解析|說明|理由|詳解|說明與法條)\s*】?[：:\s]*)(.*)', blk, re.I | re.DOTALL)
        explanation = exp_m.group(1).strip() if exp_m else ""

        # 截取選項區塊
        opts_str = blk[m_a.start():]
        if exp_m and exp_m.start() > m_a.start():
            opts_str = blk[m_a.start():exp_m.start()]
        elif ans_m and ans_m.start() > m_a.start():
            opts_str = blk[m_a.start():ans_m.start()]

        options = {}
        opt_matches = list(re.finditer(r'(?:^|\n|\s)(?:\(|\[)?([A-D])(?:\)|\]|\.|\、|\:|\s)\s*', opts_str))
        for i, om in enumerate(opt_matches):
            char = om.group(1).upper()
            start_i = om.end()
            end_i = opt_matches[i+1].start() if i + 1 < len(opt_matches) else len(opts_str)
            opt_body = opts_str[start_i:end_i].strip()
            # 若為 D 選項，清除末尾可能殘留的答案字樣
            if char == 'D':
                opt_body = re.sub(r'(?:【?\s*(?:正確)?(?:答案|解答|解答為|Ans|Answer)\s*】?[：:\s]*\(?[A-D]\)?).*', '', opt_body, flags=re.I|re.DOTALL).strip()
            options[char] = opt_body

        if raw_q and len(options) >= 2:
            # 補齊缺少選項防呆
            for needed in ["A", "B", "C", "D"]:
                if needed not in options:
                    options[needed] = f"選項 ({needed}) 內容"

            domain = get_major_domain_for_subject(default_subject)
            parsed_questions.append({
                "subject": default_subject,
                "major_domain": domain,
                "category": f"{default_subject}實務與法規核心考點",
                "question": raw_q,
                "options": options,
                "answer": answer,
                "explanation": explanation or f"【解析】：本題正確答案為 ({answer})。"
            })

    return parsed_questions


def archive_stage1_mcq(
    question: str,
    options: Dict[str, str],
    answer: str,
    subject: str = "民法",
    major_domain: Optional[str] = None,
    category: str = "",
    explanation: str = "",
    core_issue: str = "",
    legal_references: Optional[List[str]] = None,
    uploader: str = "考生手動新增"
) -> Dict[str, Any]:
    """
    單題持久化收錄至跨科一試題庫 JSON 檔案中，並同步儲存獨立 JSON 單檔。
    """
    clean_q = (question or "").strip()
    if not clean_q or len(clean_q) < 5:
        return {"success": False, "error": "題幹內容過短或為空"}

    clean_ans = (answer or "A").strip().upper()
    if clean_ans not in ["A", "B", "C", "D"]:
        clean_ans = "A"

    domain = major_domain or get_major_domain_for_subject(subject)
    clean_cat = (category or "").strip() or f"{subject}重點爭點"

    new_item = {
        "subject": subject,
        "major_domain": domain,
        "category": clean_cat,
        "question": clean_q,
        "options": {
            "A": options.get("A", "").strip(),
            "B": options.get("B", "").strip(),
            "C": options.get("C", "").strip(),
            "D": options.get("D", "").strip()
        },
        "answer": clean_ans,
        "explanation": (explanation or "").strip() or f"【解析】：本題正確答案為 ({clean_ans})。",
        "uploader": uploader,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    if core_issue:
        new_item["core_issue"] = core_issue.strip()
    if legal_references:
        new_item["legal_references"] = legal_references

    res = batch_archive_stage1_mcqs([new_item], default_subject=subject)
    return res


def batch_archive_stage1_mcqs(
    mcqs: List[Dict[str, Any]],
    default_subject: str = "民法"
) -> Dict[str, Any]:
    """
    批次將多筆選擇題持久化收錄至磁碟題庫檔案，自動去除重複試題並更新題號。
    """
    init_community_archives()
    if not mcqs:
        return {"success": False, "error": "無任何有效題目可收錄", "added": 0}

    # 讀取現有所有題目
    existing = load_stage1_bank_questions()
    seen_hashes = set()
    for q in existing:
        q_txt = q.get("question", "")[:40]
        opt_a = q.get("options", {}).get("A", "")[:15] if isinstance(q.get("options"), dict) else ""
        seen_hashes.add(f"{q_txt}_{opt_a}")

    added_items = []
    skipped_duplicates = 0

    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    for raw_m in mcqs:
        q_text = raw_m.get("question", "").strip()
        if not q_text:
            continue

        opts = raw_m.get("options", {})
        if not isinstance(opts, dict):
            opts = {"A": "選項A", "B": "選項B", "C": "選項C", "D": "選項D"}
        for k in ["A", "B", "C", "D"]:
            if k not in opts:
                opts[k] = ""

        h = f"{q_text[:40]}_{opts.get('A', '')[:15]}"
        if h in seen_hashes:
            skipped_duplicates += 1
            continue

        seen_hashes.add(h)
        sub = raw_m.get("subject", default_subject)
        domain = raw_m.get("major_domain") or get_major_domain_for_subject(sub)
        ans = (raw_m.get("answer") or "A").strip().upper()
        if ans not in ["A", "B", "C", "D"]:
            ans = "A"

        q_item = {
            "question_no": len(existing) + len(added_items) + 1,
            "subject": sub,
            "major_domain": domain,
            "category": raw_m.get("category", f"{sub}核心爭點與實務見解"),
            "question": q_text,
            "options": opts,
            "answer": ans,
            "explanation": raw_m.get("explanation", f"【解析】：本題正確解答為 ({ans})。")
        }
        if "core_issue" in raw_m and raw_m["core_issue"]:
            q_item["core_issue"] = raw_m["core_issue"]
        if "legal_references" in raw_m and raw_m["legal_references"]:
            q_item["legal_references"] = raw_m["legal_references"]

        added_items.append(q_item)

        # 儲存一份獨立 JSON 典藏檔案至 community_archives/mcqs
        try:
            single_id = f"mcq_{uuid.uuid4().hex[:8]}_{now_str}"
            single_path = MCQS_DIR / f"{single_id}.json"
            with open(single_path, "w", encoding="utf-8") as sf:
                json.dump(q_item, sf, ensure_ascii=False, indent=2)
        except Exception:
            pass

    if not added_items:
        return {
            "success": True,
            "added": 0,
            "skipped_duplicates": skipped_duplicates,
            "total_now": len(existing),
            "message": f"題目皆已存在於題庫中（略過 {skipped_duplicates} 筆重複題目）。"
        }

    # 合併現有題庫
    all_combined = existing + added_items
    for idx, q in enumerate(all_combined, 1):
        q["question_no"] = idx

    # 寫入所有目標路徑（Google Drive 根目錄與本機 repo 鏡像）
    target_paths = get_stage1_bank_filepaths()
    written_paths = []
    for tp in target_paths:
        try:
            tp.parent.mkdir(parents=True, exist_ok=True)
            with open(tp, "w", encoding="utf-8") as f:
                json.dump(all_combined, f, ensure_ascii=False, indent=2)
            written_paths.append(str(tp))
        except Exception as e:
            print(f"Error writing MCQ bank to {tp}: {e}")

    # 同步追加更新社群 MCQ 總索引
    try:
        if MCQS_CATALOG_FILE.exists():
            with open(MCQS_CATALOG_FILE, "r", encoding="utf-8") as mf:
                mcq_cat = json.load(mf)
        else:
            mcq_cat = []
        mcq_cat.extend(added_items)
        with open(MCQS_CATALOG_FILE, "w", encoding="utf-8") as mf:
            json.dump(mcq_cat, mf, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return {
        "success": True,
        "added": len(added_items),
        "skipped_duplicates": skipped_duplicates,
        "total_now": len(all_combined),
        "written_paths": written_paths,
        "items": added_items
    }

