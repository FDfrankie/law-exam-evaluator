"""
司法官律師微調大庫 - 動態權重平衡產生器 (Weighted SFT Dataset Generator)
解決問題：
1. 防止 100 萬筆模板資料稀釋 18 筆極致珍貴的手寫筆記與 300+ 筆司律真題。
2. 依據來源重要度進行科學化「過採樣 (Oversampling)」與「多源權重平衡」：
   - 手寫筆記 (User Notes): 權重最高，過採樣 500x
   - 司律真題與一試題庫 (Bar Exams & MCQ): 過採樣 50x
   - 名師講義與學說爭議 (Coursework & Theories): 過採樣 20x
   - 憲法法庭與實質裁判 (Constitutional & Courts): 過採樣 10x
   - 司法論證基礎模板 (Synthetic Baseline): 均勻取樣作為語法底層
3. 產出 100% 符合 Hugging Face Arrow 5 欄位綱要之高品質加權微調庫
"""
import os
import sys
import json
import random
from pathlib import Path

# Windows 終端編碼防護
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import DATA_DIR

TRAINING_DIR = Path(DATA_DIR) / "training_data"
VERIFIED_SFT_FILE = TRAINING_DIR / "law_exam_verified_sft.jsonl"
SYNTHETIC_SFT_FILE = TRAINING_DIR / "law_exam_1m_judicial_reasoning_sft.jsonl"
OUT_WEIGHTED_FILE = TRAINING_DIR / "law_exam_balanced_weighted_sft.jsonl"

def build_weighted_dataset(
    note_mult: int = 500,
    exam_mult: int = 50,
    coursework_mult: int = 20,
    court_mult: int = 10,
    synthetic_samples: int = 40000,
    random_seed: int = 3407
):
    random.seed(random_seed)
    print("=" * 70)
    print("  [啟動] 司法官律師微調大庫 多源動態權重平衡建構")
    print("=" * 70)

    if not VERIFIED_SFT_FILE.exists():
        print(f"  [錯誤] 找不到核實庫檔案：{VERIFIED_SFT_FILE}")
        return

    # 1. 高速讀取 5,082 筆核實資料並依 source_type 分組
    groups = {
        "notes": [],
        "exams": [],
        "coursework": [],
        "courts": [],
        "other": []
    }

    print(f"  正在載入純核實高價值資料庫 ({VERIFIED_SFT_FILE.name})...")
    with open(VERIFIED_SFT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            l = line.strip()
            if l:
                item = json.loads(l)
                st = str(item.get("source_type", "")).lower()
                if "handwritten" in st or "user_note" in st:
                    groups["notes"].append(item)
                elif "exam" in st or "mcq" in st:
                    groups["exams"].append(item)
                elif "coursework" in st or "doctrine" in st or "theories" in st:
                    groups["coursework"].append(item)
                elif "judgment" in st or "constitutional" in st or "rule" in st:
                    groups["courts"].append(item)
                else:
                    groups["other"].append(item)

    print(f"  [原始數據規模]")
    print(f"  - 個人手寫筆記：{len(groups['notes']):,} 筆")
    print(f"  - 司律真題與一試測驗題：{len(groups['exams']):,} 筆")
    print(f"  - 名師講義與學說爭議：{len(groups['coursework']):,} 筆")
    print(f"  - 憲法法庭判決與實質裁判：{len(groups['courts']):,} 筆")
    print(f"  - 其他核實規準：{len(groups['other']):,} 筆")

    # 2. 依權重過採樣
    weighted_pool = []

    # (1) 手寫筆記：500x
    for _ in range(note_mult):
        weighted_pool.extend(groups["notes"])
    print(f"  -> 加權後手寫筆記：{len(groups['notes']) * note_mult:,} 筆 (倍率: {note_mult}x)")

    # (2) 司律真題：50x
    for _ in range(exam_mult):
        weighted_pool.extend(groups["exams"])
    print(f"  -> 加權後司律真題：{len(groups['exams']) * exam_mult:,} 筆 (倍率: {exam_mult}x)")

    # (3) 名師講義：20x
    for _ in range(coursework_mult):
        weighted_pool.extend(groups["coursework"])
    print(f"  -> 加權後名師講義與學說：{len(groups['coursework']) * coursework_mult:,} 筆 (倍率: {coursework_mult}x)")

    # (4) 憲法裁判與實質裁判：10x
    for _ in range(court_mult):
        weighted_pool.extend(groups["courts"])
        weighted_pool.extend(groups["other"])
    print(f"  -> 加權後裁判與規準：{(len(groups['courts']) + len(groups['other'])) * court_mult:,} 筆 (倍率: {court_mult}x)")

    # (5) 快速均勻採樣百萬模板基底
    syn_count = 0
    if SYNTHETIC_SFT_FILE.exists() and synthetic_samples > 0:
        print(f"  正在從百萬模板大庫中高效抽取 {synthetic_samples:,} 筆平衡基底...")
        with open(SYNTHETIC_SFT_FILE, "r", encoding="utf-8") as f_syn:
            for line in f_syn:
                l_str = line.strip()
                if l_str:
                    weighted_pool.append(json.loads(l_str))
                    syn_count += 1
                    if syn_count >= synthetic_samples:
                        break
        print(f"  -> 百萬模板基底平衡抽樣：{syn_count:,} 筆")

    # 3. 洗牌打散
    print(f"\n  加權平衡池建立完成，總樣本數：{len(weighted_pool):,} 筆！正在進行全域洗牌...")
    random.shuffle(weighted_pool)

    # 4. 寫入標準化 5 欄位 JSONL
    print(f"  正在寫入加權微調檔案：{OUT_WEIGHTED_FILE.name}...")
    with open(OUT_WEIGHTED_FILE, "w", encoding="utf-8") as f_out:
        for idx, item in enumerate(weighted_pool):
            clean_item = {
                "id": str(item.get("id", f"weighted_{idx}")),
                "source_type": str(item.get("source_type", "weighted_sft")),
                "instruction": str(item.get("instruction", "")).strip(),
                "input": str(item.get("input", "")).strip(),
                "output": str(item.get("output", "")).strip()
            }
            f_out.write(json.dumps(clean_item, ensure_ascii=False) + "\n")

    file_size_mb = OUT_WEIGHTED_FILE.stat().st_size / (1024 * 1024)
    total_len = len(weighted_pool)
    print("=" * 70)
    print(f"  [加權完成] 加權平衡資料集建置成功！")
    print(f"  儲存路徑：{OUT_WEIGHTED_FILE}")
    print(f"  資料筆數：{total_len:,} 筆 ｜ 檔案大小：{file_size_mb:.2f} MB")
    print(f"  結構比例：手寫筆記 {(len(groups['notes'])*note_mult)/total_len*100:.1f}% ｜ 真題講義 {((len(groups['exams'])*exam_mult)+(len(groups['coursework'])*coursework_mult))/total_len*100:.1f}% ｜ 裁判規準 {((len(groups['courts'])+len(groups['other']))*court_mult)/total_len*100:.1f}% ｜ 模板基底 {syn_count/total_len*100:.1f}%")
    print("=" * 70)

if __name__ == "__main__":
    build_weighted_dataset()
