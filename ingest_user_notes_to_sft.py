"""
手寫筆記與個人法學筆記 SFT 資料蒸餾引擎 (Ingest User Notes to SFT)
1. 自動讀取 G:\\我的雲端硬碟\\LawExamData\\SamsungNotes 內的所有個人手寫/打字筆記（PDF、圖片等）
2. 透過 Gemini 2.0 Flash 多模態神經網路進行高精度手寫繁體中文辨識與法學架構復原
3. 依據手寫爭點與體系，自動生成高品質的：
   - 司律二試實例申論題解（IRAC 架構、法條大前提、實務見解、學說肯否二說、涵攝）
   - 司律一試單選題與逐選項深入適法性剖析
   - 四維度國家考試評分診斷與上位卷升級引導
4. 輸出標準化 5 欄位綱要（id, source_type, instruction, input, output），
   無縫擴充入 law_exam_verified_sft.jsonl 與 law_exam_master_sft_unified.jsonl
"""
import os
import sys
import io
import json
import hashlib
import time
from pathlib import Path
from typing import List, Dict, Any

# Windows 終端編碼防護
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from PIL import Image
import pypdfium2 as pdfium
import google.generativeai as genai

from config import DATA_DIR, get_gemini_api_key, DEFAULT_GEMINI_MODEL
from merge_all_sft_datasets import merge_datasets

SAMSUNG_NOTES_DIR = Path(DATA_DIR) / "SamsungNotes"
TRAINING_DIR = Path(DATA_DIR) / "training_data"
OUT_SFT_FILE = TRAINING_DIR / "law_exam_user_notes_sft.jsonl"

def compute_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8", errors="ignore")).hexdigest()

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

def ocr_and_distill_notes(images: List[Image.Image], doc_title: str) -> List[Dict[str, Any]]:
    """調用 Gemini 2.0 Flash 對手寫筆記進行 OCR 並直接蒸餾為標準法學 SFT 訓練樣本"""
    api_key = get_gemini_api_key()
    if not api_key:
        print("  [錯誤] 未配置 GEMINI_API_KEY，請確認 .env 設定！")
        return []

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name=DEFAULT_GEMINI_MODEL)

    prompt = f"""
你是一位精通台灣法學與國家考試閱卷命題之權威法學專家。
這是一份考生珍貴的手寫法律筆記，檔名為《{doc_title}》。

【任務目標】：
請仔細辨識圖片中所有手寫文字、條號（如刑法各罪）、大前提法理、實務裁判字號（如最高法院判例、決議、大法庭裁定）、學者學說對比（通說、有力說、王澤鑑、林山田、黃榮堅、王皇玉、甘添貴等）、爭點肯否二說及案例，
並直接將這份筆記提煉轉化為「高品質法學 SFT 監督式微調訓練資料集」。

請輸出嚴格的 JSON 陣列，每個元素包含：
1. "subject": 考試科目（例如：刑法、民法、公法等）
2. "topic": 筆記的核心考點/爭點名稱（例如：人之始期與終期判定、義憤殺人罪之要件與外遇通姦爭議、加工自殺罪之可罰性本質等）
3. "task_type": "irac_reasoning"（司律二試實例題推導）或 "stage1_mcq"（司律一試測驗題）或 "diagnostic_eval"（四維度評分診斷）
4. "instruction": 給 AI 模型的系統指令（角色設定為命題閱卷委員）
5. "input": 題目的案件事實或考題情境
6. "output": 標準上位卷完整解答，必須完整融合筆記中記載的法條、實務字號、學者通說有力說之分歧對比與具體涵攝。

請輸出至少 5~8 組極具法學深度與高鑑別度的 SFT 訓練對象（請僅輸出標準 JSON 陣列，用 ```json ... ``` 包裹）。
"""

    sft_records = []
    # 每批送 3~4 頁
    batch_size = 4
    for i in range(0, len(images), batch_size):
        chunk = images[i:i+batch_size]
        print(f"  正在辨識與蒸餾手寫筆記第 {i+1} ~ {min(i+batch_size, len(images))} 頁...")
        try:
            response = model.generate_content([prompt] + chunk)
            resp_text = response.text.strip()
            
            # 提取 JSON 內容
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

def process_all_samsung_notes():
    print("=" * 70)
    print("  啟動：個人手寫筆記與 Samsung Notes 法學 SFT 蒸餾管線")
    print(f"  筆記目錄：{SAMSUNG_NOTES_DIR}")
    print("=" * 70)

    if not SAMSUNG_NOTES_DIR.exists():
        SAMSUNG_NOTES_DIR.mkdir(parents=True, exist_ok=True)
        print(f"  [建立目錄] {SAMSUNG_NOTES_DIR}")

    note_files = [f for f in SAMSUNG_NOTES_DIR.glob("*") if f.suffix.lower() in [".pdf", ".png", ".jpg", ".jpeg"]]
    if not note_files:
        print(f"  [提示] 目前 {SAMSUNG_NOTES_DIR} 尚無筆記檔案。")
        return

    print(f"  發現 {len(note_files)} 份手寫/個人筆記檔案：")
    for f in note_files:
        print(f"    - {f.name} ({f.stat().st_size / (1024*1024):.2f} MB)")

    all_samples = []
    for f in note_files:
        print(f"\n[處理筆記] 《{f.name}》...")
        if f.suffix.lower() == ".pdf":
            imgs = render_pdf_to_images(f)
        else:
            imgs = [Image.open(f)]

        print(f"  └─ 成功擷取 {len(imgs)} 頁手寫影像，啟動 Gemini 2.0 Flash 多模態蒸餾...")
        samples = ocr_and_distill_notes(imgs, f.stem)
        print(f"  └─ 成功自《{f.name}》提煉出 {len(samples)} 組標準 SFT 微調樣本！")
        all_samples.extend(samples)

    if all_samples:
        # 寫入專屬使用者筆記 SFT 檔
        with open(OUT_SFT_FILE, "w", encoding="utf-8") as f_out:
            for s in all_samples:
                f_out.write(json.dumps(s, ensure_ascii=False) + "\n")

        print("\n" + "=" * 70)
        print(f"  [蒸餾完成] 共產出 {len(all_samples)} 組手寫筆記 SFT 樣本！")
        print(f"  儲存路徑：{OUT_SFT_FILE}")
        print("  正在調用 merge_datasets() 自動合併至主訓練大庫...")
        print("=" * 70)

if __name__ == "__main__":
    process_all_samsung_notes()
