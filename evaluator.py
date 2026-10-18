"""
司律手寫試卷自動評分核心引擎
使用 Gemini 2.0 Flash 多模態視覺模型：
1. 繁體手寫辨識與專有名詞校正 (支援圖片、PDF 或 Word 文字)
2. 司律閱卷級距評分（爭點識別、法學論述/三段論法、學說實務見解、事實涵攝）
3. 輸出結構化診斷報告與建議
"""
import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
import google.generativeai as genai
from PIL import Image

from config import get_gemini_api_key, REPORTS_DIR, DEFAULT_GEMINI_MODEL

class LawExamEvaluator:
    def __init__(self, model_name=DEFAULT_GEMINI_MODEL):
        self.api_key = get_gemini_api_key()
        if not self.api_key:
            raise ValueError("未檢測到 GEMINI_API_KEY！請在 Streamlit Cloud 的 Secrets 或 .env 中設定您的 API Key。")
        genai.configure(api_key=self.api_key)
        self.model_name = model_name
        self.reports_dir = Path(REPORTS_DIR)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.model = genai.GenerativeModel(model_name=self.model_name)

    def evaluate_submission(
        self,
        images: Optional[List[Image.Image]] = None,
        submission_text: Optional[str] = None,
        question_text: str = "",
        standard_rubric: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        評閱考生的作答（可傳入手寫圖片清單，或 Word/PDF 純文字，或兩者混合）
        """
        system_prompt = """
你是一位資深的台灣「司法官暨律師高等考試二試」國家考試典試/閱卷委員。
現在請依據國家考試評閱標準，評閱考生提交的作答內容（包含手寫圖片照片謄錄或電子文字稿）。

評分核心四維度（各25分，滿分100分）：
1. 【爭點意識（Issue Spotting）】是否精準發現法律事實關鍵衝突？標題開標是否俐落命中爭點？
2. 【法學推論與架構（Legal Reasoning）】是否遵循嚴謹三段論法（大前提：法規依據、小前提：具體事實、結論），法理連貫不矛盾？
3. 【實務與學說見解（Precedent & Scholarship）】是否能精準引述最高法院具有參考價值之裁判/大法庭裁定/憲法法庭判決/通說見解，並能陳述少數說或有力說？
4. 【事實涵攝（Subsumption）】是否充分運用題目給予之細部事實逐一比對構成要件，而非空泛抄法條？

【輸出要求】：
請務必輸出繁體中文，並以嚴格的 JSON 格式回應，符合以下欄位規範：
{
  "transcription": "手寫內容完整文字排版謄錄（若為文字稿則為整理後之作答全文）...",
  "total_score": 82,
  "grade_level": "上位",
  "issue_spotting_score": 22,
  "legal_reasoning_score": 20,
  "precedent_scholarship_score": 20,
  "subsumption_score": 20,
  "identified_issues": ["爭點1", "爭點2"],
  "missed_issues": ["漏掉的爭點1"],
  "strengths": ["亮點1", "亮點2"],
  "weaknesses": ["缺失1", "缺失2"],
  "suggested_revision": "針對考生的論述，給予一段具體而精闢的改寫與優化建議..."
}
只輸出純 JSON，勿添加其他多餘 markdown 程式碼區塊外說明。
"""

        user_content = [
            system_prompt,
            f"【考試題目】：\n{question_text}\n\n",
        ]

        if standard_rubric:
            user_content.append(f"【評分要點/參考擬答】：\n{standard_rubric}\n\n")

        if submission_text:
            user_content.append(f"【考生的作答文字稿內容】：\n{submission_text}\n\n")

        if images:
            user_content.append("【以下為考生實際手寫作答圖片】：")
            user_content.extend(images)

        gen_config = genai.types.GenerationConfig(
            temperature=0.2,
            response_mime_type="application/json"
        )

        response = None
        models_to_try = [self.model_name]
        for m in ["gemini-2.5-flash", "gemini-2.5-pro"]:
            if m not in models_to_try:
                models_to_try.append(m)

        last_err = None
        for m_name in models_to_try:
            try:
                cur_model = genai.GenerativeModel(model_name=m_name)
                response = cur_model.generate_content(user_content, generation_config=gen_config)
                break
            except Exception as e:
                err_str = str(e).lower()
                if any(k in err_str for k in ["api_key", "unauthorized", "permission_denied", "forbidden", "403", "401"]):
                    raise RuntimeError(f"Gemini API 認證或金鑰錯誤，請檢查 GEMINI_API_KEY：{e}") from e
                last_err = e
                continue

        if response is None:
            raise RuntimeError(f"所有 Gemini 模型呼叫均失敗，最後錯誤: {last_err}")

        try:
            result_json = json.loads(response.text)
        except Exception:
            try:
                clean_text = response.text.strip().replace("```json", "").replace("```", "")
                result_json = json.loads(clean_text)
            except Exception:
                result_json = {
                    "error": "JSON 解析失敗",
                    "raw_response": response.text[:2000],
                    "total_score": 0,
                    "grade_level": "無法評定"
                }

        report_file = self.reports_dir / f"report_{os.getpid()}_{abs(hash(question_text[:20]))}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(result_json, f, ensure_ascii=False, indent=2)

        return result_json
