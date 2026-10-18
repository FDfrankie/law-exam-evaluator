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
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from PIL import Image
import pypdfium2 as pdfium

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

from config import DATA_DIR, get_gemini_api_key, DEFAULT_GEMINI_MODEL
from merge_all_sft_datasets import merge_datasets

SAMSUNG_NOTES_DIR = Path(DATA_DIR) / "SamsungNotes"
CACHE_DIR = SAMSUNG_NOTES_DIR / "_cache"
TRAINING_DIR = Path(DATA_DIR) / "training_data"
OUT_SFT_FILE = TRAINING_DIR / "law_exam_user_notes_sft.jsonl"

def compute_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8", errors="ignore")).hexdigest()

def sync_all_drive_notes_to_samsung_notes() -> int:
    """自動自 G:\\我的雲端硬碟\\資源\\ 各科筆記同步最新檔案至 SamsungNotes 目錄"""
    drive = Path(r"G:\我的雲端硬碟")
    samsung_dir = SAMSUNG_NOTES_DIR
    samsung_dir.mkdir(parents=True, exist_ok=True)
    
    resources_dir = drive / "資源"
    source_folders = {
        "身分法": resources_dir / "身分法",
        "憲法": resources_dir / "憲法",
        "民總": resources_dir / "民總",
        "民訴": resources_dir / "民訴",
        "專利法": resources_dir / "專利法",
        "雜項": resources_dir / "雜項"
    }
    
    copied = 0
    for cat, folder in source_folders.items():
        if not folder.exists():
            continue
        for f in folder.iterdir():
            if f.suffix.lower() in [".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp"]:
                dest_name = f"{cat}_{f.name}"
                dest_path = samsung_dir / dest_name
                if not dest_path.exists() or dest_path.stat().st_size != f.stat().st_size:
                    try:
                        shutil.copy2(f, dest_path)
                        copied += 1
                    except Exception as e:
                        print(f"  [警示] 同步 {f.name} 失敗: {e}")
    return copied

def get_google_drive_notes_list() -> List[Dict[str, Any]]:
    """掃描 SamsungNotes 目錄，回傳所有已歸檔筆記之詳細清單"""
    if not SAMSUNG_NOTES_DIR.exists():
        SAMSUNG_NOTES_DIR.mkdir(parents=True, exist_ok=True)
        sync_all_drive_notes_to_samsung_notes()
    
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

    notes = []
    for f in sorted(SAMSUNG_NOTES_DIR.glob("*")):
        if f.is_file() and f.suffix.lower() in [".pdf", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp"]:
            stem = f.stem
            subject = stem.split("_")[0] if "_" in stem else "其他"
            cache_file = CACHE_DIR / f"{f.name}.txt"
            is_cached = cache_file.exists() and cache_file.stat().st_size > 0
            
            # 判斷是否已有蒸餾樣本
            distilled_count = sum(1 for h in existing_hashes if f.stem[:10] in h)
            
            notes.append({
                "filename": f.name,
                "stem": f.stem,
                "subject": subject,
                "size_mb": f.stat().st_size / (1024 * 1024),
                "path": f,
                "is_cached": is_cached,
                "distilled_count": distilled_count
            })
    return notes

def render_pdf_to_images(pdf_path: Path, max_pages: int = 15) -> List[Image.Image]:
    """使用 pypdfium2 高速 C++ 引擎將 PDF 頁面渲染為高品質 PIL 圖片"""
    images = []
    try:
        pdf = pdfium.PdfDocument(pdf_path)
        total = min(len(pdf), max_pages)
        for i in range(total):
            page = pdf[i]
            # 渲染為 200 DPI 高畫質圖像
            pil_image = page.render(scale=2.0).to_pil()
            images.append(pil_image)
    except Exception as e:
        print(f"  [警示] 渲染 PDF 失敗: {e}")
    return images

def read_note_text(file_path: Path, max_pages: int = 15, auto_ocr: bool = True) -> str:
    """高速讀取筆記文字：優先讀取快取；若無快取則自動直讀數位字或調用 Gemini 多模態 OCR 並寫入快取"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{file_path.name}.txt"
    if cache_file.exists():
        try:
            return cache_file.read_text(encoding="utf-8")
        except Exception:
            pass

    ext = file_path.suffix.lower()
    text = ""
    
    if ext == ".pdf":
        try:
            doc = pdfium.PdfDocument(file_path)
            extracted = []
            for i in range(min(len(doc), max_pages)):
                t = doc[i].get_textpage().get_text_range()
                if t and t.strip():
                    extracted.append(t.strip())
            digital_text = "\n\n".join(extracted)
            if len(digital_text.strip()) > 300:
                text = digital_text
            elif auto_ocr:
                from doc_parser import ocr_handwritten_images
                imgs = render_pdf_to_images(file_path, max_pages=max_pages)
                if imgs:
                    text = ocr_handwritten_images(imgs, prompt_hint=file_path.stem)
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
        try:
            cache_file.write_text(text, encoding="utf-8")
        except Exception:
            pass
            
    return text

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
            if NEW_SDK:
                response = client.models.generate_content(
                    model=DEFAULT_GEMINI_MODEL,
                    contents=[prompt] + chunk,
                    config=config
                )
            else:
                response = model.generate_content([prompt] + chunk)
            resp_text = response.text.strip()
            
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
    try:
        if NEW_SDK:
            response = client.models.generate_content(
                model=DEFAULT_GEMINI_MODEL,
                contents=[prompt],
                config=config
            )
        else:
            response = model.generate_content([prompt])
        resp_text = response.text.strip()
        
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
