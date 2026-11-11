# -*- coding: utf-8 -*-
"""
judicial_appeal_chain.py
========================
審級脈絡與歷程關聯導航引擎（對標法源法律網、七法 Laws.club、Lawsnote 審級歷程）。
覆蓋全國 797 萬+ 筆裁判索引與國考精華子庫之審級鏈接：
1. 前審裁判 (Prior Instances)：地方法院一審 ➔ 高等法院二審（毫秒級自 history_instances 解析）
2. 後審裁判 (Subsequent Instances)：最高法院上訴 ➔ 撤銷發回更審 ➔ 大法庭 / 憲法法庭
3. 歷程時間軸 (Appeal Timeline)：視覺化審級演進、判決日期、裁判主旨摘要與正本連結
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from config import JUDICIAL_1M_DIR, DATA_DIR



def infer_disposition_intelligence(text: str) -> Dict[str, Any]:
    """
    智能分析裁判主文與判旨，精準識別審級結論與逆轉訊號（對標 Lawsnote 審級結果分析）
    """
    t = str(text or "")
    if any(k in t for k in ["廢棄發回", "原判決廢棄", "發回更審", "發回臺灣高等"]):
        return {
            "disposition": "廢棄發回更審",
            "badge": "🚨 【見解逆轉・原判決廢棄發回】",
            "is_reversal": True,
            "badge_color": "#d90429"
        }
    if any(k in t for k in ["撤銷改判", "原判決撤銷", "改判", "改處"]):
        return {
            "disposition": "撤銷原判改判",
            "badge": "🚨 【見解逆轉・原判決撤銷改判】",
            "is_reversal": True,
            "badge_color": "#e63946"
        }
    if any(k in t for k in ["上訴駁回", "抗告駁回", "原審判決並無不合", "核無不合", "原判決並無違誤", "應予駁回"]):
        return {
            "disposition": "上訴駁回",
            "badge": "✅ 【見解推進／原審確定定錨】",
            "is_reversal": False,
            "badge_color": "#2a9d8f"
        }
    if any(k in t for k in ["大字", "大法庭", "統一見解", "徵詢"]):
        return {
            "disposition": "最高法院大法庭裁定",
            "badge": "🏛️ 【最高法院大法庭法律統一裁定】",
            "is_reversal": False,
            "badge_color": "#457b9d"
        }
    if any(k in t for k in ["憲判", "違憲", "合憲", "大法官解釋", "釋字"]):
        return {
            "disposition": "憲法法庭判決",
            "badge": "⚖️ 【憲法法庭終局裁判】",
            "is_reversal": True if "違憲" in t else False,
            "badge_color": "#6a0dad"
        }
    return {
        "disposition": "裁判審理終結",
        "badge": "📄 【實體審理終結】",
        "is_reversal": False,
        "badge_color": "#1d3557"
    }

class JudicialAppealChainEngine:
    """
    全量裁判審級歷程與前審/後審鏈接分析引擎 (毫秒級極速版)
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(JudicialAppealChainEngine, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._db_engine = None
        try:
            from build_million_judgments_db import get_million_db_engine
            self._db_engine = get_million_db_engine()
            self.index_db_path = self._db_engine.index_db_path
        except Exception:
            self.index_db_path = Path(JUDICIAL_1M_DIR) / "judicial_1m_index.db"
            if not self.index_db_path.exists():
                for cand in [
                    Path(DATA_DIR) / "judicial_1m_db" / "judicial_1m_index.db",
                    Path(DATA_DIR) / "judicial_exam_core.db",
                    Path(__file__).resolve().parent / "data" / "judicial_exam_core.db",
                ]:
                    if cand.exists():
                        self.index_db_path = cand
                        break

    def _get_connection(self) -> sqlite3.Connection:
        if self._db_engine is not None:
            return self._db_engine._get_ro_conn(self.index_db_path)
        uri = f"file:///{Path(self.index_db_path).resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=60.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 60000;")
        except Exception:
            pass
        return conn

    def get_appeal_chain(
        self,
        case_id: str = "",
        court: str = "",
        year: str = "",
        word: str = "",
        no: str = ""
    ) -> Dict[str, Any]:
        """
        查詢特定裁判之完整審級歷程（包含本案、前審、後審與關聯發回裁定）
        使用 idx_meta_ywn 毫秒級複合索引，徹底杜絕全表掃描；支援母庫、精華子庫與遠端橋接。
        """
        db_eng = self._db_engine
        is_remote = bool(db_eng and getattr(db_eng, "db_mode", "") == "remote" and db_eng.remote_api_url)
        if not is_remote and (not self.index_db_path or not self.index_db_path.exists()):
            return {"success": False, "error": "裁判資料庫未就緒", "chain": []}

        clean_case_id = case_id.strip() if case_id else ""
        y = str(year).strip() if year else ""
        w = str(word).strip() if word else ""
        n = str(no).strip() if no else ""

        if clean_case_id and not (y and w and n):
            m = re.search(r'(?:(臺灣[^\s]+法院|最高法院|最高行政法院|臺[北中南高]等[行政]*法院)\s*)?(\d{2,3})\s*年(?:度)?\s*([^\s\d號字]+)\s*字第\s*(\d+)\s*號', clean_case_id)
            if m:
                court = m.group(1) or court
                y = m.group(2)
                w = m.group(3)
                n = m.group(4)
            else:
                m_short = re.search(
                    r'(?:(臺灣[^\s]+法院|最高法院|最高行政法院|臺[北中南高]等[行政]*法院|[A-Za-z]+)\s*)?(\d{2,3})\s*(?:年|年度)?\s*([^\s\d號字]+?)\s*(?:字)?\s*(?:第)?\s*(\d+)\s*(?:號)?',
                    clean_case_id
                )
                if m_short:
                    raw_c = m_short.group(1) or ""
                    if any(k in raw_c for k in ["SC", "最高院"]):
                        court = "最高法院"
                    elif any(k in raw_c for k in ["高院", "高等"]):
                        court = "臺灣高等法院"
                    y = m_short.group(2)
                    w = m_short.group(3)
                    n = m_short.group(4)

        if is_remote:
            lookup_q = clean_case_id or f"{court} {y} 年度{w}字第 {n} 號".strip()
            rem = db_eng.find_by_citation(lookup_q)
            if not rem or not rem.get("found"):
                return {"success": False, "target_case_id": clean_case_id, "error": "於遠端裁判母庫中查無此裁判紀錄", "priors": [], "subsequents": [], "timeline": []}
            cur_h = rem.get("holding_snippet") or rem.get("text") or ""
            cur_disp = infer_disposition_intelligence(cur_h)
            timeline = [{
                "order": 2, "stage": "📍 當前檢視裁判", "case_id": rem.get("case_id"),
                "court": rem.get("court"), "date": rem.get("date", ""), "holding": cur_h,
                "disposition": cur_disp["disposition"], "disposition_badge": cur_disp["badge"],
                "is_reversal": cur_disp["is_reversal"], "badge_color": cur_disp["badge_color"]
            }]
            return {
                "success": True,
                "current": {"case_id": rem.get("case_id"), "court": rem.get("court"), "year": rem.get("jud_year", y), "word": rem.get("jud_word", w), "no": rem.get("jud_no", n), "date": rem.get("date", ""), "title": rem.get("title", ""), "holding": cur_h, "laws_cited": rem.get("laws_cited", [])},
                "priors": [], "subsequents": [], "timeline": timeline, "total_instances": len(timeline)
            }

        meta_tbl = getattr(db_eng, "_meta_table", "judgments_meta") if db_eng else "judgments_meta"
        table_cols = getattr(db_eng, "_table_cols", set()) if db_eng else set()
        has_redirects = getattr(db_eng, "_has_redirects_table", True) if db_eng else True

        def _col_sel(col_name: str, fallback_expr: str = "''") -> str:
            if not table_cols or col_name in table_cols:
                return col_name
            return f"{fallback_expr} AS {col_name}"

        select_cols = ", ".join([
            "case_id", "court", "jud_year", "jud_word", "jud_no", "date", "title",
            "holding_preview",
            _col_sel("history_instances"),
            _col_sel("substantive_prior"),
            "laws_cited", "jid"
        ])

        current_row = None
        with self._get_connection() as conn:
            if y and w and n:
                word_candidates = [w]
                w_clean = re.sub(r'字$', '', w).strip()
                if w_clean != w:
                    word_candidates.append(w_clean)
                if w_clean == "台上":
                    word_candidates.extend(["台上大", "台上大四", "台抗", "台非"])
                elif w_clean == "台上大":
                    word_candidates.extend(["台上", "台上大四"])
                elif "上更" in w_clean:
                    for repl in ["上更(一)", "上更㈠", "上更1", "上更(二)", "上更㈡", "上更2", "上更(三)", "上更㈢", "上更3", "上更(四)", "上更㈣", "上更4"]:
                        word_candidates.append(repl)

                for cand_w in word_candidates:
                    current_row = conn.execute(
                        f"SELECT {select_cols} FROM {meta_tbl} WHERE jud_year = ? AND jud_word = ? AND jud_no = ? LIMIT 1",
                        (y, cand_w, n)
                    ).fetchone()
                    if current_row:
                        break

            if not current_row and clean_case_id:
                current_row = conn.execute(
                    f"SELECT {select_cols} FROM {meta_tbl} WHERE case_id = ? LIMIT 1",
                    (clean_case_id,)
                ).fetchone()

            if not current_row:
                return {
                    "success": False,
                    "target_case_id": clean_case_id,
                    "error": "於裁判資料庫中查無此裁判主體紀錄",
                    "priors": [],
                    "subsequents": [],
                    "timeline": []
                }

            cur_case_id = current_row["case_id"]
            priors = []
            subsequents = []

            raw_instances = current_row["history_instances"]
            if raw_instances:
                try:
                    inst_list = json.loads(raw_instances)
                    for item in inst_list:
                        p_cid = item.get("case_id", "")
                        p_court = item.get("court", "")
                        p_role = item.get("role", "前審裁判")
                        p_snippet = item.get("snippet", "")
                        p_y = str(item.get("year", "")).strip()
                        p_w = str(item.get("track", "")).strip()
                        p_n = str(item.get("no", "")).strip()

                        p_meta = None
                        if p_y and p_w and p_n:
                            p_meta = conn.execute(
                                f"SELECT court, date, holding_preview, title FROM {meta_tbl} WHERE jud_year = ? AND jud_word = ? AND jud_no = ? LIMIT 1",
                                (p_y, p_w, p_n)
                            ).fetchone()

                        priors.append({
                            "case_id": p_cid,
                            "court": p_court or (p_meta["court"] if p_meta and p_meta["court"] else "事實審法院"),
                            "year": p_y,
                            "word": p_w,
                            "no": p_n,
                            "role": p_role,
                            "date": p_meta["date"] if p_meta and p_meta["date"] else "",
                            "holding": p_meta["holding_preview"] if p_meta and p_meta["holding_preview"] else p_snippet,
                            "relation": "PRIOR"
                        })
                except Exception:
                    pass

            if not priors and current_row["substantive_prior"]:
                sub_prior = current_row["substantive_prior"].strip()
                priors.append({
                    "case_id": sub_prior,
                    "court": "前審事實審法院",
                    "role": "實質前審事實審裁判",
                    "holding": "",
                    "relation": "PRIOR"
                })

            if has_redirects:
                try:
                    sub_redirs = conn.execute(
                        "SELECT dismissed_case_id, discard_reason, court FROM judgment_redirects WHERE substantive_prior_id = ? LIMIT 5",
                        (cur_case_id,)
                    ).fetchall()
                    for rd in sub_redirs:
                        subsequents.append({
                            "case_id": rd["dismissed_case_id"],
                            "court": rd["court"] or "上訴審法院",
                            "role": "上訴或審級關聯裁判",
                            "holding": rd["discard_reason"] or "",
                            "relation": "SUBSEQUENT"
                        })

                    prior_redirs = conn.execute(
                        "SELECT substantive_prior_id, discard_reason, court FROM judgment_redirects WHERE dismissed_case_id = ? LIMIT 3",
                        (cur_case_id,)
                    ).fetchall()
                    for rd in prior_redirs:
                        p_cid = rd["substantive_prior_id"]
                        if p_cid and not any(p.get("case_id") == p_cid for p in priors):
                            priors.append({
                                "case_id": p_cid,
                                "court": rd["court"] or "前審實體法院",
                                "role": "實質前審裁判",
                                "holding": rd["discard_reason"] or "",
                                "relation": "PRIOR"
                            })
                except Exception:
                    pass

            # 4. 組織為結構化時間軸（結合審級結論與逆轉訊號偵測）
            timeline = []
            for p in priors:
                p_h = p.get("holding") or ""
                disp = infer_disposition_intelligence(p_h)
                timeline.append({
                    "order": 1,
                    "stage": p.get("role", "第一審/前審事實審"),
                    "case_id": p.get("case_id"),
                    "court": p.get("court"),
                    "date": p.get("date"),
                    "holding": p_h,
                    "disposition": disp["disposition"],
                    "disposition_badge": disp["badge"],
                    "is_reversal": disp["is_reversal"],
                    "badge_color": disp["badge_color"]
                })

            cur_h = current_row["holding_preview"] or current_row["title"] or ""
            cur_disp = infer_disposition_intelligence(cur_h)
            timeline.append({
                "order": 2,
                "stage": "📍 當前檢視裁判",
                "case_id": cur_case_id,
                "court": current_row["court"],
                "date": current_row["date"],
                "holding": cur_h,
                "disposition": cur_disp["disposition"],
                "disposition_badge": cur_disp["badge"],
                "is_reversal": cur_disp["is_reversal"],
                "badge_color": cur_disp["badge_color"]
            })

            for s in subsequents:
                s_h = s.get("holding") or ""
                s_disp = infer_disposition_intelligence(s_h)
                timeline.append({
                    "order": 3,
                    "stage": s.get("role", "後續上訴/更審審級"),
                    "case_id": s.get("case_id"),
                    "court": s.get("court"),
                    "date": s.get("date"),
                    "holding": s_h,
                    "disposition": s_disp["disposition"],
                    "disposition_badge": s_disp["badge"],
                    "is_reversal": s_disp["is_reversal"],
                    "badge_color": s_disp["badge_color"]
                })

            return {
                "success": True,
                "current": {
                    "case_id": cur_case_id,
                    "court": current_row["court"],
                    "year": current_row["jud_year"],
                    "word": current_row["jud_word"],
                    "no": current_row["jud_no"],
                    "date": current_row["date"],
                    "title": current_row["title"],
                    "holding": current_row["holding_preview"],
                    "laws_cited": current_row["laws_cited"]
                },
                "priors": priors,
                "subsequents": subsequents,
                "timeline": timeline,
                "total_instances": len(timeline)
            }


_appeal_engine = None

def get_appeal_chain_engine() -> JudicialAppealChainEngine:
    global _appeal_engine
    if _appeal_engine is None:
        _appeal_engine = JudicialAppealChainEngine()
    return _appeal_engine
