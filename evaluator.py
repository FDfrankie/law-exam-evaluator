"""
司律手寫試卷自動評分核心引擎
使用官方 Google GenAI SDK (支援 Gemini 2.0 Flash / Flash Latest)：
1. 繁體手寫辨識與專有名詞校正 (支援圖片、PDF 或 Word 文字)
2. 司律閱卷級距評分（爭點識別、法學論述/三段論法、學說實務見解、事實涵攝）
3. 輸出結構化診斷報告與建議
"""
import logging
import os
import json
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from PIL import Image

from config import get_gemini_api_key, REPORTS_DIR, DEFAULT_GEMINI_MODEL
import llm_client

logger = logging.getLogger(__name__)


def _normalize_citation_verification(v_res: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure citation_verification works with both CaseCitationVerifier keys and app.py verified/unverified keys."""
    all_cits = list(v_res.get("citations") or [])
    verified: List[Dict[str, Any]] = []
    unverified: List[str] = []
    for c in all_cits:
        if not isinstance(c, dict):
            unverified.append(str(c))
            continue
        cit_label = c.get("raw") or c.get("citation") or c.get("case_id") or c.get("text") or str(c)
        is_ok = bool(c.get("verified") or c.get("is_verified") or c.get("status") == "verified" or c.get("matched"))
        if is_ok:
            db_match = c.get("db_match") or c.get("matched_title") or c.get("title") or c.get("holding", "")[:80] or cit_label
            entry = dict(c)
            entry.setdefault("citation", cit_label)
            entry.setdefault("db_match", db_match)
            verified.append(entry)
        else:
            unverified.append(cit_label)
    normalized = dict(v_res)
    normalized["citations"] = all_cits
    normalized["verified"] = verified
    normalized["unverified"] = unverified
    normalized.setdefault("verified_count", len(verified))
    normalized.setdefault("hallucination_count", len(unverified))
    return normalized


_STATUTE_LAW_ALIASES = {
    "刑法": "中華民國刑法",
    "憲法": "中華民國憲法",
    "民訴": "民事訴訟法",
    "刑訴": "刑事訴訟法",
    "行程法": "行政程序法",
    "國賠法": "國家賠償法",
}


def _verify_statutes_in_text(text: str) -> Dict[str, Any]:
    """Verify statute law names and article numbers safely against six_codes_engine."""
    if not text or not isinstance(text, str):
        return {"checked": False, "statutes": [], "verified_count": 0, "unverified_count": 0}
    try:
        from six_codes_engine import load_six_codes_data, get_law_articles, normalize_article_no
        _, _, law_map = load_six_codes_data()
    except Exception as exc:
        logger.warning("載入六法全書法條索引失敗，略過法條查核: %s", exc)
        return {"checked": False, "statutes": [], "verified_count": 0, "unverified_count": 0, "error": str(exc)}

    if not isinstance(law_map, dict) or not law_map:
        return {"checked": False, "statutes": [], "verified_count": 0, "unverified_count": 0}

    candidate_names = sorted(set(law_map.keys()) | set(_STATUTE_LAW_ALIASES.keys()), key=len, reverse=True)
    if not candidate_names:
        return {"checked": False, "statutes": [], "verified_count": 0, "unverified_count": 0}

    pattern = re.compile(
        r"(" + "|".join(re.escape(name) for name in candidate_names) + r")\s*第?\s*(\d+(?:\s*(?:之|-)\s*\d+)?)\s*條"
    )

    seen = set()
    statutes: List[Dict[str, Any]] = []
    article_cache: Dict[str, set] = {}

    for match in pattern.finditer(text):
        raw_law = match.group(1)
        raw_art = match.group(2)
        canonical_law = raw_law if raw_law in law_map else _STATUTE_LAW_ALIASES.get(raw_law, raw_law)
        norm_art = normalize_article_no(raw_art)
        dedup_key = (canonical_law, norm_art)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        if canonical_law not in article_cache:
            try:
                arts = get_law_articles(canonical_law) or []
                article_cache[canonical_law] = {
                    normalize_article_no(a.get("article_no", ""))
                    for a in arts
                    if isinstance(a, dict) and a.get("article_no")
                }
            except Exception as exc:
                logger.warning("查詢法規 %s 條文失敗: %s", canonical_law, exc)
                article_cache[canonical_law] = set()

        exists = norm_art in article_cache[canonical_law]
        statutes.append({
            "law_name": canonical_law,
            "raw_mention": match.group(0),
            "article_no": norm_art,
            "verified": exists,
        })

    verified_count = sum(1 for s in statutes if s["verified"])
    return {
        "checked": True,
        "statutes": statutes,
        "verified_count": verified_count,
        "unverified_count": len(statutes) - verified_count,
    }


class LawExamEvaluator:
    def __init__(self, model_name: str = DEFAULT_GEMINI_MODEL, api_key: Optional[str] = None):
        self._explicit_api_key = api_key
        self.model_name = model_name or DEFAULT_GEMINI_MODEL
        self.reports_dir = Path(REPORTS_DIR)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    @property
    def api_key(self) -> str:
        return get_gemini_api_key(self._explicit_api_key)

    @property
    def client(self):
        key = self.api_key
        if not key:
            return None
        try:
            from google import genai
            return genai.Client(api_key=key)
        except Exception as exc:
            logger.warning("動態建立 Gemini Client 失敗: %s", exc)
            return None

    def evaluate_submission(
        self,
        images: Optional[List[Image.Image]] = None,
        submission_text: Optional[str] = None,
        question_text: str = "",
        standard_rubric: Optional[str] = None,
        lecture_notes: Optional[str] = None
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

        # --- 司法裁判動態 Grounding & 講義真跡檢索注入 ---
        grounding_block = ""
        try:
            from authority_engine import get_dynamic_legal_grounding
            g_input = f"{question_text}\n{submission_text or ''}\n{standard_rubric or ''}\n{lecture_notes or ''}"
            grounding_res = get_dynamic_legal_grounding(g_input, limit=4)
            grounding_block = grounding_res.get("grounding_prompt_block", "")
        except Exception as exc:
            logger.warning("動態裁判與講義檢索 Grounding 失敗: %s", exc)

        user_content = [
            system_prompt,
            f"【考試題目】：\n{question_text}\n\n",
        ]

        if standard_rubric:
            user_content.append(f"【評分要點/參考擬答】：\n{standard_rubric}\n\n")

        if lecture_notes and lecture_notes.strip():
            user_content.append(f"【權威法學講義與評分法理基準（Grounding Lecture Notes）】：\n\"\"\"\n{lecture_notes.strip()[:60000]}\n\"\"\"\n【極重要】：評閱時必須以此講義之體系架構與學說爭點作為最核心評核準則！\n\n")

        if grounding_block:
            user_content.append(f"{grounding_block}\n\n")

        if submission_text:
            user_content.append(f"【考生的作答文字稿內容】：\n{submission_text}\n\n")

        if images:
            user_content.append("【以下為考生實際手寫作答圖片】：")
            user_content.extend(images)

        try:
            response_text = llm_client.generate_content(
                user_content,
                primary_model=self.model_name,
                temperature=0.2,
                response_mime_type="application/json",
                api_key=self._explicit_api_key,
            )
        except llm_client.AuthError as e:
            raise RuntimeError(f"Gemini API 認證或金鑰錯誤，請檢查 GEMINI_API_KEY：{e}") from e
        except llm_client.MissingApiKeyError as e:
            raise RuntimeError(f"未檢測到 GEMINI_API_KEY！請在 Streamlit Cloud 的 Secrets 或 .env 中設定您的 API Key：{e}") from e
        except llm_client.LlmCallError as e:
            raise RuntimeError(f"所有 Gemini 模型呼叫均失敗，最後錯誤: {e}") from e

        safe_raw = response_text if isinstance(response_text, str) else ("" if response_text is None else str(response_text))
        if not safe_raw.strip():
            logger.warning("Gemini 評分回應為空 (empty/None)")
            result_json = {
                "error": "模型未回傳有效評分內容（空白回應）",
                "raw_response": "",
                "total_score": 0,
                "grade_level": "無法評定",
            }
        else:
            def _repair_eval_json(broken_text: str) -> Optional[str]:
                repair_prompt = (
                    "請將以下法律申論評分結果修復為單一合法、完整閉合的 JSON 物件，"
                    "僅輸出 JSON 本身，不要加任何說明或 Markdown 標記：\n\n"
                    + broken_text[:6000]
                )
                return llm_client.generate_content(
                    repair_prompt,
                    primary_model=self.model_name,
                    temperature=0.0,
                    response_mime_type="application/json",
                    api_key=self._explicit_api_key,
                )

            try:
                result_json = llm_client.parse_json_response(safe_raw, repair_fn=_repair_eval_json)
            except Exception as parse_err:
                logger.warning("評分回應 JSON 解析與修補失敗: %s", parse_err)
                result_json = {
                    "error": "JSON 解析失敗",
                    "raw_response": safe_raw[:2000],
                    "total_score": 0,
                    "grade_level": "無法評定",
                }

        if isinstance(result_json, list) and len(result_json) == 1 and isinstance(result_json[0], dict):
            result_json = result_json[0]

        report_file = self.reports_dir / f"report_{os.getpid()}_{abs(hash((question_text or '')[:20]))}.json"
        try:
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(result_json, f, ensure_ascii=False, indent=2)
        except Exception as e_io:
            logger.warning("儲存初始評分報告失敗: %s", e_io)

        # 全量實體裁判案號防偽、考卷字號真實性與法條存在性查核 (CaseCitationVerifier + six_codes_engine)
        if isinstance(result_json, dict):
            q_topic = (question_text or "")[:60]
            suggested_rev = result_json.get("suggested_revision")
            feedback_text = result_json.get("feedback")
            student_text = result_json.get("transcription") or submission_text or ""

            try:
                from case_citation_verifier import get_case_verifier
                verifier = get_case_verifier()

                combined_cits: List[Any] = []
                seen_cit_keys = set()
                audit_parts: List[str] = []

                def _merge_cits(res_obj: Dict[str, Any]):
                    for c in (res_obj.get("citations") or []):
                        c_key = (
                            c.get("raw") or c.get("citation") or c.get("case_id") or c.get("text")
                            if isinstance(c, dict)
                            else str(c)
                        )
                        if c_key not in seen_cit_keys:
                            seen_cit_keys.add(c_key)
                            combined_cits.append(c)
                    audit_md = res_obj.get("audit_markdown")
                    if audit_md:
                        audit_parts.append(audit_md)

                # 1. 查核並裝飾閱卷委員優化建議 (suggested_revision)
                if isinstance(suggested_rev, str) and suggested_rev.strip():
                    v_res = verifier.verify_and_decorate_response(
                        suggested_rev,
                        context_topic=q_topic,
                        auto_badge=True,
                    )
                    result_json["suggested_revision_annotated"] = v_res.get("annotated_text", "")
                    _merge_cits(v_res)

                # 2. 查核並裝飾總評意見 (feedback)
                if isinstance(feedback_text, str) and feedback_text.strip():
                    f_res = verifier.verify_and_decorate_response(
                        feedback_text,
                        context_topic=f"{q_topic} 評閱總評",
                        auto_badge=True,
                    )
                    result_json["feedback_annotated"] = f_res.get("annotated_text", "")
                    result_json["feedback_citation_verification"] = _normalize_citation_verification(f_res)
                    _merge_cits(f_res)

                if combined_cits or audit_parts:
                    merged_norm = _normalize_citation_verification({
                        "citations": combined_cits,
                        "audit_markdown": "\n\n".join(audit_parts),
                    })
                    result_json["citation_verification"] = merged_norm
                    result_json["citations"] = merged_norm["citations"]
                    result_json["audit_markdown"] = merged_norm.get("audit_markdown", "")

                # 3. 查核考生原卷引用字號 (student_text，防範考生作答憑空捏造案號)
                if isinstance(student_text, str) and student_text.strip():
                    s_res = verifier.verify_and_decorate_response(
                        student_text,
                        context_topic="考生作答字號真實性檢視",
                        auto_badge=True,
                    )
                    result_json["student_citation_verification"] = _normalize_citation_verification(s_res)

            except Exception as e_ver:
                logger.warning("CaseCitationVerifier 引用字號查核失敗: %s", e_ver)

            # 4. 查核建議改寫、總評與考生作答所引法條條號存在性 (six_codes_engine)
            statute_probe_text = "\n".join(
                part for part in (suggested_rev, feedback_text, student_text)
                if isinstance(part, str) and part.strip()
            )
            if statute_probe_text:
                result_json["statute_verification"] = _verify_statutes_in_text(statute_probe_text)

        # 覆寫儲存已注入真實性核驗之報告
        try:
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(result_json, f, ensure_ascii=False, indent=2)
        except Exception as e_io:
            logger.warning("覆寫評分報告失敗: %s", e_io)

        return result_json
