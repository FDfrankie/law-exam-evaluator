"""
司律手寫試卷自動評分核心引擎
使用官方 Google GenAI SDK (支援 Gemini 2.0 Flash / Flash Latest)：
1. 繁體手寫辨識與專有名詞校正 (支援圖片、PDF 或 Word 文字)
2. 司律閱卷級距評分（爭點識別、法學論述/三段論法、學說實務見解、事實涵攝）
3. 輸出結構化診斷報告與建議
"""
import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from PIL import Image

try:
    from google import genai
    from google.genai import types as genai_types
    USE_MODERN_GENAI = True
except Exception:
    try:
        import google.generativeai as legacy_genai
    except Exception:
        legacy_genai = None
    USE_MODERN_GENAI = False

from config import get_gemini_api_key, REPORTS_DIR, DEFAULT_GEMINI_MODEL, get_gemini_models_to_try

class LawExamEvaluator:
    def __init__(self, model_name=DEFAULT_GEMINI_MODEL):
        self.api_key = get_gemini_api_key()
        if not self.api_key:
            raise ValueError("未檢測到 GEMINI_API_KEY！請在 Streamlit Cloud 的 Secrets 或 .env 中設定您的 API Key。")
        self.model_name = model_name
        self.reports_dir = Path(REPORTS_DIR)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        if USE_MODERN_GENAI:
            self.client = genai.Client(api_key=self.api_key)
        else:
            legacy_genai.configure(api_key=self.api_key)
            self.model = legacy_genai.GenerativeModel(model_name=self.model_name)

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
現在請依據國家考試最高評閱標準，評閱考生提交的作答內容（包含手寫圖片照片謄錄或電子文字稿）。

【核心評核標準與裁判引用準則（極度重要）】：
1. 【以他人高分擬答/評分標準為最優先錨定基準】：
   若本題提供有「評分要點/參考擬答（他人擬答）」，必須以此他人高分擬答之爭點廣度、推論深度與上位法理架構作為「唯一真理與錨定標準」。考生若能充分涵蓋他人擬答之核心爭點與法律效果，即應給予高分；若遺漏他人擬答列為重要爭點者，務必記入 missed_issues 並扣減爭點意識分數。
2. 【司法裁判權威位階原則】：
   在評閱論理及給予優化建議（suggested_revision）時，若引用或要求考生引用法院判決，必須嚴格依照以下最高位階順序：
   - 第一位階：憲法法院裁判 / 司法院大法官解釋（憲法位階最高拘束力）
   - 第二位階：最高法院民刑大法庭裁定 / 最高行政法院大法庭裁定（終審法院統一見解）
   - 第三位階：最高法院精選裁判 / 具有參考價值裁判 / 經典判例 / 決議
   - 嚴格禁忌：切勿引用高等法院或地方法院等下級審判決作為主要立論權威！
3. 【法律條文引用排版規範（極重要）】：
   在評閱論述及改寫示範（suggested_revision）中，凡引用法律條文，嚴禁將各項、各款黏連成一大段！必須清楚分項分款分行（每項獨立成段，各款一、二、三...獨立換行縮排），層次清晰分明。

評分核心四維度（各25分，滿分100分）：
1. 【爭點意識（Issue Spotting）】是否精準發現法律事實關鍵衝突？標題開標是否俐落命中爭點（與參考擬答/他人擬答相互呼應）？
2. 【法學推論與架構（Legal Reasoning）】是否遵循嚴謹三段論法（大前提：法規依據、小前提：具體事實、結論），法理連貫不矛盾？
3. 【實務與學說見解（Precedent & Scholarship）】是否能精準引述憲法法庭裁判、大法庭裁定或最高法院精選裁判，並對比通說與有力學說？
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
  "suggested_revision": "針對考生的論述，對齊他人高分擬答並以大法庭/憲判字/最高法院精選裁判為權威基準，給予一段具體而精闢的開標與涵攝改寫示範..."
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

        response_text = None
        models_to_try = get_gemini_models_to_try(self.model_name)
        last_err = None
        for m_name in models_to_try:
            try:
                if USE_MODERN_GENAI:
                    config = genai_types.GenerateContentConfig(
                        temperature=0.2,
                        response_mime_type="application/json"
                    )
                    resp = self.client.models.generate_content(
                        model=m_name,
                        contents=user_content,
                        config=config
                    )
                    response_text = resp.text
                else:
                    cur_model = legacy_genai.GenerativeModel(model_name=m_name)
                    gen_config = legacy_genai.types.GenerationConfig(
                        temperature=0.2,
                        response_mime_type="application/json"
                    )
                    resp = cur_model.generate_content(user_content, generation_config=gen_config)
                    response_text = resp.text
                break
            except Exception as e:
                err_str = str(e).lower()
                if any(k in err_str for k in ["api_key", "unauthorized", "permission_denied", "forbidden", "403", "401"]):
                    raise RuntimeError(f"Gemini API 認證或金鑰錯誤，請檢查 GEMINI_API_KEY：{e}") from e
                last_err = e
                continue

        if response_text is None:
            raise RuntimeError(f"所有 Gemini 模型呼叫均失敗，最後錯誤: {last_err}")

        try:
            result_json = json.loads(response_text)
        except Exception:
            try:
                clean_text = response_text.strip().replace("```json", "").replace("```", "")
                result_json = json.loads(clean_text)
            except Exception:
                result_json = {
                    "error": "JSON 解析失敗",
                    "raw_response": response_text[:2000],
                    "total_score": 0,
                    "grade_level": "無法評定"
                }

        report_file = self.reports_dir / f"report_{os.getpid()}_{abs(hash(question_text[:20]))}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(result_json, f, ensure_ascii=False, indent=2)

        return result_json
