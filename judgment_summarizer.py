# -*- coding: utf-8 -*-
"""
judgment_summarizer.py
======================
AI 裁判深度精華摘要與判旨提煉引擎（對標 Lawsnote 裁判摘要、法源法律網裁判要旨、Westlaw Headnotes）。
支援：
1. 訴訟標的與基礎案件事實 (Facts & Procedural History)
2. 兩造原告/被告主張要旨 (Parties' Claims & Contentions)
3. 本案核心法理爭點 (Core Legal Issues)
4. 法院裁判主旨與判決要旨 (Court Holding & Headnote Synthesis)
5. 適用法條與構成要件深度涵攝 (Statutory Reasoning & Subsumption)
6. 實務指標價值與後續影響 (Practical Significance)
7. 0 秒固化快取 (SQLite 永久快取，免重複消耗 Token)
8. 正本案號防偽核驗 (Ground Truth Case Audit)
"""

import os
import re
import json
import logging
import sqlite3
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from config import (
    DATA_DIR,
    JUDICIAL_1M_DIR,
)
from llm_client import generate_content, LlmCallError

logger = logging.getLogger(__name__)


def get_case_citation_verifier():
    """取得案號防偽驗證器（供 UI 與摘要器共用）"""
    try:
        from case_citation_verifier import get_case_verifier
        return get_case_verifier()
    except Exception as exc:
        logger.warning("Failed to initialize CaseCitationVerifier: %s", exc)
        return None


class JudgmentSummarizer:
    """
    裁判深度摘要與判旨提煉核心引擎
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(JudgmentSummarizer, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.cache_db_path = Path(DATA_DIR) / "judgment_summaries_cache.db"
        self._init_cache_db()

    @staticmethod
    def _ensure_cache_schema(conn: sqlite3.Connection):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS judgment_summaries (
                hash_key TEXT PRIMARY KEY,
                case_id TEXT,
                court TEXT,
                date TEXT,
                summary_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_js_case_id ON judgment_summaries(case_id);")

    def _init_cache_db(self):
        conn = None
        try:
            self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.cache_db_path))
            self._ensure_cache_schema(conn)
            conn.commit()
        except Exception as exc:
            logger.warning("Failed to initialize judgment cache DB %s: %s", self.cache_db_path, exc)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _get_cache(self, hash_key: str) -> Optional[Dict[str, Any]]:
        if not self.cache_db_path.exists():
            return None
        conn = None
        try:
            uri = f"file:{self.cache_db_path.resolve().as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT summary_json FROM judgment_summaries WHERE hash_key = ?",
                (hash_key,)
            ).fetchone()
            if row and row["summary_json"]:
                data = json.loads(row["summary_json"])
                if isinstance(data, dict) and data.get("success") is True:
                    return data
        except Exception as exc:
            logger.warning("Failed to read judgment cache %s: %s", self.cache_db_path, exc)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        return None

    def _set_cache(self, hash_key: str, case_id: str, court: str, date: str, summary_data: Dict[str, Any]):
        if not isinstance(summary_data, dict) or not summary_data.get("success"):
            return
        conn = None
        try:
            self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
            # 確保二進位欄位不會寫入 JSON 快取造成 TypeError
            cacheable = {
                k: v for k, v in summary_data.items()
                if k not in ("docx_bytes", "pdf_bytes")
            }
            payload = json.dumps(cacheable, ensure_ascii=False)
            conn = sqlite3.connect(str(self.cache_db_path))
            self._ensure_cache_schema(conn)
            conn.execute(
                "INSERT OR REPLACE INTO judgment_summaries (hash_key, case_id, court, date, summary_json) VALUES (?, ?, ?, ?, ?)",
                (hash_key, case_id, court, date, payload)
            )
            conn.commit()
        except Exception as exc:
            logger.warning("Failed to write judgment cache %s: %s", self.cache_db_path, exc)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def _is_case_verified(summary_data: Dict[str, Any]) -> bool:
        if summary_data.get("case_verified") is True:
            return True
        cv = summary_data.get("case_verification")
        if isinstance(cv, dict) and cv.get("is_verified") is True:
            return True
        cid = (summary_data.get("case_id") or "").strip()
        if cid:
            for cit in summary_data.get("citations") or []:
                if isinstance(cit, dict) and cit.get("is_verified") is True:
                    if cid in (cit.get("case_id") or "") or (cit.get("case_id") or "") in cid:
                        return True
        return False

    @classmethod
    def _get_verification_labels(cls, summary_data: Dict[str, Any]) -> Tuple[str, str]:
        """回傳 (DOCX 核驗標籤, PDF 核驗標籤)，絕不偽稱未核驗案號已通過正本核驗"""
        if cls._is_case_verified(summary_data):
            return (
                "🛡️ 案號驗證：司法院官方正本核驗通過",
                "✅ 司法院官方正本核驗通過",
            )
        if (summary_data.get("case_id") or "").strip():
            return (
                "⚠️ 案號驗證：未通過本機正本核驗（請逕向司法院網站查證）",
                "⚠️ 未通過本機正本核驗（請查證）",
            )
        return (
            "ℹ️ 案號驗證：未指定裁判案號（依輸入內文摘錄）",
            "ℹ️ 未指定案號（依輸入內文摘錄）",
        )

    def summarize_judgment(
        self,
        judgment_text: str = "",
        case_id: str = "",
        court: str = "",
        court_name: str = "",
        date: str = "",
        case_type: str = "",
        force_regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        對裁判全文或裁判要旨進行深度六維度 AI 摘要與判旨提煉
        支援僅傳入案號，自動由本機裁判大庫或先例庫調閱全文。
        """
        court = court or court_name
        if not judgment_text and case_id:
            try:
                from legal_summarizer_engine import find_legal_doc_by_citation
                doc = find_legal_doc_by_citation(case_id)
                if doc and doc.get("found"):
                    judgment_text = doc.get("text", "") or doc.get("holding_snippet", "")
                    court = court or doc.get("court_or_agency", "")
            except Exception as exc:
                logger.warning("Failed to look up judgment text for %s: %s", case_id, exc)

        if not judgment_text or not judgment_text.strip():
            return {"success": False, "error": "請提供欲摘要之裁判內文或案號！"}

        clean_text = judgment_text.strip()
        hash_key = hashlib.md5(f"{case_id}_{clean_text[:1000]}".encode('utf-8')).hexdigest()

        # 1. 檢查快取（僅讀取已成功之快取結果，並於讀取時按需重建檔案位元組）
        if not force_regenerate:
            cached = self._get_cache(hash_key)
            if cached and cached.get("success") is True and (cached.get("summary_markdown") or cached.get("markdown_result")):
                cached["cached"] = True
                cached.setdefault("case_verified", self._is_case_verified(cached))
                if not cached.get("dimensions"):
                    cached["dimensions"] = self._extract_dimensions(cached.get("summary_markdown", ""))
                cached["docx_bytes"] = self.generate_summary_docx(cached)
                cached["pdf_bytes"] = self.generate_summary_pdf(cached)
                return cached

        # 2. 構建 Prompt
        prompt = f"""你是一名精通中華民國司法實務之高階法官助理與法學研究員。
請以專業、精準、具備司法指標價值之架構，為以下裁判文書提煉【深度判旨與判決摘要】（對標法源法律網與 Lawsnote 專業標準）。

【裁判案號】：{case_id or '未載明 (依裁判內文定性)'}
【審理法院】：{court or '中華民國法院'}
【裁判日期】：{date or ''}

【裁判原件內文】：
{clean_text[:6000]}

---

請以繁體中文與台灣標準法學術語，嚴格輸出以下六大結構：

### 📌 一、訴訟標的與基礎事實摘要 (Procedural History & Facts)
- 本案之訴訟標的、原審判決結果與審級救濟歷程。
- 兩造當事人間核心事實經過（時間、行為態樣、法律關係）。

### ⚖️ 二、原告（上訴人）與被告（被上訴人）主張要旨 (Parties' Contentions)
- **原告／上訴人主張**：起訴或上訴指摘之法理核心。
- **被告／被上訴人答辯**：防禦抗辯或否認之法律論據。

### 🎯 三、核心法律爭點 (Core Legal Issues)
- 提煉本案最關鍵之 1~2 個實體法或程序法爭點。

### 🏛️ 四、法院裁判主旨與判旨要旨 (Court Holding & Landmark Headnote)
- 以 150~250 字提煉最關鍵之【法院判決要旨】（此為實務引述之核心論述，請務必精準提煉法律見解）。

### 🧩 五、法院法律推演與要件涵攝 (Legal Reasoning & Subsumption)
- 法院如何解釋法律大前提？
- 如何將本案事實涵攝至構成要件？說明心證形成與採證原則。

### 🌟 六、本件裁判之實務指引與指標價值 (Practical Significance)
- 對於律師實務辦案或司法考試作答之實務指導意義。
"""

        try:
            summary_content = self._call_llm(prompt)
        except Exception as exc:
            err_msg = str(exc) or "Gemini AI 摘要服務暫時無法使用"
            logger.warning("JudgmentSummarizer LLM failed for case_id=%s: %s", case_id, err_msg)
            return {
                "success": False,
                "error": err_msg,
                "case_id": case_id,
                "court": court,
                "date": date,
                "summary_markdown": "",
                "markdown_result": "",
                "audit_markdown": "",
                "citations": [],
                "case_verification": None,
                "case_verified": False,
                "dimensions": {},
                "cached": False,
                "docx_bytes": b"",
                "pdf_bytes": b"",
            }

        # 3. 案號防偽核驗 (Ground Truth Case Audit)
        audit_md = ""
        verified_citations = []
        case_verification = None
        is_case_verified = False
        try:
            from case_citation_verifier import get_case_verifier
            verifier = get_case_verifier()
            if case_id:
                case_verification = verifier.verify_citation(case_id)
                is_case_verified = bool(case_verification.get("is_verified"))
            v_res = verifier.verify_text_citations(summary_content, auto_badge=True)
            summary_content = v_res.get("annotated_text", summary_content)
            audit_md = v_res.get("audit_markdown", "")
            verified_citations = v_res.get("citations", [])
        except Exception as exc:
            logger.warning("CaseCitationVerifier failed in JudgmentSummarizer: %s", exc)

        dims = self._extract_dimensions(summary_content)
        result = {
            "success": True,
            "case_id": case_id,
            "court": court,
            "date": date,
            "summary_markdown": summary_content,
            "markdown_result": summary_content,
            "audit_markdown": audit_md,
            "citations": verified_citations,
            "case_verification": case_verification,
            "case_verified": is_case_verified,
            "dimensions": dims,
            "cached": False
        }

        # 4. 存入快取（在附加 docx_bytes / pdf_bytes 之前寫入純 JSON 資料）
        self._set_cache(hash_key, case_id, court, date, result)

        result["docx_bytes"] = self.generate_summary_docx(result)
        result["pdf_bytes"] = self.generate_summary_pdf(result)
        return result

    def _call_llm(self, prompt: str) -> str:
        return generate_content(
            prompt,
            temperature=0.2,
            max_output_tokens=3000,
        )



    def _extract_dimensions(self, markdown_text: str) -> Dict[str, str]:
        """將 AI 生成之 Markdown 依照六大標準結構解析為字典"""
        dims = {}
        patterns = {
            "facts": r'(?:###\s*.*一[、\s].*訴訟標的.*|###\s*.*基礎事實.*)([\s\S]*?)(?=###|\Z)',
            "contentions": r'(?:###\s*.*二[、\s].*主張.*)([\s\S]*?)(?=###|\Z)',
            "issues": r'(?:###\s*.*三[、\s].*爭點.*)([\s\S]*?)(?=###|\Z)',
            "holding": r'(?:###\s*.*四[、\s].*主旨.*|###\s*.*判旨.*)([\s\S]*?)(?=###|\Z)',
            "reasoning": r'(?:###\s*.*五[、\s].*法律推演.*|###\s*.*涵攝.*)([\s\S]*?)(?=###|\Z)',
            "significance": r'(?:###\s*.*六[、\s].*實務指引.*|###\s*.*指標價值.*)([\s\S]*?)(?=###|\Z)',
        }
        for key, pat in patterns.items():
            m = re.search(pat, markdown_text)
            if m:
                dims[key] = m.group(1).strip()
            else:
                dims[key] = ""
        return dims

    def generate_summary_docx(self, summary_data: Dict[str, Any]) -> bytes:
        """
        將裁判 AI 深度摘要成果導出為專業法學 Word (.docx) 檔
        包含司法案號標頭、當事人與法院資訊、六大標準 IRAC 維度與官方驗證先例。
        """
        import io
        try:
            import docx
            from docx import Document
            from docx.shared import Pt, Inches, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from docx.oxml import OxmlElement, parse_xml
            from docx.oxml.ns import nsdecls, qn

            doc = Document()

            # 設定頁邊距
            for sec in doc.sections:
                sec.top_margin = Inches(0.8)
                sec.bottom_margin = Inches(0.8)
                sec.left_margin = Inches(0.9)
                sec.right_margin = Inches(0.9)

            cid = summary_data.get("case_id") or "司法裁判書"
            court = summary_data.get("court") or "中華民國最高法院"
            date = summary_data.get("date") or ""

            # 標題
            title_p = doc.add_paragraph()
            title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run_title = title_p.add_run("中華民國司法裁判精鍊與深度判旨摘要書")
            run_title.font.name = "標楷體"
            run_title.font.size = Pt(18)
            run_title.font.bold = True
            run_title.font.color.rgb = RGBColor(26, 54, 93)

            # 案號子標題
            sub_p = doc.add_paragraph()
            sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            sub_run = sub_p.add_run(f"【{court} ｜ {cid}】")
            sub_run.font.name = "新細明體"
            sub_run.font.size = Pt(12)
            sub_run.font.bold = True
            sub_run.font.color.rgb = RGBColor(100, 116, 139)

            doc.add_paragraph("─" * 48).alignment = WD_ALIGN_PARAGRAPH.CENTER

            docx_verify_label, _ = self._get_verification_labels(summary_data)

            # 基本資訊表
            tbl = doc.add_table(rows=2, cols=2)
            tbl.autofit = True
            tbl.cell(0, 0).text = f"🏛️ 審理法院：{court}"
            tbl.cell(0, 1).text = f"📅 裁判日期：{date or '依正本為準'}"
            tbl.cell(1, 0).text = f"🔖 裁判字號：{cid}"
            tbl.cell(1, 1).text = docx_verify_label

            doc.add_paragraph("")

            # 逐一輸出六大維度
            dims = summary_data.get("dimensions", {})
            if not dims:
                dims = self._extract_dimensions(summary_data.get("summary_markdown", ""))

            dim_titles = [
                ("facts", "📌 一、訴訟標的與基礎事實摘要", RGBColor(30, 64, 175)),
                ("contentions", "⚖️ 二、原告（上訴人）與被告（被上訴人）主張要旨", RGBColor(79, 70, 229)),
                ("issues", "🎯 三、核心法律爭點", RGBColor(180, 83, 9)),
                ("holding", "🏛️ 四、法院裁判主旨與判旨要旨", RGBColor(185, 28, 28)),
                ("reasoning", "🧩 五、法院法律推演與要件涵攝", RGBColor(4, 120, 87)),
                ("significance", "🌟 六、本件裁判之實務指引與指標價值", RGBColor(109, 40, 217)),
            ]

            for d_key, d_label, d_color in dim_titles:
                h_p = doc.add_paragraph()
                h_run = h_p.add_run(d_label)
                h_run.font.name = "微軟正黑體"
                h_run.font.size = Pt(13)
                h_run.font.bold = True
                h_run.font.color.rgb = d_color

                content_txt = dims.get(d_key, "")
                if content_txt:
                    for line in content_txt.split("\n"):
                        clean_l = line.strip()
                        if clean_l:
                            p = doc.add_paragraph()
                            p.paragraph_format.line_spacing = 1.25
                            p.paragraph_format.space_after = Pt(4)
                            r = p.add_run(clean_l)
                            r.font.name = "新細明體"
                            r.font.size = Pt(11)
                else:
                    p = doc.add_paragraph()
                    r = p.add_run("（詳見裁判全文）")
                    r.font.italic = True

                doc.add_paragraph("")

            # 頁尾簽核資訊
            ft_p = doc.add_paragraph()
            ft_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            ft_run = ft_p.add_run("本摘要由 司律考試 AI 評分與法學研析大師・裁判精鍊引擎 自動生成")
            ft_run.font.name = "新細明體"
            ft_run.font.size = Pt(9)
            ft_run.font.color.rgb = RGBColor(148, 163, 184)

            buffer = io.BytesIO()
            doc.save(buffer)
            return buffer.getvalue()
        except Exception as e:
            logger.warning("Failed to generate judgment summary DOCX: %s", e)
            return b""


    def generate_summary_pdf(self, summary_data: Dict[str, Any]) -> bytes:
        """將裁判 AI 深度摘要成果導出為專業法學 PDF 檔"""
        try:
            from document_exporter import LegalPdfDocument
            cid = summary_data.get("case_id") or "司法裁判書"
            court = summary_data.get("court") or "中華民國法院"
            date = summary_data.get("date") or ""
            _, pdf_verify_label = self._get_verification_labels(summary_data)

            pdf = LegalPdfDocument(title=f"📑 裁判精鍊要旨・{cid}")
            pdf.add_title("🏛️ 中華民國司法裁判精鍊與深度判旨摘要書")
            pdf.add_table(
                ["審理法院", "裁判案號", "裁判日期", "案號真偽核驗"],
                [[court, cid, date or "依正本為準", pdf_verify_label]]
            )

            dims = summary_data.get("dimensions", {})
            if not dims:
                dims = self._extract_dimensions(summary_data.get("summary_markdown", ""))

            dim_titles = [
                ("facts", "📌 一、訴訟標的與基礎事實摘要"),
                ("contentions", "⚖️ 二、原告（上訴人）與被告（被上訴人）主張要旨"),
                ("issues", "🎯 三、核心法律爭點"),
                ("holding", "🏛️ 四、法院裁判主旨與判旨要旨"),
                ("reasoning", "🧩 五、法院法律推演與要件涵攝"),
                ("significance", "🌟 六、本件裁判之實務指引與指標價值"),
            ]

            for d_key, d_label in dim_titles:
                pdf.add_heading(d_label, level=2)
                content_txt = dims.get(d_key, "")
                if content_txt:
                    for line in content_txt.split("\n"):
                        clean_l = line.strip()
                        if clean_l:
                            pdf.add_paragraph(clean_l, font_size=9.5)
                else:
                    pdf.add_paragraph("（詳見裁判全文）", font_size=9.5, color=(0.5, 0.5, 0.5))

            return pdf.get_pdf_bytes()
        except Exception as e:
            logger.warning("Failed to generate judgment summary PDF: %s", e)
            return b""

_summarizer_instance = None

def get_judgment_summarizer() -> JudgmentSummarizer:
    global _summarizer_instance
    if _summarizer_instance is None:
        _summarizer_instance = JudgmentSummarizer()
    return _summarizer_instance
