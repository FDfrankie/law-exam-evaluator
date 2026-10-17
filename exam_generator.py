"""
司律高階命題引擎（一試選擇題、二試申論題）與高分擬答生成模組
全面比照司律一試 300 題全真模擬題庫規格：
- 試題區全面隱匿法條條號與裁判字號（盲測情境實力）
- 支援任意題數（5, 10, 20, 30+ 題）分批穩定生成防截斷
- 支援標準單選題、綜合實例實事題組題
- 自動產出答案速查表與逐題詳解（含條號、釋字、憲判字、最高法院/行政法院裁判連結）
- 緊密結合考生手寫或文字筆記進行客製化命題
"""
import json
import re
from typing import Dict, Any, List, Optional, Callable
import google.generativeai as genai

from config import get_gemini_api_key, DEFAULT_GEMINI_MODEL

class LawExamGenerator:
    def __init__(self, model_name=DEFAULT_GEMINI_MODEL):
        self.api_key = get_gemini_api_key()
        if not self.api_key:
            raise ValueError("未檢測到 GEMINI_API_KEY！請在 Streamlit Cloud 的 Secrets 或 .env 中設定您的 API Key。")
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(model_name=model_name)

    def _parse_json_safely(self, text: str) -> Any:
        """安全解析模型返回的 JSON，自動過濾 markdown code fence 與修補微小語法問題"""
        clean = text.strip()
        # 移除 ```json 和 ```
        if "```" in clean:
            clean = re.sub(r"^```(?:json)?", "", clean, flags=re.MULTILINE)
            clean = re.sub(r"```$", "", clean, flags=re.MULTILINE).strip()
        
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            # 嘗試擷取最外層的 [ ... ] 或 { ... }
            match = re.search(r"(\[.*\]|\{.*\})", clean, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except Exception:
                    pass
            raise ValueError(f"無法解析為合法 JSON 格式，回傳片段：{clean[:200]}")

    def generate_stage1_exam(
        self,
        subject: str,
        topic: str,
        count: int = 5,
        question_mode: str = "標準單選題",
        notes_content: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Dict[str, Any]:
        """
        生成司律一試測驗題卷（支援批次生成以防 token 溢位）。
        :param subject: 考試科目
        :param topic: 核心考點主題
        :param count: 總出題數 (例如 5, 10, 20, 30 題)
        :param question_mode: "標準單選題" / "綜合案例實事實務題組題" / "全真綜合模考卷"
        :param notes_content: 考生筆記內容（可由手寫 OCR 或純文字傳入）
        :param progress_callback: 進度回報回調函數 callback(current, total)
        :return: 包含 questions 清單與答案速查表 answer_key 的字典
        """
        notes_instruction = ""
        if notes_content and notes_content.strip():
            notes_instruction = f"""
【考生個人學習筆記 / 爭點講義重點】：
\"\"\"
{notes_content.strip()[:4500]}
\"\"\"
【深度結合指令】：請深入提取上述考生筆記所載之爭點論理、肯否兩說、法條構成要件或判決字號，將其轉換為題目情境與選項陷阱！
"""

        batch_size = 5
        all_questions = []
        answer_key = {}

        total_batches = (count + batch_size - 1) // batch_size
        current_q_index = 1

        for batch_num in range(total_batches):
            this_batch_count = min(batch_size, count - len(all_questions))
            start_num = current_q_index
            end_num = current_q_index + this_batch_count - 1

            mode_spec = ""
            if question_mode == "綜合案例實事實務題組題":
                mode_spec = "請以『實務案例情境題組題』為主，設計一至二組跨法律關係事實，每組延伸 2~3 題關聯子題。"
            elif question_mode == "全真綜合模考卷":
                mode_spec = "請混合單題實例題與題組綜合實例題，完整覆蓋基礎構成要件判斷與實務深度爭點。"
            else:
                mode_spec = "每題均為獨立實例案例單選題，全面考核具體事實之行為定性、效力與法理辨析。"

            prompt = f"""
你是一位台灣「律師司法官高等考試一試」命題典試委員。
請針對科目【{subject}】，主題【{topic}】，依據司律一試全真全規格，出第 {start_num} 題至第 {end_num} 題（共 {this_batch_count} 題，四選一單選題）。

【命題嚴格規範（比照司法官律師考試標準）】：
1. 【試題區去條號、去字號】：題目情境題幹一律「隱匿法條條號」與「法院裁判字號」，純以具體案例事實盲測考生真實法理涵攝與爭點洞察力！
2. 【選項辨析深度】：四個選項 (A, B, C, D) 必須針對核心爭議、關鍵字眼或實務通說與少數說之差別設定深層辨析陷阱，僅有一最正確答案。
3. 【題型要求】：{mode_spec}
4. {notes_instruction}

請輸出嚴格的 JSON 陣列格式：
[
  {{
    "question_no": {start_num},
    "category": "考點類別（例如：[公私法性質]、[消滅時效]、[不法原因給付]、[裁量收縮]）",
    "case_facts": "若是題組題則填寫共通案件事實，若為單選獨立題則留空字串",
    "question": "具體案例情境描述及題目發問（盲測，不洩漏法條條號與裁判字號）...",
    "options": {{
      "A": "選項A文字...",
      "B": "選項B文字...",
      "C": "選項C文字...",
      "D": "選項D文字..."
    }},
    "answer": "A",
    "core_issue": "本題測驗之核心法學爭點（例如：公私法債權互相抵銷之容許性）",
    "explanation": "詳解說明：逐一分析 (A)(B)(C)(D) 為何正確或錯誤...",
    "legal_references": "精確之法律條號、最高法院/最高行政法院判決字號、司法院釋字、憲法法庭判決或大法庭裁定出處"
  }}
]
只輸出純 JSON，勿添加其他多餘文字。
"""
            resp = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.35,
                    response_mime_type="application/json"
                )
            )
            
            try:
                batch_items = self._parse_json_safely(resp.text)
            except Exception as pe:
                # 容錯重試一次
                resp_retry = self.model.generate_content(
                    prompt + "\n注意：請務必確保 JSON 語法完整合法且閉合！",
                    generation_config=genai.types.GenerationConfig(temperature=0.2, response_mime_type="application/json")
                )
                batch_items = self._parse_json_safely(resp_retry.text)

            if isinstance(batch_items, dict):
                batch_items = [batch_items]

            for item in batch_items:
                item["question_no"] = current_q_index
                ans = str(item.get("answer", "A")).strip().upper()
                if ans not in ["A", "B", "C", "D"]:
                    ans = "A"
                item["answer"] = ans
                answer_key[str(current_q_index)] = ans
                all_questions.append(item)
                current_q_index += 1

            if progress_callback:
                progress_callback(len(all_questions), count)

        return {
            "subject": subject,
            "topic": topic,
            "mode": question_mode,
            "total_count": len(all_questions),
            "questions": all_questions,
            "answer_key": answer_key
        }

    def generate_stage2_exam(self, subject: str, topic: str, notes_content: Optional[str] = None) -> Dict[str, Any]:
        """
        生成二試申論實例題（含事實背景、多角爭議、子題配分、核心爭點與評閱標準，支援筆記客製化命題）
        """
        notes_instruction = ""
        if notes_content and notes_content.strip():
            notes_instruction = f"""
【考生個人學習筆記 / 爭點講義重點】：
\"\"\"
{notes_content.strip()[:4500]}
\"\"\"
【特別命題指示】：請深入融合上述考生筆記中的核心法條、權威裁判判旨與學者爭點，編織進本題二試實例案件事實中！
"""

        prompt = f"""
你是一位台灣「律師司法官高等考試二試」命題召集人。
請針對科目【{subject}】，主題【{topic}】，設計一題標準的司律二試綜合實例申論題（滿分 100 分或 50 分標準題型）。
{notes_instruction}
題目必須具有高度法學深度，融合甲乙丙丁等複雜事實關係、多角法律爭端、最新憲法法庭判決或大法庭重要裁定爭點。

請輸出嚴格的 JSON 格式：
{{
  "subject": "{subject}",
  "total_points": 100,
  "question_facts": "詳細的案例事實描述與當事人各自主張（含人事時地物、契約簽訂、物權變動或訴訟程序等具體歷程）...",
  "sub_questions": [
    "子題（一）：試問甲得否依民法第...向乙主張何種權利？(50分)",
    "子題（二）：設若...試問法院應如何裁判？(50分)"
  ],
  "core_issues": [
    "爭點一：...",
    "爭點二：...",
    "爭點三：..."
  ],
  "scoring_criteria": "命題委員設定之評分級距要點與上位卷論述關鍵..."
}}
只輸出純 JSON。
"""
        response = self.model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.35,
                response_mime_type="application/json"
            )
        )
        return self._parse_json_safely(response.text)

    def generate_model_answer(self, question: str, subject: str = "") -> str:
        """
        針對二試申論題，生成具備上位卷（全國前1%錄取高分卷）水準的完美擬答
        包含嚴謹三段論法、各家學說對比、最高法院判決/大法庭裁定字號、事實具體細膩涵攝。
        """
        prompt = f"""
你是一位司律二試榜首兼法學權威講座名師。
請針對以下司律題目，撰寫一份足堪作為「全國最高分範本」的極致高分擬答。

【考試題目】：
{question}

【寫作規範要求】：
1. 【開標俐落】標題精準命中爭點與請求權基礎（例如：（一）甲得依民法第179條向乙請求返還...）
2. 【大前提嚴謹】精確引出法條構成要件，並對比「實務見解（引出代表性字號/決議/大法庭/憲判字）」與「學者有力見解（如王澤鑑、林山田、黃榮堅、陳敏、姜世明等通說有力說）」，並說明採何說之理由。
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

    @staticmethod
    def format_stage1_exam_markdown(exam_data: Dict[str, Any]) -> str:
        """將一試測驗卷排版成符合正式考試規格的 Markdown 文件（含試題區、答案速查表、詳解區）"""
        subject = exam_data.get("subject", "法學")
        topic = exam_data.get("topic", "綜合爭點")
        total = exam_data.get("total_count", len(exam_data.get("questions", [])))
        questions = exam_data.get("questions", [])
        answer_key = exam_data.get("answer_key", {})

        md = f"# 司律一試模擬測驗卷【{subject}】\n\n"
        md += f"**主題考點**：{topic} ｜ **總題數**：{total} 題 ｜ **命題標準**：依司律一試全真命題規格（盲測情境實力）\n\n"
        md += "---\n\n## 📝 第一部分：試題區（四選一單選題）\n\n"

        for q in questions:
            no = q.get("question_no")
            cat = q.get("category", "")
            cat_str = f" {cat}" if cat else ""
            md += f"### 第 {no} 題{cat_str}\n"
            if q.get("case_facts"):
                md += f"> **【題組案例背景】**\n> {q.get('case_facts')}\n\n"
            md += f"{q.get('question')}\n\n"
            
            opts = q.get("options", {})
            for key in ["A", "B", "C", "D"]:
                if key in opts:
                    md += f"- **({key})** {opts[key]}\n"
            md += "\n"

        md += "---\n\n## 📋 第二部分：標準答案速查表\n\n"
        # 格式化答案表 (每 5 題一行)
        key_items = []
        for i in range(1, total + 1):
            key_items.append(f"**第 {i} 題**：`({answer_key.get(str(i), 'A')})`")
            if i % 5 == 0 or i == total:
                md += " ｜ ".join(key_items) + "\n\n"
                key_items = []

        md += "---\n\n## 💡 第三部分：逐題詳細解析與實務裁判出處\n\n"
        for q in questions:
            no = q.get("question_no")
            ans = q.get("answer")
            issue = q.get("core_issue", "")
            expl = q.get("explanation", "")
            refs = q.get("legal_references", "")

            md += f"### 【第 {no} 題解析】 正確答案：`({ans})`\n"
            if issue:
                md += f"- **核心爭點**：{issue}\n"
            if refs:
                md += f"- **規範法條與實務裁判字號**：{refs}\n"
            md += f"\n**【解析內容】**：\n{expl}\n\n"
            md += "---\n\n"

        return md
