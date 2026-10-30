"""
手寫筆記與個人法學筆記 SFT 資料蒸餾引擎 (Ingest User Notes to SFT)
1. 自動讀取 G:\\我的雲端硬碟\\LawExamData\\SamsungNotes 內的所有個人手寫/打字筆記（PDF、圖片、Word 等 68+ 份筆記）
2. 支援一鍵自 Google Drive「資源」目錄同步身分法、民總、憲法、專利法、民訴等最新筆記
3. 透過 Gemini 2.0 Flash 多模態神經網路進行高精度手寫繁體中文辨識與法學架構復原（具備高速本機快取）
4. 依據手寫爭點與體系，自動生成高品質的：
   - 司律二試實例申論題解（IRAC 架構、法條大前提、實務見解、學說肯否二說、涵攝）
   - 司律一試單選題與逐選項深入適法性剖析
   - 四維度國家考試評分診斷與上位卷升級引導
5. 輸出標準化 5 欄位綱要（id, source_type, instruction, input, output），
   無縫擴充入 law_exam_verified_sft.jsonl 與 law_exam_master_sft_unified.jsonl
"""
import os
import sys
import io
import json
import shutil
import hashlib
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

# Windows 終端編碼防護
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
    from PIL import Image
except ImportError:
    Image = None

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

try:
    from google import genai
    from google.genai import types
    NEW_SDK = True
except ImportError:
    try:
        import google.generativeai as genai
        types = None
        NEW_SDK = False
    except ImportError:
        genai = None
        types = None
        NEW_SDK = False

from config import DATA_DIR, get_gemini_api_key, DEFAULT_GEMINI_MODEL, get_gemini_models_to_try
try:
    from merge_all_sft_datasets import merge_datasets
except ImportError:
    merge_datasets = None

SAMSUNG_NOTES_DIR = Path(DATA_DIR) / "SamsungNotes"
CACHE_DIR = SAMSUNG_NOTES_DIR / "_cache"
TRAINING_DIR = Path(DATA_DIR) / "training_data"
OUT_SFT_FILE = TRAINING_DIR / "law_exam_user_notes_sft.jsonl"

try:
    from six_codes_engine import classify_document_nature
except Exception:
    def classify_document_nature(filename: str, path: str = ""):
        s = (filename + " " + path).lower()
        if "百題" in s:
            if any(k in s for k in ["刑總", "刑分", "刑法", "刑"]):
                q_tag = "【刑法百題爭點】"
            elif any(k in s for k in ["民總", "民法", "債", "物權", "身分", "民"]):
                q_tag = "【民法百題爭點】"
            else:
                q_tag = "【百題爭點演練】"
            return {"doc_nature": "question", "nature_name": "🎯 實例試題與百題演練", "tag": q_tag, "badge_icon": "🎯"}
        elif "考古題" in s or any(k in s for k in ["試題", "考題", "題目", "演練", "模擬", "測驗"]):
            return {"doc_nature": "question", "nature_name": "🎯 實例試題與百題演練", "tag": "【實戰試題】", "badge_icon": "🎯"}
        elif any(k in s for k in ["講義", "課輔", "教材", "課程"]):
            return {"doc_nature": "handout", "nature_name": "📘 課輔與授課講義", "tag": "【課輔講義】", "badge_icon": "📘"}
        return {"doc_nature": "note", "nature_name": "📝 個人讀書筆記", "tag": "【個人筆記】", "badge_icon": "📝"}

import re

def chinese_to_int(s: str) -> int:
    """將中文數字（一至九十九）轉換為整數以供體系章節精確排序"""
    cn_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    s = s.strip()
    if not s:
        return 999
    if s == '十':
        return 10
    if s.startswith('十'):
        return 10 + cn_map.get(s[1:], 0)
    if '十' in s:
        parts = s.split('十')
        tens = cn_map.get(parts[0], 1) * 10
        units = cn_map.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens + units
    return cn_map.get(s, 999)

def get_chapter_sort_key(file_path: Path) -> tuple:
    """法學章節體系智能排序鍵：依中文章節號（一、親屬總論）、講義代號（AA01）或數值自然排序"""
    name = file_path.name
    # 1. 匹配中文章節號：如 一、親屬總論、(二)、【第三章】
    m = re.search(r'[（(【第]?([一二三四五六七八九十]+)[)）】、.章]', name)
    if m:
        return (0, chinese_to_int(m.group(1)), name)
    # 2. 匹配阿拉伯數字序號：如 AA01、01_、第1章
    m2 = re.search(r'(?:AA|講義|回|課輔|第)?(\d+)', name)
    if m2:
        return (1, int(m2.group(1)), name)
    return (2, 999, name)

def compute_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8", errors="ignore")).hexdigest()

def classify_resource_file(full_path: Path, resources_dir: Path):
    """
    智能識別「資源」目錄下檔案之考科、標準化檔名與出處/教授
    回傳：(subject, normalized_name, author)
    """
    try:
        rel_parts = full_path.relative_to(resources_dir).parts
    except Exception:
        rel_parts = (full_path.name,)
        
    top = rel_parts[0]
    fname = full_path.name
    
    subject = "其他"
    sub_category = ""
    author = ""

    if top == "民法":
        if len(rel_parts) >= 2:
            folder2 = rel_parts[1]
            if folder2 in ["身分法", "物權", "民總", "債各"]:
                subject = folder2
            elif folder2 in ["債一", "債二"]:
                subject = "債總"
            elif folder2 == "民總轉學考":
                subject = "民總"
            else:
                subject = "民法"
            
            if len(rel_parts) >= 3 and not rel_parts[2].endswith(full_path.suffix):
                author = rel_parts[2]
        else:
            subject = "民法"
            
    elif top == "刑總":
        subject = "刑總"
        if len(rel_parts) >= 2 and not rel_parts[1].endswith(full_path.suffix):
            author = rel_parts[1]
            
    elif top == "刑分":
        subject = "刑分"
        if len(rel_parts) >= 2 and not rel_parts[1].endswith(full_path.suffix):
            author = rel_parts[1]
            
    elif top == "智財":
        if len(rel_parts) >= 2:
            f2 = rel_parts[1]
            if f2 in ["專利法", "商標法", "著作權法"]:
                subject = f2
            else:
                subject = "智慧財產權法"
        else:
            subject = "智慧財產權法"
            
    elif top == "百題":
        sub_folder = rel_parts[1] if len(rel_parts) >= 2 and not rel_parts[1].endswith(full_path.suffix) else ""
        if sub_folder in ["刑總", "刑分", "刑法"]:
            subject = sub_folder
            author = "百題爭點"
        elif sub_folder in ["民總", "民法", "債總", "債各", "物權", "身分法"]:
            subject = sub_folder
            author = "百題爭點"
        elif "刑" in fname:
            subject = "刑總"
            author = "百題爭點"
        elif "民" in fname:
            subject = "民總"
            author = "百題爭點"
        else:
            subject = sub_folder or "法學百題"
            author = "百題爭點"
            
    elif top in ["憲法", "憲法轉學考"]:
        subject = "憲法"
        if top == "憲法轉學考":
            sub_category = "轉學考"
            
    elif top == "行政法":
        subject = "行政法"
    elif top == "商事法":
        subject = "商事法"
    elif top == "保險法":
        subject = "保險法"
    elif top == "民訴":
        subject = "民訴"
    elif top == "法理學錄音":
        subject = "法理學"
    elif top == "考古題":
        if any(k in fname for k in ["民法", "民總", "債", "物權", "身分"]):
            subject = "民法考古題"
        elif any(k in fname for k in ["刑法", "刑總", "刑分"]):
            subject = "刑法考古題"
        elif any(k in fname for k in ["憲法", "行政法", "公法"]):
            subject = "公法考古題"
        elif any(k in fname for k in ["民訴"]):
            subject = "民訴考古題"
        else:
            subject = "法學考古題"
    elif top == "雜項":
        subject = "法學實務"
    else:
        subject = top

    prefix_parts = [subject]
    if author and author not in fname:
        prefix_parts.append(author)
    if sub_category and sub_category not in fname:
        prefix_parts.append(sub_category)
        
    clean_prefix = "_".join(prefix_parts)
    
    if fname.startswith(f"{subject}_"):
        if author and author not in fname:
            normalized_name = f"{subject}_{author}_{fname[len(subject)+1:]}"
        else:
            normalized_name = fname
    else:
        normalized_name = f"{clean_prefix}_{fname}"

    normalized_name = normalized_name.replace("/", "_").replace("\\", "_")
    return subject, normalized_name, author

def get_resources_dir() -> Optional[Path]:
    """偵測 Google Drive「資源」資料夾路徑"""
    for candidate in [
        Path(__file__).resolve().parent.parent / "資源",
        Path(__file__).resolve().parent / "資源",
        Path(DATA_DIR).parent / "資源",
        Path(DATA_DIR) / "資源"
    ]:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None

def sync_all_drive_notes_to_samsung_notes() -> int:
    """自動自 Google Drive「資源」目錄與 SamsungNotes 動態掃描並同步所有法學考科最新檔案（涵蓋 550+ 份講義筆記，整合 DriveFS lost_and_found）"""
    # 優先執行 Google DriveFS lost_and_found 遺失修復整合
    try:
        from ingest_lost_and_found import run_lost_and_found_ingest
        run_lost_and_found_ingest()
    except Exception as _lafe:
        pass

    drive_notes = get_google_drive_notes_list()
    manifest_paths = [
        Path(DATA_DIR) / "drive_notes_manifest.json",
        Path(__file__).resolve().parent / "data" / "drive_notes_manifest.json"
    ]
    manifest_data = []
    for n in drive_notes:
        manifest_data.append({
            "filename": n["filename"],
            "orig_filename": n.get("orig_filename", n["filename"]),
            "subject": n["subject"],
            "author": n.get("author", ""),
            "size_mb": n["size_mb"],
            "path": str(n["path"]),
            "is_cached": n["is_cached"],
            "doc_nature": n.get("doc_nature", "note"),
            "nature_name": n.get("nature_name", "📝 個人讀書筆記"),
            "tag": n.get("tag", "【個人筆記】")
        })
    for mp in manifest_paths:
        try:
            mp.parent.mkdir(parents=True, exist_ok=True)
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return len(drive_notes)

def merge_subject_pdfs(subject: str, output_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    一鍵將指定考科底下的所有個別 PDF 筆記，依據法學章節體系邏輯順序，拼接合併為一個新的單一完整 PDF
    例如：身分法 26 份獨立 PDF (親屬總論 -> 扣減權) 自動拼接為單一《身分法_全科整合手寫體系總筆記.pdf》
    """
    samsung_dir = SAMSUNG_NOTES_DIR
    if not samsung_dir.exists():
        samsung_dir.mkdir(parents=True, exist_ok=True)
    
    all_notes = get_google_drive_notes_list()
    CIVIL_SUBS = {"民總", "債總", "債各", "物權", "身分法", "民法"}
    CRIM_SUBS = {"刑總", "刑分"}
    PUB_SUBS = {"憲法", "行政法"}
    COMM_SUBS = {"商事法", "保險法"}
    IP_SUBS = {"專利法", "商標法", "著作權法", "智慧財產權法"}

    # 找出該科目所有 PDF，排除已合併之總筆記
    if subject in ["全部考科", "全部"]:
        target_files = [
            n["path"] for n in all_notes 
            if n["path"].suffix.lower() == ".pdf"
            and "全科整合" not in n["filename"] and "全科體系" not in n["filename"]
        ]
    elif "民法" in subject:
        target_files = [
            n["path"] for n in all_notes 
            if n["subject"] in CIVIL_SUBS and n["path"].suffix.lower() == ".pdf"
            and "全科整合" not in n["filename"] and "全科體系" not in n["filename"]
        ]
    elif "刑法" in subject:
        target_files = [
            n["path"] for n in all_notes 
            if n["subject"] in CRIM_SUBS and n["path"].suffix.lower() == ".pdf"
            and "全科整合" not in n["filename"] and "全科體系" not in n["filename"]
        ]
    elif "公法" in subject:
        target_files = [
            n["path"] for n in all_notes 
            if n["subject"] in PUB_SUBS and n["path"].suffix.lower() == ".pdf"
            and "全科整合" not in n["filename"] and "全科體系" not in n["filename"]
        ]
    elif "商事" in subject:
        target_files = [
            n["path"] for n in all_notes 
            if n["subject"] in COMM_SUBS and n["path"].suffix.lower() == ".pdf"
            and "全科整合" not in n["filename"] and "全科體系" not in n["filename"]
        ]
    elif "智財" in subject:
        target_files = [
            n["path"] for n in all_notes 
            if n["subject"] in IP_SUBS and n["path"].suffix.lower() == ".pdf"
            and "全科整合" not in n["filename"] and "全科體系" not in n["filename"]
        ]
    else:
        target_files = [
            n["path"] for n in all_notes 
            if (n["subject"] == subject or subject in n["subject"]) and n["path"].suffix.lower() == ".pdf"
            and "全科整合" not in n["filename"] and "全科體系" not in n["filename"]
        ]
        
    if not target_files:
        raise ValueError(f"考科【{subject}】未找到任何可供合併之 PDF 筆記檔案。")
        
    sorted_files = sorted(target_files, key=get_chapter_sort_key)
    
    merged_doc = pdfium.PdfDocument.new()
    included_files = []
    
    for f in sorted_files:
        try:
            doc = pdfium.PdfDocument(f)
            merged_doc.import_pages(doc)
            included_files.append({
                "filename": f.name,
                "pages": len(doc),
                "size_mb": f.stat().st_size / (1024 * 1024)
            })
        except Exception as e:
            print(f"  [警示] 合併檔案 {f.name} 失敗: {e}")
            
    if len(merged_doc) == 0:
        raise RuntimeError(f"未能從【{subject}】的筆記中讀取到任何 PDF 頁面。")
        
    if output_path is None:
        output_path = samsung_dir / f"{subject}_全科整合手寫體系總筆記.pdf"
        
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged_doc.save(output_path)
    
    # 鏡像備份至 code/data/SamsungNotes/ (供 Streamlit Cloud 下載)
    repo_samsung = Path(__file__).resolve().parent / "data" / "SamsungNotes"
    if repo_samsung.exists() and output_path.parent.resolve() != repo_samsung.resolve():
        try:
            shutil.copy2(output_path, repo_samsung / output_path.name)
        except Exception:
            pass
            
    return {
        "subject": subject,
        "output_path": output_path,
        "total_pages": len(merged_doc),
        "file_size_mb": output_path.stat().st_size / (1024 * 1024),
        "file_count": len(included_files),
        "included_files": included_files
    }

def extract_subject_text_corpus(
    subject: str,
    auto_ocr: bool = True,
    max_pages_per_note: int = 15,
    progress_callback: Optional[Any] = None
) -> Dict[str, Any]:
    """
    一鍵將一整個考科的所有手寫/打字筆記進行全自動文字提取、OCR 辨識與快取建立，
    並自動依章節邏輯彙編成一份單一完整 Markdown 全科筆記大典
    """
    all_notes = get_google_drive_notes_list()
    CIVIL_SUBS = {"民總", "債總", "債各", "物權", "身分法", "民法"}
    CRIM_SUBS = {"刑總", "刑分"}
    PUB_SUBS = {"憲法", "行政法"}
    COMM_SUBS = {"商事法", "保險法"}
    IP_SUBS = {"專利法", "商標法", "著作權法", "智慧財產權法"}

    if subject in ["全部考科", "全部"]:
        sub_notes = [
            n for n in all_notes 
            if "全科整合" not in n["filename"] 
            and "全科體系" not in n["filename"]
            and not n["filename"].endswith("_全科筆記文字總彙編.md")
        ]
    elif "民法" in subject:
        sub_notes = [
            n for n in all_notes 
            if n["subject"] in CIVIL_SUBS 
            and "全科整合" not in n["filename"] 
            and "全科體系" not in n["filename"]
            and not n["filename"].endswith("_全科筆記文字總彙編.md")
        ]
    elif "刑法" in subject:
        sub_notes = [
            n for n in all_notes 
            if n["subject"] in CRIM_SUBS 
            and "全科整合" not in n["filename"] 
            and "全科體系" not in n["filename"]
            and not n["filename"].endswith("_全科筆記文字總彙編.md")
        ]
    elif "公法" in subject:
        sub_notes = [
            n for n in all_notes 
            if n["subject"] in PUB_SUBS 
            and "全科整合" not in n["filename"] 
            and "全科體系" not in n["filename"]
            and not n["filename"].endswith("_全科筆記文字總彙編.md")
        ]
    elif "商事" in subject:
        sub_notes = [
            n for n in all_notes 
            if n["subject"] in COMM_SUBS 
            and "全科整合" not in n["filename"] 
            and "全科體系" not in n["filename"]
            and not n["filename"].endswith("_全科筆記文字總彙編.md")
        ]
    elif "智財" in subject:
        sub_notes = [
            n for n in all_notes 
            if n["subject"] in IP_SUBS 
            and "全科整合" not in n["filename"] 
            and "全科體系" not in n["filename"]
            and not n["filename"].endswith("_全科筆記文字總彙編.md")
        ]
    else:
        sub_notes = [
            n for n in all_notes 
            if (n["subject"] == subject or subject in n["subject"])
            and "全科整合" not in n["filename"] 
            and "全科體系" not in n["filename"]
            and not n["filename"].endswith("_全科筆記文字總彙編.md")
        ]
    
    if not sub_notes:
        raise ValueError(f"考科【{subject}】查無任何筆記檔案。")
        
    sorted_notes = sorted(sub_notes, key=lambda n: (n.get("subject", ""), get_chapter_sort_key(n["path"])))
    
    chapters_extracted = []
    total_notes = len(sorted_notes)
    
    for idx, n in enumerate(sorted_notes, 1):
        if progress_callback:
            try:
                progress_callback(idx, total_notes, n["filename"])
            except Exception:
                pass
                
        text = read_note_text(n["path"], max_pages=max_pages_per_note, auto_ocr=auto_ocr)
        chapters_extracted.append({
            "chapter_index": idx,
            "filename": n["filename"],
            "title": n["stem"],
            "char_count": len(text),
            "text": text
        })
        
    # 組裝全科完整文字 Markdown
    total_chars = sum(c["char_count"] for c in chapters_extracted)
    md_lines = [
        f"# 📖 【{subject}】全科手寫體系與法學筆記總彙編",
        f"> ⚡ 本彙總由司法大模型管線自 {len(chapters_extracted)} 份個人手寫與講義檔案自動提取生成。",
        f"> 考科領域：**{subject}** ｜ 收錄章節：**{len(chapters_extracted)} 章** ｜ 總文字量：**{total_chars:,} 字元**",
        "\n---\n"
    ]
    
    for c in chapters_extracted:
        clean_title = c["title"].replace(f"{subject}_", "")
        md_lines.append(f"## 📌 第 {c['chapter_index']} 章：{clean_title}")
        md_lines.append(f"*來源檔案：`{c['filename']}` ｜ 本章字元：{c['char_count']:,}*")
        md_lines.append("\n" + c["text"].strip() + "\n\n---\n")
        
    full_markdown = "\n".join(md_lines)
    
    out_md_path = SAMSUNG_NOTES_DIR / f"{subject}_全科筆記文字總彙編.md"
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.write_text(full_markdown, encoding="utf-8")
    
    # 鏡像備份至 code/data/SamsungNotes/
    repo_samsung = Path(__file__).resolve().parent / "data" / "SamsungNotes"
    if repo_samsung.exists() and out_md_path.parent.resolve() != repo_samsung.resolve():
        try:
            shutil.copy2(out_md_path, repo_samsung / out_md_path.name)
        except Exception:
            pass
            
    return {
        "subject": subject,
        "total_notes": total_notes,
        "total_chars": total_chars,
        "output_path": out_md_path,
        "chapters": chapters_extracted,
        "full_text": full_markdown
    }


_DRIVE_NOTES_CACHE = None
_DRIVE_NOTES_CACHE_TIME = 0

def get_google_drive_notes_list(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    全方位動態掃描「資源」目錄與 SamsungNotes 目錄，
    即時回傳所有法學筆記（涵蓋民法各編、刑總、刑分、公法、商事法、智財等 550+ 份講義與筆記）之詳細清單。
    若無實體雲端硬碟掛載（如 Streamlit Cloud），自動調用 drive_notes_manifest.json 與 本地 SamsungNotes。
    """
    global _DRIVE_NOTES_CACHE, _DRIVE_NOTES_CACHE_TIME
    if not force_refresh and _DRIVE_NOTES_CACHE is not None and (time.time() - _DRIVE_NOTES_CACHE_TIME < 60):
        return _DRIVE_NOTES_CACHE

    existing_hashes = set()
    if OUT_SFT_FILE.exists():
        try:
            with open(OUT_SFT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    l = line.strip()
                    if l:
                        try:
                            it = json.loads(l)
                            existing_hashes.add(it.get("id", ""))
                        except Exception:
                            pass
        except Exception:
            pass

    existing_hashes_blob = " ".join(existing_hashes) if existing_hashes else ""

    valid_exts = {".pdf", ".docx", ".doc", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp"}
    ignore_folders = {"DLCV", "training", "近代物理"}
    
    # 預先載入快取檔案名稱清單，避免遠端虛擬硬碟數千次 stat 呼叫
    existing_caches = set(os.listdir(CACHE_DIR)) if CACHE_DIR.exists() else set()
    
    notes_dict = {}
    resources_dir = get_resources_dir()
    
    # 1. 優先掃描 Google Drive「資源」目錄（包含民法、刑總、刑分、智財等所有子目錄）
    if resources_dir and resources_dir.exists():
        for root, dirs, files in os.walk(resources_dir):
            rel = os.path.relpath(root, resources_dir)
            top = rel.split(os.sep)[0]
            if top in ignore_folders or top.startswith("."):
                continue
            for f in files:
                if f == "desktop.ini" or f.startswith("."):
                    continue
                p = Path(root) / f
                if p.suffix.lower() in valid_exts:
                    subject, norm_name, author = classify_resource_file(p, resources_dir)
                    try:
                        size_mb = p.stat().st_size / (1024 * 1024)
                    except Exception:
                        size_mb = 0.0
                    
                    is_cached = (f"{p.name}.txt" in existing_caches) or (f"{norm_name}.txt" in existing_caches)
                    distilled_count = 1 if (p.stem[:8] in existing_hashes_blob or norm_name[:8] in existing_hashes_blob) else 0
                    
                    nat = classify_document_nature(norm_name, str(p))
                    notes_dict[norm_name] = {
                        "filename": norm_name,
                        "orig_filename": p.name,
                        "stem": Path(norm_name).stem,
                        "subject": subject,
                        "author": author,
                        "size_mb": round(size_mb, 2),
                        "path": p,
                        "is_cached": is_cached,
                        "distilled_count": distilled_count,
                        "doc_nature": nat["doc_nature"],
                        "nature_name": nat["nature_name"],
                        "tag": nat["tag"],
                        "badge_icon": nat["badge_icon"]
                    }
                    
    # 2. 補充掃描 SamsungNotes 目錄（納入可能獨立存放或 Samsung Notes 直接匯出之講義筆記）
    if SAMSUNG_NOTES_DIR.exists():
        for f in sorted(SAMSUNG_NOTES_DIR.glob("*")):
            if f.is_file() and f.suffix.lower() in valid_exts and f.name != "desktop.ini" and not f.name.startswith("."):
                if f.name in notes_dict:
                    continue
                orig_found = False
                for existing_v in notes_dict.values():
                    if f.name == existing_v.get("orig_filename"):
                        orig_found = True
                        break
                if orig_found:
                    continue
                    
                stem = f.stem
                subject = stem.split("_")[0] if "_" in stem else "其他"
                try:
                    size_mb = f.stat().st_size / (1024 * 1024)
                except Exception:
                    size_mb = 0.0
                is_cached = f"{f.name}.txt" in existing_caches
                distilled_count = 1 if f.stem[:8] in existing_hashes_blob else 0
                
                nat = classify_document_nature(f.name, str(f))
                notes_dict[f.name] = {
                    "filename": f.name,
                    "orig_filename": f.name,
                    "stem": stem,
                    "subject": subject,
                    "author": "",
                    "size_mb": round(size_mb, 2),
                    "path": f,
                    "is_cached": is_cached,
                    "distilled_count": distilled_count,
                    "doc_nature": nat["doc_nature"],
                    "nature_name": nat["nature_name"],
                    "tag": nat["tag"],
                    "badge_icon": nat["badge_icon"]
                }

    # 3. 雲端部署回退（例如 Streamlit Cloud，若實體資料夾檔案有限，由 manifest 補齊檔案清單）
    manifest_paths = [
        Path(DATA_DIR) / "drive_notes_manifest.json",
        Path(__file__).resolve().parent / "data" / "drive_notes_manifest.json"
    ]
    if len(notes_dict) < 100:
        for mp in manifest_paths:
            if mp.exists():
                try:
                    with open(mp, "r", encoding="utf-8") as mf:
                        m_list = json.load(mf)
                        for item in m_list:
                            fname = item.get("filename", "")
                            if fname and fname not in notes_dict:
                                local_p = SAMSUNG_NOTES_DIR / fname
                                alt_p = Path(__file__).resolve().parent / "data" / "SamsungNotes" / fname
                                p = local_p if local_p.exists() else (alt_p if alt_p.exists() else Path(item.get("path", fname)))
                                nat = classify_document_nature(fname, str(p))
                                notes_dict[fname] = {
                                    "filename": fname,
                                    "orig_filename": item.get("orig_filename", fname),
                                    "stem": Path(fname).stem,
                                    "subject": item.get("subject", "其他"),
                                    "author": item.get("author", ""),
                                    "size_mb": item.get("size_mb", 0.0),
                                    "path": p,
                                    "is_cached": item.get("is_cached", False),
                                    "distilled_count": 0,
                                    "doc_nature": item.get("doc_nature") or nat["doc_nature"],
                                    "nature_name": item.get("nature_name") or nat["nature_name"],
                                    "tag": item.get("tag") or nat["tag"],
                                    "badge_icon": nat["badge_icon"]
                                }
                except Exception:
                    pass

    # 4. 排序規則：民法各編優先排前，其餘章節自然排序
    subject_order = {
        "民總": 1, "債總": 2, "債各": 3, "物權": 4, "身分法": 5, "民法": 6, "民法考古題": 7,
        "刑總": 10, "刑分": 11, "刑法考古題": 12,
        "憲法": 20, "行政法": 21, "公法考古題": 22,
        "民訴": 30, "民訴考古題": 31,
        "商事法": 40, "保險法": 41,
        "專利法": 50, "商標法": 51, "著作權法": 52, "智慧財產權法": 53,
        "法理學": 60, "法學考古題": 70, "法學實務": 80, "其他": 99
    }
    
    sorted_notes = sorted(
        notes_dict.values(),
        key=lambda n: (subject_order.get(n["subject"], 90), get_chapter_sort_key(n["path"]))
    )
    _DRIVE_NOTES_CACHE = sorted_notes
    _DRIVE_NOTES_CACHE_TIME = time.time()
    return sorted_notes

def render_pdf_to_images(pdf_path: Path, max_pages: int = 15):
    """使用 pypdfium2 高速 C++ 引擎將 PDF 頁面渲染為高品質 PIL 圖片"""
    images = []
    if pdfium is None:
        return images
    try:
        pdf = pdfium.PdfDocument(pdf_path)
        total = min(len(pdf), max_pages)
        for i in range(total):
            page = pdf[i]
            pil_image = page.render(scale=2.0).to_pil()
            images.append(pil_image)
    except Exception as e:
        print(f"  [警示] 渲染 PDF 失敗: {e}")
    return images

def save_to_samsung_notes_cache(filename: str, text: str):
    """將提取或視覺 OCR 解析之筆記內文同時寫入本地 _cache 目錄與 samsung_notes_cache.json"""
    if not filename or not text or text.startswith("["):
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{filename}.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass

    try:
        json_candidates = [
            Path(DATA_DIR) / "samsung_notes_cache.json",
            Path(__file__).resolve().parent / "data" / "samsung_notes_cache.json"
        ]
        for jp in json_candidates:
            c_dict = {}
            if jp.exists():
                try:
                    with open(jp, "r", encoding="utf-8") as f:
                        c_dict = json.load(f)
                except Exception:
                    c_dict = {}
            c_dict[filename] = {"text": text, "char_count": len(text)}
            jp.parent.mkdir(parents=True, exist_ok=True)
            with open(jp, "w", encoding="utf-8") as f:
                json.dump(c_dict, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[快取存檔提示] {e}")

def read_note_text(file_path: Any, max_pages: int = 60, auto_ocr: bool = True) -> str:
    """高速讀取筆記文字：優先讀取快取；若無快取則自動直讀數位字或調用 Gemini 多模態 OCR 並寫入快取"""
    if not file_path:
        return ""
    if isinstance(file_path, str):
        file_path = Path(file_path)
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    cache_candidates = [
        CACHE_DIR / f"{file_path.name}.txt",
        CACHE_DIR / f"{file_path.stem}.txt"
    ]
    if "_" in file_path.name:
        cache_candidates.append(CACHE_DIR / f"{file_path.name.split('_', 1)[-1]}.txt")
        cache_candidates.append(CACHE_DIR / f"{file_path.name.split('_')[-1]}.txt")

    for cf in cache_candidates:
        if cf.exists() and cf.stat().st_size > 0:
            try:
                txt = cf.read_text(encoding="utf-8")
                if txt.strip():
                    return txt
            except Exception:
                pass

    primary_cache_file = CACHE_DIR / f"{file_path.name}.txt"
    
    # 檢查實體檔案是否存在（若為 Streamlit Cloud 或檔案未落地，依序從快取 JSON 與 SQLite 資料庫讀取）
    if not file_path.exists() or not file_path.is_file():
        # 1. 檢查本機與 repo 內 _cache 目錄
        repo_cache = Path(__file__).resolve().parent / "data" / "SamsungNotes" / "_cache" / f"{file_path.name}.txt"
        if repo_cache.exists() and repo_cache.stat().st_size > 0:
            return repo_cache.read_text(encoding="utf-8")

        # 2. 檢查全量雲端同步快取 JSON (samsung_notes_cache.json)
        json_candidates = [
            Path(DATA_DIR) / "samsung_notes_cache.json",
            Path(__file__).resolve().parent / "data" / "samsung_notes_cache.json",
            Path(__file__).resolve().parent.parent / "data" / "samsung_notes_cache.json"
        ]
        for jc in json_candidates:
            if jc.exists():
                try:
                    with open(jc, "r", encoding="utf-8") as jf:
                        c_dict = json.load(jf)
                        if file_path.name in c_dict:
                            item = c_dict[file_path.name]
                            txt = item.get("text", "") if isinstance(item, dict) else str(item)
                            if txt and len(txt.strip()) > 50:
                                return txt
                except Exception:
                    pass

        # 3. 檢查 SQLite 資料庫 user_notes 資料表
        try:
            db_file = Path(DATA_DIR) / "judicial_authority.db"
            if db_file.exists():
                import sqlite3
                conn = sqlite3.connect(str(db_file), timeout=5.0)
                cur = conn.cursor()
                cur.execute("SELECT extracted_text FROM user_notes WHERE filename = ? OR note_id = ?", (file_path.name, file_path.name))
                row = cur.fetchone()
                conn.close()
                if row and row[0] and len(row[0].strip()) > 50:
                    return row[0]
        except Exception:
            pass

        return f"[筆記《{file_path.name}》已收錄於 Google Drive 雲端庫]"

    ext = file_path.suffix.lower()
    text = ""
    
    if ext == ".pdf":
        try:
            doc = pdfium.PdfDocument(file_path)
            total_doc_pages = len(doc)
            scan_pages = min(total_doc_pages, max_pages)
            extracted = []
            for i in range(scan_pages):
                t = doc[i].get_textpage().get_text_range()
                if t and t.strip():
                    extracted.append(t.strip())
            digital_text = "\n\n".join(extracted)
            avg_chars = len(digital_text.strip()) / max(1, scan_pages)

            # 若數位文字充足（非手寫、非圖片掃描），直接採用
            if len(digital_text.strip()) > 150 and avg_chars >= 40:
                text = digital_text
            elif auto_ocr:
                from doc_parser import ocr_handwritten_images
                imgs = render_pdf_to_images(file_path, max_pages=max_pages)
                if imgs:
                    ocr_res = ocr_handwritten_images(imgs, prompt_hint=file_path.stem)
                    if ocr_res and not ocr_res.startswith("["):
                        if digital_text and len(digital_text.strip()) > 40:
                            text = f"【數位檢定文字】：\n{digital_text}\n\n---\n【視覺手寫OCR解析】：\n{ocr_res}"
                        else:
                            text = ocr_res
                    elif digital_text:
                        text = digital_text
            elif digital_text:
                text = digital_text
        except Exception as e:
            text = f"[PDF 讀取異常: {e}]"
            
    elif ext in [".docx"]:
        try:
            import docx
            doc = docx.Document(file_path)
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception as e:
            text = f"[Word 讀取異常: {e}]"
            
    elif ext in [".txt", ".md"]:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            text = f"[文字讀取異常: {e}]"
            
    elif ext in [".png", ".jpg", ".jpeg", ".webp"]:
        if auto_ocr:
            try:
                from doc_parser import ocr_handwritten_images
                img = Image.open(file_path)
                text = ocr_handwritten_images([img], prompt_hint=file_path.stem)
            except Exception as e:
                text = f"[圖片辨識異常: {e}]"

    if text and not text.startswith("["):
        save_to_samsung_notes_cache(file_path.name, text)
            
    return text


def get_full_drive_note_content(note_info_or_path: Any, max_chars: int = 100000, auto_ocr: bool = True) -> Dict[str, Any]:
    """
    深度提取 Google Drive 講義與筆記實體檔案之全文內容（真實 RAG 核心）：
    支援 PDF（自動多頁文字萃取 + 視覺 OCR）、Word、TXT、Markdown 與圖片。
    回傳具備完整檔名、考科、作者、總字數與真實全文之字典，保證 100% 傳送給 Gemini API。
    """
    if not note_info_or_path:
        return {"filename": "", "subject": "其他", "author": "", "char_count": 0, "text": "", "path": None}

    fname = ""
    subject = "其他"
    author = ""
    resolved_path = None

    if isinstance(note_info_or_path, dict):
        fname = note_info_or_path.get("filename", "")
        subject = note_info_or_path.get("subject", "其他")
        author = note_info_or_path.get("author", "")
        raw_p = note_info_or_path.get("path")
        if raw_p:
            resolved_path = Path(raw_p) if isinstance(raw_p, str) else raw_p
    elif isinstance(note_info_or_path, (str, Path)):
        resolved_path = Path(note_info_or_path)
        fname = resolved_path.name
        subject = fname.split("_")[0] if "_" in fname else "其他"

    if not resolved_path or not resolved_path.exists():
        candidates = [
            SAMSUNG_NOTES_DIR / fname,
            Path(DATA_DIR) / "SamsungNotes" / fname,
            Path(__file__).resolve().parent / "data" / "SamsungNotes" / fname,
            Path("G:/我的雲端硬碟/LawExamData/SamsungNotes") / fname,
            Path("G:/我的雲端硬碟/LawExamData/資源") / fname,
        ]
        r_dir = get_resources_dir()
        if r_dir and r_dir.exists():
            for root, _, files in os.walk(r_dir):
                if fname in files:
                    candidates.append(Path(root) / fname)
                    break
        for cand in candidates:
            if cand.exists() and cand.is_file():
                resolved_path = cand
                break

    full_text = ""
    if resolved_path and resolved_path.exists():
        full_text = read_note_text(resolved_path, max_pages=60, auto_ocr=auto_ocr)
    elif fname:
        full_text = read_note_text(fname, max_pages=60, auto_ocr=False)

    if len(full_text) > max_chars:
        full_text = full_text[:max_chars]

    return {
        "filename": fname,
        "subject": subject,
        "author": author,
        "char_count": len(full_text),
        "text": full_text,
        "path": resolved_path,
        "is_cached": bool(full_text and not full_text.startswith("["))
    }


def ocr_and_distill_notes(images: List[Image.Image], doc_title: str) -> List[Dict[str, Any]]:
    """調用 Gemini 2.0 Flash 對手寫筆記進行 OCR 並直接蒸餾為標準法學 SFT 訓練樣本"""
    api_key = get_gemini_api_key()
    if not api_key:
        print("  [錯誤] 未配置 GEMINI_API_KEY，請確認 .env 設定！")
        return []

    if NEW_SDK:
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json"
        )
    elif genai is not None:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name=DEFAULT_GEMINI_MODEL)
    else:
        print("  [錯誤] 系統未安裝 google-genai 套件！")
        return []

    prompt = f"""
你是一位精通台灣法學與國家考試閱卷命題之權威法學專家。
這是一份考生珍貴的手寫法律筆記，檔名為《{doc_title}》。

【任務目標】：
請仔細辨識圖片中所有手寫文字、條號、大前提法理、實務裁判字號（如最高法院判例、決議、大法庭裁定）、學者學說對比（通說、有力說）、爭點肯否二說及案例，
並直接將這份筆記提煉轉化為「高品質法學 SFT 監督式微調訓練資料集」。

請輸出嚴格的 JSON 陣列，每個元素包含：
1. "subject": 考試科目（例如：刑法、民法、公法、身分法等）
2. "topic": 筆記的核心考點/爭點名稱
3. "task_type": "irac_reasoning"（司律二試實例題推導）或 "stage1_mcq"（司律一試測驗題）或 "diagnostic_eval"（四維度評分診斷）
4. "instruction": 給 AI 模型的系統指令（角色設定為命題閱卷委員）
5. "input": 題目的案件事實或考題情境
6. "output": 標準上位卷完整解答，必須完整融合筆記中記載的法條、實務字號、學者通說有力說之分歧對比與具體涵攝。

請輸出至少 5~8 組極具法學深度與高鑑別度的 SFT 訓練對象（請僅輸出標準 JSON 陣列，用 ```json ... ``` 包裹）。
"""

    sft_records = []
    batch_size = 4
    for i in range(0, len(images), batch_size):
        chunk = images[i:i+batch_size]
        print(f"  正在辨識與蒸餾手寫筆記第 {i+1} ~ {min(i+batch_size, len(images))} 頁...")
        try:
            resp_text = None
            for m_name in get_gemini_models_to_try():
                try:
                    if NEW_SDK:
                        response = client.models.generate_content(
                            model=m_name,
                            contents=[prompt] + chunk,
                            config=config
                        )
                    else:
                        cur_model = genai.GenerativeModel(model_name=m_name)
                        response = cur_model.generate_content([prompt] + chunk)
                    if response and response.text:
                        resp_text = response.text.strip()
                        break
                except Exception:
                    continue
            if not resp_text:
                continue
            
            if "```json" in resp_text:
                json_str = resp_text.split("```json")[1].split("```")[0].strip()
            elif "```" in resp_text:
                json_str = resp_text.split("```")[1].split("```")[0].strip()
            else:
                json_str = resp_text

            items = json.loads(json_str)
            if isinstance(items, list):
                for idx, item in enumerate(items):
                    inst = item.get("instruction", "").strip()
                    inp = item.get("input", "").strip()
                    out = item.get("output", "").strip()
                    if inst and out:
                        h = compute_hash(inst + inp)[:10]
                        sft_records.append({
                            "id": f"user_note_{doc_title[:10]}_{i}_{idx}_{h}",
                            "source_type": "verified_user_handwritten_notes",
                            "instruction": inst,
                            "input": inp,
                            "output": out
                        })
        except Exception as e:
            print(f"  [警示] 處理第 {i+1} 頁失敗: {e}")
        time.sleep(1.0)

    return sft_records

def distill_notes_from_text(text: str, doc_title: str) -> List[Dict[str, Any]]:
    """調用 Gemini 2.0 Flash 對已解析之文字筆記進行法學 SFT 訓練資料蒸餾"""
    api_key = get_gemini_api_key()
    if not api_key:
        print("  [錯誤] 未配置 GEMINI_API_KEY，請確認 .env 設定！")
        return []

    if NEW_SDK:
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json"
        )
    elif genai is not None:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name=DEFAULT_GEMINI_MODEL)
    else:
        print("  [錯誤] 系統未安裝 google-genai 套件！")
        return []

    prompt = f"""
你是一位精通台灣法學與國家考試閱卷命題之權威法學專家。
這是一份考生個人法律筆記/課輔講義內容，檔名為《{doc_title}》：

=== 筆記內容開始 ===
{text[:12000]}
=== 筆記內容結束 ===

【任務目標】：
請依據上述筆記內容記載之法條、大前提法理、實務裁判字號（最高法院判例、決議、大法庭裁定）、學者學說對比（通說、有力說分歧）、爭點肯否二說及案例事實，
直接將這份筆記提煉轉化為「高品質法學 SFT 監督式微調訓練資料集」。

請輸出嚴格的 JSON 陣列，每個元素包含：
1. "subject": 考試科目（例如：民法、身分法、憲法、刑法、專利法等）
2. "topic": 筆記的核心考點/爭點名稱
3. "task_type": "irac_reasoning"（司律二試實例題推導）或 "stage1_mcq"（司律一試測驗題）或 "diagnostic_eval"（四維度評分診斷）
4. "instruction": 給 AI 模型的系統指令（角色設定為命題閱卷委員）
5. "input": 題目的案件事實或考題情境
6. "output": 標準上位卷完整解答，必須完整融合筆記中記載的法條、實務字號、學者通說有力說之分歧對比與具體涵攝。

請輸出至少 5~8 組極具法學深度與高鑑別度的 SFT 訓練對象（請僅輸出標準 JSON 陣列，用 ```json ... ``` 包裹）。
"""
    resp_text = None
    for m_name in get_gemini_models_to_try():
        try:
            if NEW_SDK:
                response = client.models.generate_content(
                    model=m_name,
                    contents=[prompt],
                    config=config
                )
            else:
                response = model.generate_content([prompt])
            if response and response.text:
                resp_text = response.text.strip()
                break
        except Exception:
            continue

    if not resp_text:
        return []

    try:
        
        if "```json" in resp_text:
            json_str = resp_text.split("```json")[1].split("```")[0].strip()
        elif "```" in resp_text:
            json_str = resp_text.split("```")[1].split("```")[0].strip()
        else:
            json_str = resp_text

        items = json.loads(json_str)
        sft_records = []
        if isinstance(items, list):
            for idx, item in enumerate(items):
                inst = item.get("instruction", "").strip()
                inp = item.get("input", "").strip()
                out = item.get("output", "").strip()
                if inst and out:
                    h = compute_hash(inst + inp)[:10]
                    sft_records.append({
                        "id": f"user_note_{doc_title[:10]}_{idx}_{h}",
                        "source_type": "verified_user_handwritten_notes",
                        "instruction": inst,
                        "input": inp,
                        "output": out
                    })
        return sft_records
    except Exception as e:
        print(f"  [警示] 文字蒸餾失敗: {e}")
        return []

def distill_single_note_file(file_path: Path, max_pages: int = 15) -> List[Dict[str, Any]]:
    """對單一雲端筆記檔案執行多模態 OCR 與法學 SFT 蒸餾，並即時合併入主訓練大庫"""
    text = read_note_text(file_path, max_pages=max_pages, auto_ocr=True)
    if not text or text.startswith("["):
        if file_path.suffix.lower() == ".pdf":
            imgs = render_pdf_to_images(file_path, max_pages=max_pages)
            if imgs:
                new_samples = ocr_and_distill_notes(imgs, file_path.stem)
            else:
                return []
        else:
            return []
    else:
        new_samples = distill_notes_from_text(text, file_path.stem)

    if new_samples:
        existing_hashes = set()
        existing_samples = []
        if OUT_SFT_FILE.exists():
            with open(OUT_SFT_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line_str = line.strip()
                    if line_str:
                        try:
                            item = json.loads(line_str)
                            existing_samples.append(item)
                            existing_hashes.add(compute_hash(item.get("instruction", "") + item.get("input", "")))
                        except Exception:
                            pass
        
        for s in new_samples:
            h = compute_hash(s.get("instruction", "") + s.get("input", ""))
            if h not in existing_hashes:
                existing_hashes.add(h)
                existing_samples.append(s)
        
        OUT_SFT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_SFT_FILE, "w", encoding="utf-8") as f_out:
            for s in existing_samples:
                f_out.write(json.dumps(s, ensure_ascii=False) + "\n")
        
        # 同步鏡像至 code/data/training_data/ 確保本機提煉成果隨時可推播至 Streamlit Cloud
        repo_data_sft = Path(__file__).resolve().parent / "data" / "training_data" / "law_exam_user_notes_sft.jsonl"
        if repo_data_sft.resolve() != OUT_SFT_FILE.resolve():
            try:
                repo_data_sft.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(OUT_SFT_FILE, repo_data_sft)
            except Exception:
                pass

        try:
            merge_datasets(include_synthetic=False)
        except Exception as me:
            print(f"[警告] 自動合併失敗: {me}")
            
    return new_samples

def process_all_samsung_notes():
    print("=" * 70)
    print("  啟動：個人手寫筆記與 Samsung Notes 法學 SFT 蒸餾管線")
    print(f"  筆記目錄：{SAMSUNG_NOTES_DIR}")
    print("=" * 70)

    if not SAMSUNG_NOTES_DIR.exists():
        SAMSUNG_NOTES_DIR.mkdir(parents=True, exist_ok=True)
        print(f"  [建立目錄] {SAMSUNG_NOTES_DIR}")

    sync_all_drive_notes_to_samsung_notes()
    note_files = [f for f in SAMSUNG_NOTES_DIR.glob("*") if f.is_file() and f.suffix.lower() in [".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp"]]
    if not note_files:
        print(f"  [提示] 目前 {SAMSUNG_NOTES_DIR} 尚無筆記檔案。")
        return

    print(f"  發現 {len(note_files)} 份手寫/個人筆記檔案：")
    for f in note_files[:10]:
        print(f"    - {f.name} ({f.stat().st_size / (1024*1024):.2f} MB)")
    if len(note_files) > 10:
        print(f"    ... 以及其餘 {len(note_files)-10} 份筆記")

    for idx, f in enumerate(note_files, 1):
        print(f"\n[{idx}/{len(note_files)}] 處理筆記《{f.name}》...")
        try:
            samples = distill_single_note_file(f)
            print(f"  └─ 成功提煉出 {len(samples)} 組標準 SFT 微調樣本！")
        except Exception as e:
            print(f"  [警示] 處理 {f.name} 失敗: {e}")

    try:
        print("\n  正在執行全量統一資料庫合併 (含百萬基準庫)...")
        merge_datasets(include_synthetic=True)
    except Exception as me:
        print(f"  [警示] 全量資料庫合併失敗: {me}")

    print("\n" + "=" * 70)
    print(f"  [蒸餾全數完成] 儲存路徑：{OUT_SFT_FILE}")
    print("=" * 70)

def ingest_single_uploaded_file(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    """接收前端上傳之手寫檔案 byte 串流，自動儲存至 SamsungNotes 並蒸餾寫入 SFT 資料庫"""
    if not SAMSUNG_NOTES_DIR.exists():
        SAMSUNG_NOTES_DIR.mkdir(parents=True, exist_ok=True)
    
    saved_path = SAMSUNG_NOTES_DIR / filename
    with open(saved_path, "wb") as f:
        f.write(file_bytes)
    
    return distill_single_note_file(saved_path)

if __name__ == "__main__":
    process_all_samsung_notes()
