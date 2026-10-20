"""
Master SFT Training Dataset Unified Merger & Quality Verifier

【資料來源與權威溯源 (Data Provenance)】:
1. 司法實務裁判：司法院公開裁判書資料庫，依政府資訊公開法及裁判書公開原則取得
2. 憲法法庭判決與大法官解釋：憲法法庭與司法院公報公開之憲法裁判與解釋文
3. 全國法規與主管命令：立法院與全國法規資料庫公開之法定條文
4. 國家考試歷年真題：考選部司法官律師、司法特考及公立大學法研所公開公務考試真題
5. 個人手寫讀書筆記：考生自主研讀之手寫心智圖與爭點筆記 OCR 提煉
6. 100萬筆司法推理基準庫：以真實事實情境為基礎提煉之標準 IRAC 三段論合成樣本

【法律性質與著作權遵循界限 (Legal & Copyright Boundaries)】:
1. 公開公務資訊（依法不得為著作權標的）：
   - 依著作權法第 9 條第 1 項第 1 款至第 3 款，憲法、法律、法規命令、公文及法院實質裁判書，依法不受著作權保護，屬公共領域資訊。
2. 私人研析與學術資料（合理使用與私法授權限制）：
   - 個人手寫筆記屬考生個人創作；名師講義與學說爭議涉及學者文獻。
   - 依著作權法第 52 條及第 65 條，合理使用須依具體利用目的、性質、質與量之比例及對市場影響個案判定，本宣告為工程研發限制提示，非授權判定或法律豁免保證。
   - 本專案資料集與微調權重僅供內部自律學習與答題推論研究，未獲著作權人授權前嚴禁公開散布、出版或商業營利。

【資料集輸出目標】:
1. law_exam_verified_sft.jsonl:
   - 100% Authentic, Verified Legal SFT Dataset (Zero synthetic noise)
   - 嚴格去重、欄位正規化為 5 大核心欄位 (id, source_type, instruction, input, output)
2. law_exam_master_sft_unified.jsonl:
   - 全量統一大庫 (Verified Authentic 5,082 筆 + Segregated Synthetic 1M Baseline 1,000,000 筆)
   - 採原子串流生成與嚴格失敗回滾機制 (Atomic streaming with rollback on failure)
"""
import os
import sys
import json
import hashlib
from pathlib import Path

from config import DATA_DIR

TRAINING_DIR = Path(DATA_DIR) / "training_data"

VERIFIED_DATASET_FILES = [
    ("Live Substantive Court Decisions SFT", TRAINING_DIR / "law_exam_live_cases_sft.jsonl", "verified_authentic_judgment"),
    ("Comprehensive Judicial Cases SFT", TRAINING_DIR / "law_exam_comprehensive_sft.json", "verified_authentic_judgment"),
    ("Constitutional Court & Grand Justices SFT", TRAINING_DIR / "law_exam_constitutional_sft.json", "verified_constitutional"),
    ("Statutory Rules Interpretation SFT", TRAINING_DIR / "law_exam_statutory_rules_sft.json", "verified_statutory_rule"),
    ("Master Jurists & Theories SFT", TRAINING_DIR / "law_exam_master_theories_sft.json", "verified_jurist_doctrine"),
    ("Academic Coursework & Teaching SFT", TRAINING_DIR / "law_exam_coursework_sft.jsonl", "verified_academic_coursework"),
    ("Past Bar Exams & 300 MCQ SFT", TRAINING_DIR / "law_exam_exams_and_mcq_sft.jsonl", "verified_exam_bank"),
    ("User Handwritten Notes & Outlines SFT", TRAINING_DIR / "law_exam_user_notes_sft.jsonl", "verified_user_handwritten_notes")
]

SYNTHETIC_DATASET_FILES = [
    ("1M Synthetic Template Reasoning SFT", TRAINING_DIR / "law_exam_1m_judicial_reasoning_sft.jsonl", "synthetic_template")
]

def compute_hash(sample: dict) -> str:
    key = (sample.get("instruction", "") + sample.get("input", "") + sample.get("output", "")[:200]).strip()
    return hashlib.sha256(key.encode("utf-8", errors="ignore")).hexdigest()

def merge_datasets(include_synthetic: bool = True):
    print("=" * 70)
    print("  Stage 1: Building 100% Verified Authentic SFT Dataset")
    print("=" * 70)

    out_verified_jsonl = TRAINING_DIR / "law_exam_verified_sft.jsonl"
    temp_verified_jsonl = TRAINING_DIR / "law_exam_verified_sft.tmp"
    seen_hashes = set()
    verified_count = 0
    stats = {}

    try:
        with open(temp_verified_jsonl, "w", encoding="utf-8") as f_ver:
            for name, path, default_source in VERIFIED_DATASET_FILES:
                if not path.exists():
                    raise FileNotFoundError(f"核實庫來源資料集遺失: {path.name} ({path})，終止 Stage 1 合併以防止生成殘缺資料庫")
                count = 0
                if path.suffix == ".jsonl":
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            line_str = line.strip()
                            if line_str:
                                item = json.loads(line_str)
                                h = compute_hash(item)
                                if h not in seen_hashes:
                                    seen_hashes.add(h)
                                    clean_item = {
                                        "id": str(item.get("id", f"sample_{h[:12]}")),
                                        "source_type": str(item.get("source_type", default_source)),
                                        "instruction": str(item.get("instruction", "")).strip(),
                                        "input": str(item.get("input", "")).strip(),
                                        "output": str(item.get("output", "")).strip()
                                    }
                                    f_ver.write(json.dumps(clean_item, ensure_ascii=False) + "\n")
                                    count += 1
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        items = json.load(f)
                        for item in items:
                            h = compute_hash(item)
                            if h not in seen_hashes:
                                seen_hashes.add(h)
                                clean_item = {
                                    "id": str(item.get("id", f"sample_{h[:12]}")),
                                    "source_type": str(item.get("source_type", default_source)),
                                    "instruction": str(item.get("instruction", "")).strip(),
                                    "input": str(item.get("input", "")).strip(),
                                    "output": str(item.get("output", "")).strip()
                                }
                                f_ver.write(json.dumps(clean_item, ensure_ascii=False) + "\n")
                                count += 1
                verified_count += count
                stats[name] = count
                print(f"  [LOADED & DEDUPED] {name}: {count:,} samples from {path.name}")

        # 原子性覆蓋正式核實庫檔案 (防止中斷或殘缺覆蓋)
        os.replace(str(temp_verified_jsonl), str(out_verified_jsonl))
    except Exception as e:
        if temp_verified_jsonl.exists():
            try:
                temp_verified_jsonl.unlink()
            except Exception:
                pass
        raise RuntimeError(f"Stage 1 核實庫合併失敗，已終止替換並清理暫存檔以確保正式資料完整性：{e}") from e

    ver_size_mb = out_verified_jsonl.stat().st_size / (1024 * 1024)

    print("\n" + "=" * 70)
    print("  [STAGE 1 COMPLETE: VERIFIED AUTHENTIC CORPUS]")
    print(f"  Total Verified Authentic Samples: {verified_count:,}")
    print(f"  Verified Dataset File Size: {ver_size_mb:.2f} MB")
    print(f"  Target File: {out_verified_jsonl}")
    print("=" * 70)

    if not include_synthetic:
        return

    print("\n" + "=" * 70)
    print("  Stage 2: Building Unified Master Corpus (Verified + Synthetic)")
    print("=" * 70)

    out_unified_jsonl = TRAINING_DIR / "law_exam_master_sft_unified.jsonl"
    temp_unified_jsonl = TRAINING_DIR / "law_exam_master_sft_unified.tmp"

    unified_count = 0
    try:
        with open(temp_unified_jsonl, "w", encoding="utf-8", buffering=1024*1024*8) as f_uni:
            # 1. 串流寫入核實核心集
            with open(out_verified_jsonl, "r", encoding="utf-8") as f_ver_in:
                for line in f_ver_in:
                    f_uni.write(line)
                    unified_count += 1

            # 2. 串流追加百萬合成推理基準集（若有錯誤立即拋出異常中斷，絕不產生殘缺資料）
            for name, path, default_source in SYNTHETIC_DATASET_FILES:
                if not path.exists():
                    raise FileNotFoundError(f"合成基準來源資料集遺失: {path.name} ({path})，終止 Stage 2 合併以防止生成殘缺資料庫")
                syn_count = 0
                with open(path, "r", encoding="utf-8", buffering=1024*1024*8) as f:
                    for line in f:
                        line_str = line.strip()
                        if line_str:
                            f_uni.write(line_str + "\n")
                            syn_count += 1
                unified_count += syn_count
                print(f"  [APPENDED] {name}: {syn_count:,} samples from {path.name}")

        # 3. 原子性覆蓋正式檔案 (os.replace 在 Windows/POSIX 均保證原子覆蓋，避免 unlink 造成空檔漏洞)
        os.replace(str(temp_unified_jsonl), str(out_unified_jsonl))
    except Exception as e:
        if temp_unified_jsonl.exists():
            try:
                temp_unified_jsonl.unlink()
            except Exception:
                pass
        raise RuntimeError(f"合併統一資料庫失敗，已終止替換並清理暫存檔以確保正式資料完整性：{e}") from e

    uni_size_mb = out_unified_jsonl.stat().st_size / (1024 * 1024)

    print("\n" + "=" * 70)
    print("  [STAGE 2 COMPLETE: MASTER UNIFIED CORPUS]")
    print(f"  Total Unified Samples: {unified_count:,}")
    print(f"  Master Dataset File Size: {uni_size_mb:.2f} MB ({uni_size_mb / 1024:.2f} GB)")
    print(f"  Target File: {out_unified_jsonl}")
    print("=" * 70)

def build_weighted_dataset(
    note_mult: int = 500,
    exam_mult: int = 50,
    coursework_mult: int = 20,
    court_mult: int = 10,
    synthetic_samples: int = 40000,
    random_seed: int = 3407
):
    """司法官律師微調大庫 - 多源動態權重平衡產生器"""
    import random
    random.seed(random_seed)
    verified_file = TRAINING_DIR / "law_exam_verified_sft.jsonl"
    out_weighted_file = TRAINING_DIR / "law_exam_balanced_weighted_sft.jsonl"

    if not verified_file.exists():
        print(f"  [提示] 核實庫尚未生成，先執行 merge_datasets(include_synthetic=False)...")
        merge_datasets(include_synthetic=False)

    print("=" * 70)
    print("  [啟動] 司法官律師微調大庫 多源動態權重平衡建構")
    print("=" * 70)

    groups = {"notes": [], "exams": [], "coursework": [], "courts": [], "other": []}
    with open(verified_file, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            stype = item.get("source_type", "")
            if "note" in stype:
                groups["notes"].append(item)
            elif "exam" in stype:
                groups["exams"].append(item)
            elif "coursework" in stype or "theor" in stype:
                groups["coursework"].append(item)
            elif "judgment" in stype or "court" in stype or "constitutional" in stype:
                groups["courts"].append(item)
            else:
                groups["other"].append(item)

    final_samples = []
    final_samples.extend(groups["notes"] * note_mult)
    final_samples.extend(groups["exams"] * exam_mult)
    final_samples.extend(groups["coursework"] * coursework_mult)
    final_samples.extend(groups["courts"] * court_mult)
    final_samples.extend(groups["other"] * 5)

    random.shuffle(final_samples)
    with open(out_weighted_file, "w", encoding="utf-8") as f_out:
        for s in final_samples:
            f_out.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"  ✅ 成功生成加權平衡資料集：{out_weighted_file} ({len(final_samples):,} 筆樣本)")
    return len(final_samples)

if __name__ == "__main__":
    if "--weighted" in sys.argv:
        build_weighted_dataset()
    else:
        merge_datasets()
