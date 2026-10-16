"""
訓練資料集生成器 (Dataset Generator for SFT / LoRA)
將題目、評分規準、實務見解與學生試卷結構化合成為標準 Alpaca / ShareGPT 格式。
儲存至 Google Drive 的 training_data 目錄，供 Google Colab 直接讀取進行模型訓練。
"""
import os
import json
from pathlib import Path
from typing import List, Dict, Any
from config import GOOGLE_DRIVE_DATA_DIR, RAW_DATA_DIR, REPORTS_DIR

TRAIN_DATA_DIR = Path(GOOGLE_DRIVE_DATA_DIR) / "training_data"
TRAIN_DATA_DIR.mkdir(parents=True, exist_ok=True)

class LawDatasetBuilder:
    def __init__(self, output_dir=TRAIN_DATA_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def create_instruction_sample(self, question: str, student_answer: str, evaluation: Dict[str, Any]) -> Dict[str, Any]:
        """
        建立一筆標準指令微調 (SFT) 樣本
        """
        system_instruction = (
            "你是一位資深的台灣「司法官暨律師高等考試二試」國家考試典試閱卷委員。"
            "請依據爭點意識、三段論法邏輯、學說實務見解以及具體事實涵攝，對考生的作答進行精闢專業的評分與診斷。"
        )
        user_input = f"【考試題目】：\n{question}\n\n【考生手寫/答題謄錄】：\n{student_answer}"
        output_response = json.dumps(evaluation, ensure_ascii=False, indent=2)

        return {
            "instruction": system_instruction,
            "input": user_input,
            "output": output_response
        }

    def export_alpaca_dataset(self, filename="prepared_sft_dataset.json") -> Path:
        """
        從已累積的評分紀錄與試題資料庫，自動匯出完整的訓練集 JSON
        """
        dataset = []
        reports = list(Path(REPORTS_DIR).glob("*.json"))
        
        for r_path in reports:
            try:
                with open(r_path, "r", encoding="utf-8") as f:
                    eval_data = json.load(f)
                transcription = eval_data.get("transcription", "")
                
                # 建立訓練條目
                # Use actual question from the report if available
                actual_question = eval_data.get("question_text", eval_data.get("question", "司律申論試題"))
                sample = self.create_instruction_sample(
                    question=actual_question,
                    student_answer=transcription,
                    evaluation=eval_data
                )
                dataset.append(sample)
            except Exception as e:
                print(f"[ERROR] Failed parsing report {r_path}: {e}")

        target_file = self.output_dir / filename
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(dataset, f, ensure_ascii=False, indent=2)

        print(f"[EXPORTED] {target_file} (count: {len(dataset)})")
        return target_file

if __name__ == "__main__":
    builder = LawDatasetBuilder()
    builder.export_alpaca_dataset()
