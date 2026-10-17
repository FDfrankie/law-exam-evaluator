"""
Master SFT Training Dataset Unified Merger
Combines all legal domain datasets:
1. Real Court Judgments & Rulings (scoring_standards)
2. National Statutes & Statutory Rules (236,949 articles)
3. 26 Legal Disciplines Master Theories & Jurists Knowledge
4. Constitutional Interpretations & Judgments
Outputs a unified training dataset ready for LLM fine-tuning:
G:\\我的雲端硬碟\\LawExamData\\training_data\\law_exam_master_sft_unified.json
"""
import os
import sys
import json
from pathlib import Path

from config import DATA_DIR

TRAINING_DIR = Path(DATA_DIR) / "training_data"

DATASET_FILES = [
    ("1M Real Court Judgment Legal Reasoning SFT", TRAINING_DIR / "law_exam_1m_judicial_reasoning_sft.jsonl"),
    ("Live Court Decisions SFT Stream", TRAINING_DIR / "law_exam_live_cases_sft.jsonl"),
    ("Live Court Decisions SFT", TRAINING_DIR / "law_exam_comprehensive_sft.json"),
    ("Statutory Rules Interpretation SFT", TRAINING_DIR / "law_exam_statutory_rules_sft.json"),
    ("Master Jurists & Theories SFT", TRAINING_DIR / "law_exam_master_theories_sft.json"),
    ("Constitutional Court & Grand Justices SFT", TRAINING_DIR / "law_exam_constitutional_sft.json")
]

def merge_datasets():
    print("=" * 70)
    print("  Merging All Taiwan Law Examination Datasets into Unified Corpus")
    print("=" * 70)

    unified_records = []
    stats = {}

    out_unified_jsonl = TRAINING_DIR / "law_exam_master_sft_unified.jsonl"
    f_out = open(out_unified_jsonl, "w", encoding="utf-8")

    total_count = 0
    for name, path in DATASET_FILES:
        if path.exists():
            try:
                count = 0
                if path.suffix == ".jsonl":
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            line_str = line.strip()
                            if line_str:
                                item = json.loads(line_str)
                                f_out.write(json.dumps(item, ensure_ascii=False) + "\n")
                                count += 1
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        items = json.load(f)
                        for item in items:
                            f_out.write(json.dumps(item, ensure_ascii=False) + "\n")
                            count += 1
                total_count += count
                print(f"  [LOADED] {name}: {count:,} samples from {path.name}")
            except Exception as e:
                print(f"  [WARN] Failed to load {path.name}: {e}")
        else:
            print(f"  [SKIPPED] {path.name} (not found yet)")

    f_out.close()

    total_bytes = out_unified_jsonl.stat().st_size
    print("\n" + "=" * 70)
    print(f"  [UNIFICATION COMPLETE]")
    print(f"  Total Unified SFT Triples: {total_count:,}")
    print(f"  Dataset File Size: {total_bytes / (1024*1024):.2f} MB")
    print(f"  Target File: {out_unified_jsonl}")
    print("=" * 70)

if __name__ == "__main__":
    merge_datasets()
