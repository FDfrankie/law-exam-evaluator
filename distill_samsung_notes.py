# -*- coding: utf-8 -*-
"""
Samsung Notes 全量法學手寫筆記批次 OCR 蒸餾與資料庫固化管線
=======================================================
功能：
1. 建立並同步 data/judicial_authority.db 之 user_notes 與 user_notes_fts 資料表。
2. 遍歷 data/SamsungNotes/ 全數筆記與講義（PDF/圖像/Word/TXT）：
   - 具數位文字層者：秒級無失真抽取完整文字
   - 純手寫掃描者：調用 Gemini 多模態神經網路執行高精確繁體中文手寫法學 OCR
3. 將成果多重固化：
   - 本機硬碟快取：data/SamsungNotes/_cache/{filename}.txt
   - 本機 SQLite 資料庫：user_notes 與 FTS5 全文索引
   - 雲端同步輕量檔：data/samsung_notes_cache.json（供 Streamlit Cloud 離線秒讀）
   - 更新 drive_notes_manifest.json 確保前端標記為「⚡已快取」
"""

import os
import sys
import time
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

# 終端輸出編碼保護
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

try:
    from PIL import Image
except ImportError:
    Image = None

from config import DATA_DIR, SAMSUNG_NOTES_DIR, PROJECT_ROOT
from doc_parser import ocr_handwritten_images
from ingest_user_notes_to_sft import (
    render_pdf_to_images,
    classify_document_nature,
    get_google_drive_notes_list,
    sync_all_drive_notes_to_samsung_notes
)

DB_PATH = DATA_DIR / "judicial_authority.db"
CACHE_DIR = SAMSUNG_NOTES_DIR / "_cache"
CLOUD_CACHE_JSON = DATA_DIR / "samsung_notes_cache.json"


def init_user_notes_db():
    """初始化 user_notes 與 FTS5 全文檢索表"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_notes (
            note_id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            subject TEXT,
            author TEXT,
            page_count INTEGER DEFAULT 1,
            size_mb REAL DEFAULT 0.0,
            extracted_text TEXT,
            summary TEXT,
            has_ocr INTEGER DEFAULT 0,
            updated_at TEXT
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_unotes_sub ON user_notes(subject);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_unotes_fn ON user_notes(filename);")

    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS user_notes_fts USING fts5(
            note_id UNINDEXED,
            filename,
            subject,
            extracted_text,
            summary,
            tokenize='unicode61'
        );
    """)
    conn.commit()
    conn.close()


def save_note_to_db(rec: Dict[str, Any]):
    """寫入單筆筆記至 SQLite 與 FTS5"""
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO user_notes (
            note_id, filename, subject, author, page_count, size_mb,
            extracted_text, summary, has_ocr, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        rec["note_id"], rec["filename"], rec["subject"], rec.get("author", ""),
        rec.get("page_count", 1), rec.get("size_mb", 0.0),
        rec["extracted_text"], rec.get("summary", ""),
        rec.get("has_ocr", 0), datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    # 更新 FTS
    try:
        cur.execute("DELETE FROM user_notes_fts WHERE note_id = ?", (rec["note_id"],))
        cur.execute("""
            INSERT INTO user_notes_fts (note_id, filename, subject, extracted_text, summary)
            VALUES (?, ?, ?, ?, ?)
        """, (rec["note_id"], rec["filename"], rec["subject"], rec["extracted_text"], rec.get("summary", "")))
    except Exception:
        pass

    conn.commit()
    conn.close()


def get_existing_db_notes() -> Dict[str, str]:
    """獲取資料庫已存在的筆記文字"""
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    cur = conn.cursor()
    try:
        cur.execute("SELECT filename, extracted_text FROM user_notes WHERE length(extracted_text) > 50")
        rows = cur.fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def extract_single_note(file_path: Path, max_pages: int = 15, force_ocr: bool = False) -> Dict[str, Any]:
    """
    對單一筆記抽取文字：
    1. 數位 PDF 文字層優先抽取（超高速）
    2. 若純掃描/無文字層，調用 Gemini 多模態執行手寫法學 OCR
    """
    ext = file_path.suffix.lower()
    stem = file_path.stem
    subject = stem.split("_")[0] if "_" in stem else "其他"
    size_mb = round(file_path.stat().st_size / (1024 * 1024), 2)
    page_count = 1
    has_ocr = 0
    extracted_text = ""

    if ext == ".pdf":
        if pdfium:
            try:
                doc = pdfium.PdfDocument(file_path)
                page_count = len(doc)
                pages_to_read = min(page_count, max_pages)
                extracted_pages = []

                for i in range(pages_to_read):
                    t = doc[i].get_textpage().get_text_range().strip()
                    if t:
                        extracted_pages.append(f"--- [第 {i+1} 頁] ---\n" + t)

                digital_text = "\n\n".join(extracted_pages).strip()

                if len(digital_text) > 100 and not force_ocr:
                    extracted_text = digital_text
                else:
                    # 純手寫掃描，執行多模態 OCR
                    imgs = render_pdf_to_images(file_path, max_pages=pages_to_read)
                    if imgs:
                        print(f"    [啟動多模態手寫 OCR] 筆記《{file_path.name}》共 {len(imgs)} 頁...")
                        ocr_res = ocr_handwritten_images(imgs, prompt_hint=f"考科：{subject}，筆記主旨：{stem}")
                        if ocr_res and not ocr_res.startswith("["):
                            extracted_text = ocr_res
                            has_ocr = 1
                        elif digital_text:
                            extracted_text = digital_text
            except Exception as e:
                print(f"    [!] PDF 解析異常 {file_path.name}: {e}")

    elif ext in [".png", ".jpg", ".jpeg", ".webp"]:
        if Image:
            try:
                img = Image.open(file_path)
                ocr_res = ocr_handwritten_images([img], prompt_hint=f"考科：{subject}，手寫圖檔：{stem}")
                if ocr_res and not ocr_res.startswith("["):
                    extracted_text = ocr_res
                    has_ocr = 1
            except Exception as e:
                print(f"    [!] 圖片 OCR 異常 {file_path.name}: {e}")

    elif ext in [".txt", ".md"]:
        try:
            extracted_text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    return {
        "note_id": file_path.name,
        "filename": file_path.name,
        "subject": subject,
        "author": "",
        "page_count": page_count,
        "size_mb": size_mb,
        "extracted_text": extracted_text,
        "summary": extracted_text[:300] if extracted_text else "",
        "has_ocr": has_ocr
    }


def run_batch_distillation(max_ocr_items: Optional[int] = None, force_refresh: bool = False):
    """執行 Samsung Notes 全量批次抽取、OCR 蒸餾與多端固化"""
    print("=" * 70)
    print("🚀 啟動 Samsung Notes 全量筆記批次 OCR 萃取與資料庫固化管線")
    print(f"📂 筆記來源目錄: {SAMSUNG_NOTES_DIR}")
    print(f"💾 固化資料庫: {DB_PATH}")
    print("=" * 70)

    init_user_notes_db()
    existing_in_db = get_existing_db_notes()
    print(f"[*] 目前資料庫已收錄 {len(existing_in_db)} 份有效筆記內文。")

    valid_exts = {".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp"}
    files = sorted([
        f for f in SAMSUNG_NOTES_DIR.glob("*")
        if f.is_file() and f.suffix.lower() in valid_exts and f.name != "desktop.ini" and not f.name.startswith(".")
    ])

    print(f"[*] 掃描到 {len(files)} 份 Samsung Notes 本地筆記。")

    cloud_cache_dict = {}
    if CLOUD_CACHE_JSON.exists():
        try:
            with open(CLOUD_CACHE_JSON, "r", encoding="utf-8") as f:
                cloud_cache_dict = json.load(f)
        except Exception:
            pass

    ocr_count = 0
    digital_count = 0
    skipped_count = 0

    for idx, f in enumerate(files, 1):
        # 檢查是否已具備快取且長度足夠
        cache_file = CACHE_DIR / f"{f.name}.txt"
        cached_text = ""
        if not force_refresh:
            if cache_file.exists() and cache_file.stat().st_size > 50:
                try:
                    cached_text = cache_file.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    pass
            elif f.name in existing_in_db:
                cached_text = existing_in_db[f.name]

        if cached_text:
            skipped_count += 1
            rec = {
                "note_id": f.name,
                "filename": f.name,
                "subject": f.name.split("_")[0] if "_" in f.name else "其他",
                "extracted_text": cached_text,
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                "summary": cached_text[:300]
            }
            save_note_to_db(rec)
            cloud_cache_dict[f.name] = {
                "subject": rec["subject"],
                "text": cached_text,
                "size_mb": rec["size_mb"]
            }
            if idx % 20 == 0:
                print(f"  [{idx}/{len(files)}] [已快取秒載] 《{f.name[:30]}...》({len(cached_text):,} 字)")
            continue

        print(f"\n[{idx}/{len(files)}] 正在萃取筆記: 《{f.name}》({f.stat().st_size / (1024*1024):.2f} MB)...")
        res = extract_single_note(f, max_pages=15)
        text = res["extracted_text"]

        if text and len(text.strip()) > 50:
            if res["has_ocr"]:
                ocr_count += 1
                print(f"  [✓] 手寫多模態 OCR 成功！取得 {len(text):,} 字。")
            else:
                digital_count += 1
                print(f"  [✓] 數位文字層抽取成功！取得 {len(text):,} 字。")

            # 1. 寫入本地 txt 快取
            try:
                cache_file.write_text(text, encoding="utf-8")
            except Exception:
                pass

            # 2. 寫入 SQLite 與 FTS5
            save_note_to_db(res)

            # 3. 收集至雲端全量快取 JSON
            cloud_cache_dict[f.name] = {
                "subject": res["subject"],
                "text": text,
                "size_mb": res["size_mb"]
            }
        else:
            print(f"  [!] 未能取得實質文字內容: 《{f.name}》")

        if max_ocr_items and ocr_count >= max_ocr_items:
            print(f"[*] 已達到指定 OCR 上限 ({max_ocr_items} 份)，暫停後續多模態辨識。")
            break

    # 4. 固化導出至 data/samsung_notes_cache.json
    print("\n" + "=" * 70)
    print(f"📦 正在將 {len(cloud_cache_dict)} 份筆記完整文字固化匯出至雲端快取 JSON...")
    try:
        with open(CLOUD_CACHE_JSON, "w", encoding="utf-8") as out_fp:
            json.dump(cloud_cache_dict, out_fp, ensure_ascii=False, indent=2)
        print(f"✅ 成功產出 {CLOUD_CACHE_JSON} (大小: {CLOUD_CACHE_JSON.stat().st_size / (1024*1024):.2f} MB)！")
    except Exception as je:
        print(f"[!] 匯出 JSON 失敗: {je}")

    # 5. 更新 Manifest
    try:
        sync_all_drive_notes_to_samsung_notes()
        print("✅ 筆記 Manifest 已同步更新。")
    except Exception:
        pass

    print("=" * 70)
    print("🎉 Samsung Notes 筆記抽取與固化作業順利完成！")
    print(f"• 既有快取秒載: {skipped_count} 份")
    print(f"• 數位文字抽取: {digital_count} 份")
    print(f"• 多模態手寫 OCR: {ocr_count} 份")
    print(f"• 累計收納庫容: {len(cloud_cache_dict)} 份")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Samsung Notes 批次 OCR 萃取與資料庫固化管線")
    parser.add_argument("--max-ocr", type=int, default=None, help="最多執行的多模態 OCR 筆記數量（預設不限）")
    parser.add_argument("--force-refresh", action="store_true", help="強制重新抽取/OCR 全部筆記")
    args = parser.parse_args()

    run_batch_distillation(max_ocr_items=args.max_ocr, force_refresh=args.force_refresh)


if __name__ == "__main__":
    main()
