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
    """讀取所有社群考生上傳收藏之講義筆記"""
    init_community_archives()
    try:
        if NOTES_CATALOG_FILE.exists():
            with open(NOTES_CATALOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
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

    record = {
        "question_id": q_id,
        "title": clean_title,
        "content": content.strip(),
        "subject": subject or "跨領域綜合",
        "rubric": rubric.strip() if rubric else "",
        "uploader": uploader,
        "source": source,
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "word_count": len(content.strip())
    }

    # 1. 寫入獨立收藏檔案 (供備份與後續下載)
    q_file_path = QUESTIONS_DIR / f"{q_id}.json"
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
    
    safe_name = re.sub(r'[\\/*?:"<>|]', '_', filename)
    archive_filename = f"{subject}_{safe_name}_{timestamp_str}.pdf" if not safe_name.lower().endswith(".pdf") else f"{subject}_{safe_name[:-4]}_{timestamp_str}.pdf"
    
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
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S")
    }

    # 2. 追加至社群筆記總表
    notes_catalog = load_community_notes()
    notes_catalog.insert(0, record)
    try:
        with open(NOTES_CATALOG_FILE, "w", encoding="utf-8") as f:
            json.dump(notes_catalog, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to update community notes catalog: {e}")

    # 3. 實時注入六法標註 metadata (六法即刻可查閱)
    meta_path = Path(DATA_DIR) / "national_laws" / "six_codes_annotated_metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            
            nc = meta.get("notes_catalog", {})
            if subject not in nc:
                nc[subject] = []
            
            # 加入前排
            nc[subject].insert(0, {
                "filename": archive_filename,
                "size_kb": size_kb,
                "path": str(target_path),
                "is_community_upload": True
            })
            meta["notes_catalog"] = nc
            
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to inject into six codes metadata: {e}")

    return record

def search_community_questions(subject: str = "全部科目", keyword: str = "") -> List[Dict[str, Any]]:
    """篩選檢索社群題目"""
    questions = load_community_questions()
    results = []
    for q in questions:
        if subject != "全部科目" and subject != "跨領域綜合":
            if q.get("subject") != subject and subject not in q.get("subject", ""):
                continue
        if keyword:
            kw = keyword.strip()
            if kw not in q.get("title", "") and kw not in q.get("content", "") and kw not in q.get("subject", ""):
                continue
        results.append(q)
    return results

def search_community_notes(subject: str = "全部科目", keyword: str = "") -> List[Dict[str, Any]]:
    """篩選檢索社群筆記"""
    notes = load_community_notes()
    results = []
    for n in notes:
        if subject != "全部科目":
            if n.get("subject") != subject and subject not in n.get("subject", ""):
                continue
        if keyword:
            kw = keyword.strip()
            if kw not in n.get("filename", "") and kw not in n.get("original_name", "") and kw not in n.get("summary", ""):
                continue
        results.append(n)
    return results
