"""
司律出題（一試選擇題、二試申論題）與高分擬答生成引擎
"""
import json
from typing import Dict, Any, List, Optional
import google.generativeai as genai
from config import get_gemini_api_key

class LawExamGenerator:
    def __init__(self, model_name="gemini-2.0-flash"):
        self.api_key = get_gemini_api_key()
        if not self.api_key:
            raise ValueError("未檢測到 GEMINI_API_KEY！請在 Streamlit Cloud 的 Secrets 或 .env 中設定您的 API Key。")
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(model_name=model_name)

    def generate_stage1_exam(self, subject: str, topic: str, count: int = 3) -> List[Dict[str, Any]]:
        """
        生成一試選擇題（單選題，4個選項，含詳解與法條依據）
        """
        prompt = f"""
你是一位台灣「律師司法官高等考試一試」命題委員。
請針對科目【{subject}】，主題【{topic}】，出 {count} 題具備司律難度的四選一選擇題。

每題必須包含：
1. 題幹（情境案例或法理判斷）
2. 四個選項 (A, B, C, D)
3. 正確答案
4. 逐項詳細解析（需精確引用相關法條、最高法院判決字號或實務大法庭見解）

請輸出嚴格的 JSON 陣列格式：
[
  {{
    "question": "題目情境描述...",
    "options": {{
      "A": "選項A文字",
      "B": "選項B文字",
      "C": "選項C文字",
      "D": "選項D文字"
    }},
    "answer": "A",
    "explanation": "解析內容，包含法條依據與各選項為何正確或錯誤的說明..."
  }}
]
只輸出純 JSON，勿添加其他多餘文字。
"""
        response = self.model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.4,
                response_mime_type="application/json"
            )
        )
        try:
            return json.loads(response.text)
        except Exception:
            clean = response.text.strip().replace("```json", "").replace("```", "")
            return json.loads(clean)

    def generate_stage2_exam(self, subject: str, topic: str) -> Dict[str, Any]:
        """
        生成二試申論實例題（含配分、事實關係、核心爭點與閱卷標準）
        """
        prompt = f"""
你是一位台灣「律師司法官高等考試二試」命題召集人。
請針對科目【{subject}】，主題【{topic}】，設計一題標準的司律二試綜合實例申論題（配分通常為 50~75 分或 100 分題型）。

題目必須具有深度，融合甲乙丙丁等複雜事實關係、多角法律爭議、最新憲判字或大法庭重要爭點。

請輸出嚴格的 JSON 格式：
{{
  "subject": "{subject}",
  "total_points": 50,
  "question_facts": "詳細的案例事實描述與當事人主張...",
  "sub_questions": [
    "子題一：試問甲得否依民法第...向乙主張何種權利？(25分)",
    "子題二：設若...試問法院應如何裁判？(25分)"
  ],
  "core_issues": [
    "爭點一：...",
    "爭點二：..."
  ],
  "scoring_criteria": "命題委員設定之評分要點與得心應手論述關鍵..."
}}
只輸出純 JSON。
"""
        response = self.model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.4,
                response_mime_type="application/json"
            )
        )
        try:
            return json.loads(response.text)
        except Exception:
            clean = response.text.strip().replace("```json", "").replace("```", "")
            return json.loads(clean)

    def generate_model_answer(self, question: str, subject: str = "") -> str:
        """
        針對二試申論題，生成具備上位卷（高分錄取卷）水準的完美擬答
        包含嚴謹三段論法、各家學說、最高法院判決/大法庭裁定字號、事實具體涵攝。
        """
        prompt = f"""
你是一位司律二試榜首兼法學補教名師。
請針對以下司律題目，撰寫一份足堪作為「全國最高分範本」的極致高分擬答。

【考試題目】：
{question}

【寫作規範要求】：
1. 【開標俐落】標題精準命中爭點與請求權基礎（例如：（一）甲得依民法第179條向乙請求返還...）
2. 【大前提嚴謹】精確引出法條構成要件，並對比「實務見解（引出代表性字號/決議/大法庭）」與「學者有力見解（如王澤鑑、林山田、黃榮堅、陳敏等通說有力說）」，並說明採何說之理由。
3. 【小前提事實涵攝細膩】將題幹事實人事時地物嚴密套入構成要件，嚴禁只有法條沒有涵攝。
4. 【結論明確】一錘定音，直接回應題目發問。

請直接以排版工整之 Markdown 格式輸出擬答全文。
"""
        response = self.model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3
            )
        )
        return response.text
