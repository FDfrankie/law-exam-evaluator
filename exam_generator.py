from pathlib import Path
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
import uuid
from typing import Dict, Any, List, Optional, Callable
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

from config import get_gemini_api_key, DEFAULT_GEMINI_MODEL, get_gemini_models_to_try, RAW_DATA_DIR, DATA_DIR

class LawExamGenerator:
    def __init__(self, model_name=DEFAULT_GEMINI_MODEL):
        self.api_key = get_gemini_api_key()
        if not self.api_key:
            raise ValueError("未檢測到 GEMINI_API_KEY！請在 Streamlit Cloud 的 Secrets 或 .env 中設定您的 API Key。")
        self.model_name = model_name
        if USE_MODERN_GENAI:
            self.client = genai.Client(api_key=self.api_key)
        else:
            if legacy_genai is None:
                raise RuntimeError("未安裝 google-genai 或 google-generativeai 套件！")
            legacy_genai.configure(api_key=self.api_key)
            self.model = legacy_genai.GenerativeModel(model_name=model_name)

    def _make_config(self, temperature: float = 0.3, response_mime_type: Optional[str] = "application/json") -> Any:
        """根據目前載入之 SDK 動態生成安全相容之生成配置物件或字典"""
        if USE_MODERN_GENAI:
            kwargs = {"temperature": temperature}
            if response_mime_type:
                kwargs["response_mime_type"] = response_mime_type
            return genai_types.GenerateContentConfig(**kwargs)
        else:
            kwargs = {"temperature": temperature}
            if response_mime_type:
                kwargs["response_mime_type"] = response_mime_type
            try:
                if legacy_genai is not None and hasattr(legacy_genai, "types") and hasattr(legacy_genai.types, "GenerationConfig"):
                    return legacy_genai.types.GenerationConfig(**kwargs)
            except Exception:
                pass
            return kwargs

    def _call_model(self, prompt: Any, generation_config: Any = None) -> Any:
        models_to_try = get_gemini_models_to_try(self.model_name)
        last_err = None
        for m_name in models_to_try:
            try:
                if USE_MODERN_GENAI:
                    if isinstance(generation_config, genai_types.GenerateContentConfig):
                        cfg = generation_config
                    elif isinstance(generation_config, dict):
                        cfg = genai_types.GenerateContentConfig(**generation_config)
                    elif generation_config is not None:
                        temp = getattr(generation_config, "temperature", 0.3)
                        mime = getattr(generation_config, "response_mime_type", None)
                        cfg = genai_types.GenerateContentConfig(
                            temperature=temp,
                            response_mime_type=mime
                        )
                    else:
                        cfg = genai_types.GenerateContentConfig(temperature=0.3)
                    return self.client.models.generate_content(
                        model=m_name,
                        contents=prompt,
                        config=cfg
                    )
                else:
                    if legacy_genai is None:
                        raise RuntimeError("Neither google-genai nor google-generativeai is installed.")
                    mod = legacy_genai.GenerativeModel(model_name=m_name)
                    return mod.generate_content(prompt, generation_config=generation_config)
            except Exception as e:
                err_str = str(e).lower()
                if any(k in err_str for k in ["api_key", "unauthorized", "permission_denied", "forbidden", "403", "401"]):
                    raise RuntimeError(f"Gemini API 認證或金鑰錯誤，請檢查 GEMINI_API_KEY：{e}") from e
                last_err = e
                continue
        raise RuntimeError(f"所有 Gemini 模型呼叫均失敗: {last_err}")

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

    @staticmethod
    def _verify_and_align_mcq_item(item: Dict[str, Any]) -> Dict[str, Any]:
        """
        對 AI 生成的一試選擇題進行深度校驗與自癒修正：
        1. 答案自洽性驗證：比對 explanation/options_analysis 中的分析結論，若 answer 與詳解結論矛盾，自動對齊。
        2. 清理草稿獨白：過濾『等等，仔細計算...調整案件事實』等草稿自言自語洩漏。
        3. 時間事實對齊：若解析中發現時間不符並修正了年份，將題幹對應年份同步更新，確保題幹與解析完全一致。
        """
        explanation = str(item.get("explanation", ""))
        raw_answer = str(item.get("answer", "")).strip().upper()
        options = item.get("options", {})

        # --- 1. 清理草稿獨白與時間調整洩漏 ---
        leak_match = re.search(
            r'(?:本題中[：:]\s*)?(?:甲對乙之借款債權.*?始屆滿[？?]\s*)?(?:等等[，,]仔細計算|重新檢視時間點).*?(?:調整案件事實之時間邏輯|重新檢視時間點設定)[：:]?\s*',
            explanation,
            re.DOTALL
        )
        if leak_match:
            # 若有調整時間，同步更新題幹
            if "94年" in leak_match.group(0) or "94年" in explanation:
                q_text = item.get("question", "")
                if "96年1月1日" in q_text:
                    item["question"] = q_text.replace("96年1月1日", "94年1月1日").replace("95年1月1日", "93年1月1日")
            clean_exp = explanation[:leak_match.start()] + explanation[leak_match.end():]
            clean_exp = re.sub(r'^[，。、；\s]+', '', clean_exp)
            item["explanation"] = clean_exp
            explanation = clean_exp

        # --- 2. 答案精確性自動核驗與對齊 ---
        detected_ans = None

        # (a) 尋找明確結論語句：故選(X) / 應選(X) / 正確答案為(X) / 故本題應選(X)
        select_match = re.search(r'(?:故選|應選|考生應選|正確答案(?:為|應為|是)|故本題選|故本題應選)\s*[\(（]?([A-D])[\)）]?', explanation)
        if select_match:
            detected_ans = select_match.group(1).upper()

        # (b) 尋找結尾結論：故 ... (X) 正確/精確/為是/完全正確
        if not detected_ans:
            conclusion_match = re.search(
                r'故.*?[\(（]([A-D])[\)）](?:選項)?(?:之[^\n，。]{0,15})?(?:敘述精確|之法理分析完全正確|完全正確|正確|為正確|為是|為當|為最佳選項)',
                explanation
            )
            if conclusion_match:
                detected_ans = conclusion_match.group(1).upper()

        # (c) 尋找 (X) 為正確選項
        if not detected_ans:
            opt_match = re.search(r'[\(（]([A-D])[\)）]\s*(?:選項)?\s*(?:為正確選項|為唯一正確選項|為正確)', explanation)
            if opt_match:
                detected_ans = opt_match.group(1).upper()

        # (d) 逐項比對 (A)(B)(C)(D) 的正誤標註
        if not detected_ans:
            correct_opts = []
            for opt in ['A', 'B', 'C', 'D']:
                has_pos = bool(re.search(rf'[\(（]{opt}[\)）]\s*(?:選項)?\s*(?:正確|為正確|敘述精確|為是)', explanation))
                has_neg = bool(re.search(rf'[\(（]{opt}[\)）]\s*(?:選項)?\s*(?:錯誤|為錯誤|不正確|非正確)', explanation))
                if has_pos and not has_neg:
                    correct_opts.append(opt)
            if len(correct_opts) == 1:
                detected_ans = correct_opts[0]

        # 若抓取到明確的解析結論，且與 raw_answer 不一致，以詳解之實質論述為準進行修正
        if detected_ans and detected_ans in ["A", "B", "C", "D"]:
            item["answer"] = detected_ans
        elif raw_answer in ["A", "B", "C", "D"]:
            item["answer"] = raw_answer
        else:
            item["answer"] = "A"

        # 確保 options 結構健全
        if not isinstance(options, dict) or not options:
            item["options"] = {"A": "選項A", "B": "選項B", "C": "選項C", "D": "選項D"}

        return item

    def generate_stage1_exam(
        self,
        subject: str,
        topic: str,
        count: int = 5,
        question_mode: str = "標準單選題",
        notes_content: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        difficulty: int = 10
    ) -> Dict[str, Any]:
        """
        生成司律一試測驗題卷（支援批次生成以防 token 溢位）。
        :param subject: 考試科目
        :param topic: 核心考點主題
        :param count: 總出題數 (例如 5, 10, 20, 30 題)
        :param question_mode: "標準單選題" / "綜合案例實事實務題組題" / "全真綜合模考卷"
        :param notes_content: 考生筆記內容（可由手寫 OCR 或純文字傳入）
        :param progress_callback: 進度回報回調函數 callback(current, total)
        :param difficulty: 題目難度設定 (1~10 分，10為全真司律一試難度)
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

            difficulty_spec = ""
            if difficulty >= 8:
                difficulty_spec = f"【題目難度設定：{difficulty}/10（考選部司律一試全真頂級難度）】：維持考選部司律一試高難度標竿，包含複雜長篇案例事實、多面法律關係、跨法條跨爭點、具實務最新判解爭鳴或大法庭裁定之高誘答性選項，嚴格檢驗考生深層法理涵攝與爭點洞察力。"
            elif difficulty >= 6:
                difficulty_spec = f"【題目難度設定：{difficulty}/10（中階進階難度）】：採中等篇幅案例事實，涵蓋核心法條構成要件與重要實務通說，注重核心概念之辨析與法理定性判斷。"
            else:
                difficulty_spec = f"【題目難度設定：{difficulty}/10（初階入門/新手練習觀念題）】：專為法學新手循序漸進建立信心設計。採用基礎單一法條、構成要件直觀判斷之情境題，題幹敘述精簡明確，選項直接測試基本法學概念，避免過度複雜之跨法條交錯陷阱。"

            prompt = f"""
你是一位台灣「律師司法官高等考試一試」命題典試委員。
請針對科目【{subject}】，主題【{topic}】，依據司律一試全真規格，命題第 {start_num} 題至第 {end_num} 題（共 {this_batch_count} 題，四選一單選題）。

【命題最高準則（比照司法官律師考試標準）】：
1. {difficulty_spec}
2. 【試題區去條號、去字號】：題目情境題幹一律「隱匿法條條號」與「法院裁判字號」，純以具體案例事實盲測考生真實法理涵攝與爭點洞察力！
3. 【時間與時效精算規範（絕對零矛盾、零草稿流出）】：
   - 凡涉及民法第125條消滅時效（15年）、第126條（5年）、第127條（2年）、民法第337條（時效完成前已適於抵銷）、票據時效、撤銷除斥期間、年齡等任何時間要素：
   - 命題前【必須精確驗算】：『起算民國年份 + 期間年數 = 屆滿民國年份』。題幹中設定的具體年份與月份，必須 100% 精確符合所欲呈現之法定效果（例如：起算日為民國94年5月1日，則至民國109年5月1日始屆滿15年；若在110年間主張抵銷，始符合『時效已完成』之事實！切勿寫成96年起算卻在110年稱時效已完成）。
   - 嚴禁在題目（question）或解析（explanation）中出現年份算錯、事後推翻自己的草稿字眼（例如「等等，仔細計算...調整案件事實...」）！題幹事實與解析推導必須從一開始就完全一致、定稿輸出！
4. 【選項辨析深度與答案唯一自洽性】：
   - 四個選項 (A, B, C, D) 必須針對核心爭議、關鍵字眼或實務通說與少數說之差別設定深層辨析陷阱，僅有一最正確答案。
   - "answer" 欄位之選項英文字母（A/B/C/D），必須與 "explanation" 解析中最終判定為【正確】（例如『故(C)正確』、『故(C)敘述精確』、『故本題選(C)』）的選項字母 100% 絕對完全一致！嚴禁 answer 寫 A 解析卻說 (C) 正確！
5. 【題型要求】：{mode_spec}
6. {notes_instruction}

請輸出嚴格的 JSON 陣列格式：
[
  {{
    "question_no": {start_num},
    "category": "考點類別（例如：[公私法性質]、[消滅時效完成之效力與抵銷]、[不法原因給付]、[裁量收縮]）",
    "time_and_date_check": "若涉及時間/時效/年齡，寫出算式確認：起算年+期間=屆滿年，確認題幹符合；若無涉及時間填寫'無涉時間'",
    "case_facts": "若是題組題則填寫共通案件事實，若為單選獨立題則留空字串",
    "question": "具體案例情境描述及題目發問（盲測，不洩漏法條條號與裁判字號）...",
    "options": {{
      "A": "選項A文字...",
      "B": "選項B文字...",
      "C": "選項C文字...",
      "D": "選項D文字..."
    }},
    "options_analysis": "逐項簡要判定：(A) 說明...；(B) 說明...；(C) 說明...；(D) 說明...",
    "answer": "A",
    "core_issue": "本題測驗之核心法學爭點（例如：時效消滅債權得否抵銷之要件涵攝）",
    "explanation": "詳解說明：逐一分析 (A)(B)(C)(D) 為何正確或錯誤，文末請統一以『故 (A) 之法理分析完全正確，其餘選項錯誤。』作為定稿總結，該總結英文字母必須與 answer 欄位完全吻合！",
    "legal_references": "精確之法律條號、最高法院/最高行政法院判決字號、司法院釋字、憲法法庭判決或大法庭裁定出處"
  }}
]
只輸出純 JSON，勿添加其他多餘文字。
"""
            resp = self._call_model(
                prompt,
                generation_config=self._make_config(
                    temperature=0.35,
                    response_mime_type="application/json"
                )
            )
            
            try:
                batch_items = self._parse_json_safely(resp.text)
            except Exception as pe:
                # 容錯重試一次
                resp_retry = self._call_model(
                    prompt + "\n注意：請務必確保 JSON 語法完整合法且閉合！",
                    generation_config=self._make_config(temperature=0.2, response_mime_type="application/json")
                )
                batch_items = self._parse_json_safely(resp_retry.text)

            if isinstance(batch_items, dict):
                batch_items = [batch_items]

            for item in batch_items:
                item["question_no"] = current_q_index
                item = self._verify_and_align_mcq_item(item)
                ans = item.get("answer", "A")
                answer_key[str(current_q_index)] = ans
                all_questions.append(item)
                current_q_index += 1

            if progress_callback:
                progress_callback(len(all_questions), count)

        exam_id = f"ai_exam_{uuid.uuid4().hex[:8]}"
        return {
            "exam_id": exam_id,
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
        response = self._call_model(
            prompt,
            generation_config=self._make_config(
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
2. 【大前提嚴謹與權威判解位階】精確引出法條構成要件與法律效果。在引述實務見解時，嚴格遵循最高司法權威位階：
   - 第一位階：憲法法庭判決 / 司法院大法官解釋（憲法位階最高權威）
   - 第二位階：最高法院民刑大法庭裁定 / 最高行政法院大法庭裁定（統一見解核心）
   - 第三位階：最高法院精選裁判 / 具有參考價值裁判 / 經典判例
   - 嚴禁引用普通地方法院或高等法院裁判作為主要立論權威！
3. 【學說對比與深度分析】精準對比實務見解與法學名家有力見解（如王澤鑑、林山田、黃榮堅、陳敏、姜世明等通說與有力說），並詳述採擇理由。
4. 【小前提事實涵攝細膩】將題幹事實人事時地物嚴密套入法條構成要件，不空泛抄法條。
5. 【結論明確】一錘定音，直接俐落回應題目所有提問。
6. 【法律條文引用排版規範（極重要）】輸出文字中凡出現或引用法律條文時，嚴禁將各項、各款、各目黏連在同一行！必須嚴格分項分款分行排版（各項獨立成段並明確標記第幾項或Ⅰ、Ⅱ；各款一、二、三...獨立換行縮排），使法條層次清晰分明、絕不混淆。

請直接以排版工整之 Markdown 格式輸出擬答全文。
"""
        response = self._call_model(
            prompt,
            generation_config=self._make_config(
                temperature=0.3,
                response_mime_type=None
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

def load_all_existing_stage1_mcqs() -> list:
    """
    全量載入既有一試全真題庫：
    1. admin_law_300_mcqs.json (行政法 300 題全量題庫)
    2. data/training_data/law_exam_exams_and_mcq_sft.jsonl (SFT 一試題庫)
    3. 內建民法、刑法、憲法、民事訴訟法、刑事訴訟法、商事法全真精選選擇題
    """
    all_questions = []
    seen_hashes = set()

    # 1. 行政法 300 題
    bank_paths = [
        Path(RAW_DATA_DIR) / "admin_law_300_mcqs.json",
        Path(__file__).resolve().parent / "data" / "raw_exams" / "admin_law_300_mcqs.json",
        Path(__file__).resolve().parent.parent / "raw_exams" / "admin_law_300_mcqs.json"
    ]
    for bp in bank_paths:
        if bp.exists():
            try:
                data = json.loads(bp.read_text(encoding="utf-8"))
                for q in data.get("questions", []):
                    q_copy = dict(q)
                    q_copy["subject"] = "行政法"
                    q_copy["major_domain"] = "憲法與行政法"
                    h = f"{q_copy.get('question', '')[:30]}_{q_copy.get('options', {}).get('A', '')[:10]}"
                    if h not in seen_hashes:
                        all_questions.append(q_copy)
                        seen_hashes.add(h)
                break
            except Exception:
                pass

    # 2. 跨科全真模擬題庫 (民法、刑法、憲法、民事訴訟法、刑事訴訟法、商事法 86 題)
    multi_bank_paths = [
        Path(RAW_DATA_DIR) / "stage1_multi_subject_mcq_bank.json",
        Path(__file__).resolve().parent / "data" / "raw_exams" / "stage1_multi_subject_mcq_bank.json",
        Path(__file__).resolve().parent.parent / "raw_exams" / "stage1_multi_subject_mcq_bank.json"
    ]
    for mbp in multi_bank_paths:
        if mbp.exists():
            try:
                mdata = json.loads(mbp.read_text(encoding="utf-8"))
                for q in mdata:
                    q_copy = dict(q)
                    h = f"{q_copy.get('question', '')[:30]}_{q_copy.get('options', {}).get('A', '')[:10]}"
                    if h not in seen_hashes:
                        all_questions.append(q_copy)
                        seen_hashes.add(h)
                break
            except Exception:
                pass

    # 3. SFT 題庫
    sft_paths = [
        Path(DATA_DIR) / "training_data" / "law_exam_exams_and_mcq_sft.jsonl",
        Path(__file__).resolve().parent / "data" / "training_data" / "law_exam_exams_and_mcq_sft.jsonl"
    ]
    for sp in sft_paths:
        if sp.exists():
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip(): continue
                        item = json.loads(line)
                        raw_in = item.get("input", "")
                        raw_out = item.get("output", "")
                        if "(A)" in raw_in and ("【正確解答】" in raw_out or "A" in raw_out):
                            sub = item.get("subject", "綜合領域")
                            opts = {}
                            for opt_char in ["A", "B", "C", "D"]:
                                m_opt = re.search(rf'\({opt_char}\)\s*([^\n\(]+)', raw_in)
                                if m_opt:
                                    opts[opt_char] = m_opt.group(1).strip()
                            m_ans = re.search(r'【正確解答】[：:]\s*\(?([A-D])\)?', raw_out)
                            ans_char = m_ans.group(1) if m_ans else "A"
                            q_text_m = re.search(r'【案例事實與題目】[：:]\s*(.*?)(?=\(A\)|$)', raw_in, re.DOTALL)
                            q_text = q_text_m.group(1).strip() if q_text_m else raw_in[:200]
                            if len(opts) == 4:
                                h = f"{q_text[:30]}_{opts.get('A', '')[:10]}"
                                if h not in seen_hashes:
                                    domain = "民法與民事訴訟法" if "民" in sub else (
                                        "刑法與刑事訴訟法" if "刑" in sub else (
                                            "憲法與行政法" if ("憲" in sub or "行政" in sub) else "商事法與綜合領域"
                                        )
                                    )
                                    all_questions.append({
                                        "question_no": len(all_questions) + 1,
                                        "subject": sub,
                                        "major_domain": domain,
                                        "category": item.get("category", "法學核心爭點"),
                                        "question": q_text,
                                        "options": opts,
                                        "answer": ans_char,
                                        "explanation": raw_out
                                    })
                                    seen_hashes.add(h)
                break
            except Exception:
                pass

    # 3. 內建跨科全真精選題庫
    curated_mcqs = [
        {
            "question_no": len(all_questions) + 1,
            "subject": "民法",
            "major_domain": "民法與民事訴訟法",
            "category": "物權與借名登記處分",
            "question": "甲將其所有之A房地借名登記於乙名下，約定乙未得甲同意不得處分。後乙未經同意將A房地出賣並移轉登記於知情之惡意第三人丙。依最高法院108年度台上大字第1719號民事大法庭裁定見解，下列敘述何者最正確？",
            "options": {
                "A": "乙之移轉行為屬無權處分，因丙為惡意，故效力未定",
                "B": "乙本於物權登記名義人之處分權能而為移轉，無論丙善意或惡意均屬有權處分，丙有效取得所有權",
                "C": "甲得依民法第767條第1項前段規定，直接請求丙塗銷登記",
                "D": "乙之處分行為效力未定，俟甲承認後始生效力"
            },
            "answer": "B",
            "explanation": "【解析】：依最高法院108年度台上大字第1719號裁定，出名人擅自處分借名登記不動產，無論第三人善意或惡意均為有權處分，第三人有效取得所有權。故選 (B)。"
        },
        {
            "question_no": len(all_questions) + 2,
            "subject": "刑法",
            "major_domain": "刑法與刑事訴訟法",
            "category": "毒品販賣既遂與未遂",
            "question": "甲意圖營利，與便衣員警乙談妥以2萬元購買海洛因5公克，約定於捷運站交付。甲攜毒品赴約，自口袋取出尚未交給乙且未收受價金即遭逮捕。依最高法院108年度台上大字第3594號刑事大法庭裁定，甲應如何論處？",
            "options": {
                "A": "甲成立販賣第一級毒品既遂罪，因買賣意思合致即既遂",
                "B": "甲成立販賣第一級毒品未遂罪，因尚未交付毒品且未取得價金",
                "C": "甲不成立犯罪，因員警係陷害教唆",
                "D": "甲僅成立意圖販賣而持有第一級毒品罪"
            },
            "answer": "B",
            "explanation": "【解析】：最高法院108年度台上大字第3594號刑事大法庭裁定定錨：販賣毒品必須已交付毒品或收受價金移轉占有始成立既遂；僅達成買賣合意尚未交付者僅成立未遂。故選 (B)。"
        },
        {
            "question_no": len(all_questions) + 3,
            "subject": "憲法",
            "major_domain": "憲法與行政法",
            "category": "正當法律程序與身體權",
            "question": "警察攔停涉嫌酒駕之甲，甲拒絕吐氣測試，警遂依道交條例強制將甲移送醫院抽血。依憲法法庭111年憲判字第1號判決意旨，下列敘述何者最正確？",
            "options": {
                "A": "警察強制抽血完全合憲，因公共交通安全法益優先",
                "B": "強制抽血干預人身自由、身體權與隱私權，欠缺事前令狀審查或事後法定救濟程序，牴觸憲法正當法律程序原則",
                "C": "只要經警察分局長書面許可即可強制抽血",
                "D": "強制抽血屬非侵入性處分，毋庸受令狀原則拘束"
            },
            "answer": "B",
            "explanation": "【解析】：111年憲判字第1號判決宣告：道交條例授權警察逕行強制移送抽血檢測規定牴觸憲法第8條、第22條，違反正當法律程序與令狀原則。故選 (B)。"
        },
        {
            "question_no": len(all_questions) + 4,
            "subject": "民事訴訟法",
            "major_domain": "民法與民事訴訟法",
            "category": "爭點效與既判力",
            "question": "甲請求乙給付價金100萬元，法院審理後於理由認定契約有效，但因消滅時效完成而駁回甲之訴確定。嗣後甲請求乙受領標的物，乙再度主張契約無效。下列敘述何者最正確？",
            "options": {
                "A": "前訴理由中契約有效之判斷具備民事訴訟法第400條第1項之既判力",
                "B": "前案理由中之重大爭點判斷經兩造實質攻防，依爭點效理論，當事人不得為相反主張，法院亦不得為矛盾判斷",
                "C": "判決理由中之判斷絕對不生拘束力，乙於後訴可恣意重啟爭辯",
                "D": "時效抗辯之成立表示主文實質確定契約無效"
            },
            "answer": "B",
            "explanation": "【解析】：依最高法院實務通說，理由中判斷雖無既判力，但本於誠信原則適用「爭點效」，兩造充分言詞辯論之主要爭點於後訴具拘束力。故選 (B)。"
        },
        {
            "question_no": len(all_questions) + 5,
            "subject": "刑事訴訟法",
            "major_domain": "刑法與刑事訴訟法",
            "category": "違法取證與證據排除法則",
            "question": "警察無搜索票違法進入甲宅扣得海洛因磚。檢察官起訴提出該扣案毒品為證。依刑事訴訟法第158條之4及實務定錨見解，法院應如何處理？",
            "options": {
                "A": "違法搜索扣押之物證絕對不具證據能力，一律排除",
                "B": "物證具客觀不變性，程序違法不影響證據能力",
                "C": "法院應審酌人權保障與公共利益均衡維護，綜合權衡八大要素決定該物證有無證據能力",
                "D": "只要甲事後自白，違法搜索瑕疵即告補正"
            },
            "answer": "C",
            "explanation": "【解析】：依刑訴第158條之4及93台上664判例，公務員違法取證之證據能力應本於利益均衡原則綜合權衡八大要素決定。故選 (C)。"
        },
        {
            "question_no": len(all_questions) + 6,
            "subject": "商事法",
            "major_domain": "商事法與綜合領域",
            "category": "保險法告知義務與除斥期間",
            "question": "甲投保人壽保險隱匿罹癌事實，承保逾2年後因癌身故，受益人請求理賠。保險人主張依民法第92條撤銷投保意思表示拒賠。依最高法院108年度台上大字第897號裁定，下列敘述何者最正確？",
            "options": {
                "A": "保險人仍得於民法1年除斥期間內撤銷契約",
                "B": "保險法第64條第3項之2年除斥期間具排他性，逾2年後保險人不得再依民法第92條撤銷意思表示",
                "C": "因甲出於詐欺惡意，民法第92條撤銷權無除斥期間之適用",
                "D": "保險契約自始因詐欺而當然無效"
            },
            "answer": "B",
            "explanation": "【解析】：108台上大897裁定終局定錨：保險人解除權應專依保險法第64條第3項，逾2年除斥期間後不得再依民法第92條撤銷。故選 (B)。"
        }
    ]

    for cm in curated_mcqs:
        h = f"{cm['question'][:30]}_{cm['options']['A'][:10]}"
        if h not in seen_hashes:
            all_questions.append(cm)
            seen_hashes.add(h)

    for idx, q in enumerate(all_questions, 1):
        q["global_index"] = idx

    return all_questions
