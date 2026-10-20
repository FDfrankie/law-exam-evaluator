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

from config import DATA_DIR, GOOGLE_DRIVE_DATA_DIR

ARCHIVE_BASE_DIR = Path(DATA_DIR) / "community_archives"
QUESTIONS_DIR = ARCHIVE_BASE_DIR / "questions"
NOTES_DIR = ARCHIVE_BASE_DIR / "notes"

QUESTIONS_CATALOG_FILE = ARCHIVE_BASE_DIR / "community_questions_catalog.json"
NOTES_CATALOG_FILE = ARCHIVE_BASE_DIR / "community_notes_catalog.json"

def init_community_archives():
    """初始化社群典藏庫目錄與清單檔案"""
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    if not QUESTIONS_CATALOG_FILE.exists():
        with open(QUESTIONS_CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

    if not NOTES_CATALOG_FILE.exists():
        with open(NOTES_CATALOG_FILE, "w", encoding="utf-8") as f:
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
