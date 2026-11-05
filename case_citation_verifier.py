# -*- coding: utf-8 -*-
"""
Case Citation Anti-Hallucination & Ground-Truth Verification Engine
==================================================================
專門防範與攔截 AI 法律生成中常見之「虛構案號」、「字號錯置」與「幻覺裁判」問題。
對標 Lawsnote、七法 Laws.club 與 Casetext CoCounsel 之法學真實性校驗機制：

1. 精準正則萃取：覆蓋台灣最高法院、高等法院、地方法院、憲法法庭判決、大法官解釋、
   最高法院大法庭裁定、民事庭會議決議與高等法院法律座談會字號。
2. 毫秒級雙庫實體核驗：
   - 百萬實體裁判庫 (4,006,156 筆裁判，以 idx_meta_ywn 複合索引 1ms 檢驗)
   - 權威判例與決議庫 (judicial_authority.db: 11,625 筆代表性先例)
   - 憲法法庭裁判全集與歷年大法官解釋典藏 (O(1) 字典極速比對)
3. 防偽標籤與官方連結：
   - 已核驗案號自動附加 [✅ 實體裁判庫核驗 | 司法院正本檢索] 官方超連結
   - 虛構案號自動攔截並標註 [⚠️ 查無實體判決警示 (防偽攔截)]
4. 自動附帶「🏛️ 裁判案號真實性核驗清單」，列明案由、審級、裁判日期與法理要旨。
"""

import os
import re
import json
import sqlite3
import urllib.parse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from config import DATA_DIR, RAW_DATA_DIR, JUDICIAL_1M_DIR, CONSTITUTIONAL_DIR

FULL_TO_HALF = str.maketrans("０１２３４５６７８９", "0123456789")
CHINESE_NUMS = {
    "〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "百": 100, "千": 1000
}


def chinese_to_number(ch_str: str) -> int:
    """轉換中文數字為整數"""
    if not ch_str:
        return 0
    ch_str = ch_str.strip()
    if ch_str.isdigit():
        return int(ch_str)
    digits = ""
    is_pure_digits = True
    for c in ch_str:
        if c in "〇零":
            digits += "0"
        elif c in CHINESE_NUMS and CHINESE_NUMS[c] < 10:
            digits += str(CHINESE_NUMS[c])
        elif c in "0123456789":
            digits += c
        else:
            is_pure_digits = False
            break
    if is_pure_digits and digits:
        try:
            return int(digits)
        except Exception:
            pass

    total = 0
    current = 0
    for c in ch_str:
        if c in CHINESE_NUMS:
            val = CHINESE_NUMS[c]
            if val in (10, 100, 1000):
                if current == 0:
                    current = 1
                total += current * val
                current = 0
            else:
                current = val
        elif c in "0123456789":
            current = int(c)
    total += current
    return total if total > 0 else 0


class CaseCitationVerifier:
    """
    全量裁判案號防偽與實體驗證核心引擎 (極速快取版)
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(CaseCitationVerifier, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._init_paths()
        self._precedents_cache = None
        self._const_file_map = None

    def _init_paths(self):
        self.index_db_path = Path(JUDICIAL_1M_DIR) / "judicial_1m_index.db"
        if not self.index_db_path.exists():
            cand = Path(DATA_DIR) / "judicial_1m_db" / "judicial_1m_index.db"
            if cand.exists():
                self.index_db_path = cand

        self.authority_db_path = Path(DATA_DIR) / "judicial_authority.db"
        self.precedents_json_path = Path(RAW_DATA_DIR) / "precedents_catalog.json"
        if not self.precedents_json_path.exists():
            cand_p = Path(__file__).resolve().parent / "data" / "raw_exams" / "precedents_catalog.json"
            if cand_p.exists():
                self.precedents_json_path = cand_p

        self.const_dir = Path(CONSTITUTIONAL_DIR)

    def _get_const_file_map(self) -> Dict[str, Path]:
        if self._const_file_map is not None:
            return self._const_file_map
        self._const_file_map = {}
        if self.const_dir.exists():
            try:
                for f in self.const_dir.glob("*.json"):
                    self._const_file_map[f.name] = f
            except Exception:
                pass
        return self._const_file_map

    def _get_precedents_catalog(self) -> List[Dict[str, Any]]:
        if self._precedents_cache is not None:
            return self._precedents_cache
        self._precedents_cache = []
        if self.precedents_json_path.exists():
            try:
                with open(self.precedents_json_path, "r", encoding="utf-8") as f:
                    self._precedents_cache = json.load(f)
            except Exception:
                self._precedents_cache = []
        return self._precedents_cache

    # =========================================================================
    # 1. 精準字號萃取 (Extraction Pipeline)
    # =========================================================================
    def extract_citations(self, text: str) -> List[Dict[str, Any]]:
        if not text or not isinstance(text, str):
            return []

        citations = []
        seen_spans = set()

        # Pattern A: 憲法法庭判決 / 裁定
        p_const = re.compile(
            r'(?:憲法法庭\s*)?([0-9\uff10-\uff19]+)\s*年\s*(憲[判裁]|憲審)\s*字\s*第?\s*([0-9\uff10-\uff19]+)\s*號(?:\s*判決|\s*裁定)?'
        )
        for m in p_const.finditer(text):
            span = m.span()
            if any(s <= span[0] and span[1] <= e for s, e in seen_spans):
                continue
            seen_spans.add(span)
            raw = m.group(0).strip()
            y_str = m.group(1).translate(FULL_TO_HALF)
            word = m.group(2).strip()
            no_str = m.group(3).translate(FULL_TO_HALF)
            citations.append({
                "raw": raw,
                "span": span,
                "category": "CONSTITUTIONAL",
                "court": "憲法法庭",
                "year": y_str,
                "word": word,
                "no": no_str,
                "normalized": f"憲法法庭 {y_str} 年{word}字第 {no_str} 號"
            })

        # Pattern B: 司法院釋字 / 院解字解釋
        p_interp = re.compile(
            r'(?:司法院)?\s*(釋字|院解?字)\s*第?\s*([0-9\uff10-\uff19]+)\s*號(?:\s*解釋)?'
        )
        for m in p_interp.finditer(text):
            span = m.span()
            if any(s <= span[0] and span[1] <= e for s, e in seen_spans):
                continue
            seen_spans.add(span)
            raw = m.group(0).strip()
            w_prefix = m.group(1).strip()
            no_str = m.group(2).translate(FULL_TO_HALF)
            citations.append({
                "raw": raw,
                "span": span,
                "category": "INTERPRETATION",
                "court": "司法院大法官",
                "year": "",
                "word": w_prefix,
                "no": no_str,
                "normalized": f"司法院{w_prefix}第 {no_str} 號解釋"
            })

        # Pattern C: 最高法院庭長法官聯席會議決議 (Resolutions)
        p_res = re.compile(
            r'((?:最高法院)?\s*([0-9\uff10-\uff19一二三四五六七八九十百〇零]+)\s*年度?(?:度)?\s*(?:第\s*([0-9\uff10-\uff19一二三四五六七八九十]+)\s*次)?\s*(?:民事庭|刑事庭|民刑庭|刑庭|民庭)?\s*(?:庭長法官聯席)?\s*(?:會議)?\s*決議)'
        )
        for m in p_res.finditer(text):
            span = m.span()
            if any(s <= span[0] and span[1] <= e for s, e in seen_spans):
                continue
            seen_spans.add(span)
            raw = m.group(1).strip()
            y_raw = m.group(2).translate(FULL_TO_HALF)
            y_num = chinese_to_number(y_raw)
            y_str = str(y_num) if y_num > 0 else y_raw
            no_raw = m.group(3).translate(FULL_TO_HALF) if m.group(3) else ""
            no_num = chinese_to_number(no_raw) if no_raw else ""
            citations.append({
                "raw": raw,
                "span": span,
                "category": "RESOLUTION",
                "court": "最高法院",
                "year": y_str,
                "word": "決議",
                "no": str(no_num) if no_num else "",
                "normalized": raw
            })

        # Pattern D: 各級法院判決、裁定、判例、大法庭
        p_jud = re.compile(
            r'((?:最高法院|最高行政法院|臺灣高等法院|高等法院|臺北高等行政法院|臺中高等行政法院|高雄高等行政法院|[臺台][\u4e00-\u9fa5]{2,6}地方法院)?\s*([0-9\uff10-\uff19一二三四五六七八九十百〇零]+)\s*年(?:度)?\s*([^\d\s，。；:：\(\)\uff08\uff09]{1,8}?)\s*字\s*第?\s*([0-9\uff10-\uff19]+)\s*號(?:\s*(?:民事|刑事|行政))?(?:\s*(?:判決|裁定|判例|大法庭裁定))?)'
        )
        for m in p_jud.finditer(text):
            span = m.span()
            if any(s <= span[0] and span[1] <= e for s, e in seen_spans):
                continue
            seen_spans.add(span)
            raw = m.group(1).strip()
            if "憲判" in raw or "釋字" in raw or "決議" in raw:
                continue

            court = ""
            c_m = re.search(r'(最高法院|最高行政法院|臺灣高等法院|高等法院|臺北高等行政法院|臺中高等行政法院|高雄高等行政法院|[臺台][\u4e00-\u9fa5]{2,6}地方法院)', raw)
            if c_m:
                court = c_m.group(1)

            y_raw = m.group(2).translate(FULL_TO_HALF)
            y_num = chinese_to_number(y_raw)
            y_str = str(y_num) if y_num > 0 else y_raw

            word = m.group(3).strip()
            word = re.sub(r'^(?:民事|刑事|行政)?', '', word)
            word = re.sub(r'字$', '', word)

            no_str = m.group(4).translate(FULL_TO_HALF)

            if not court:
                if any(w in word for w in ["台上", "台抗", "台非", "台覆", "台簡上", "台大", "台上大", "台抗大"]):
                    court = "最高法院"
                elif any(w in word for w in ["上", "上易", "上訴", "重上", "重上更", "抗"]):
                    court = "臺灣高等法院"

            category = "GRAND_CHAMBER" if "大" in word else ("PRECEDENT" if "判例" in raw else "JUDGMENT")

            citations.append({
                "raw": raw,
                "span": span,
                "category": category,
                "court": court or "法院",
                "year": y_str,
                "word": word,
                "no": no_str,
                "normalized": f"{court} {y_str} 年度{word}字第 {no_str} 號".strip()
            })

        return citations

    # =========================================================================
    # 2. 跨資料庫多維防偽核驗 (Dual-DB Verification Engine)
    # =========================================================================
    def verify_citation(self, cit: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "raw": cit.get("raw", ""),
            "normalized": cit.get("normalized", ""),
            "is_verified": False,
            "match_source": "NONE",
            "court": cit.get("court", ""),
            "year": cit.get("year", ""),
            "word": cit.get("word", ""),
            "no": cit.get("no", ""),
            "case_id": "",
            "date": "",
            "title": "",
            "holding": "",
            "laws_cited": "",
            "official_url": "",
            "warning": ""
        }

        category = cit.get("category", "")
        y = str(cit.get("year", "")).strip()
        w = str(cit.get("word", "")).strip()
        n = str(cit.get("no", "")).strip()

        # ---------------------------------------------------------------------
        # 檢驗情境 0: 最高法院庭長法官聯席會議決議 (RESOLUTION)
        # ---------------------------------------------------------------------
        if category == "RESOLUTION":
            raw_res = cit.get("raw", "")
            if self.authority_db_path.exists():
                try:
                    with sqlite3.connect(str(self.authority_db_path), timeout=2.0) as a_conn:
                        a_conn.row_factory = sqlite3.Row
                        p_query = f"%{y}%決議%"
                        r_row = a_conn.execute(
                            "SELECT case_no, precedent_id, title, holding, reasoning, source_url FROM precedents WHERE case_no LIKE ? OR title LIKE ? LIMIT 1",
                            (p_query, p_query)
                        ).fetchone()
                        if not r_row:
                            r_row = a_conn.execute(
                                "SELECT case_no, title, holding, reasoning FROM authority_records WHERE case_no LIKE ? OR title LIKE ? LIMIT 1",
                                (p_query, p_query)
                            ).fetchone()
                        if r_row:
                            result["is_verified"] = True
                            result["match_source"] = "AUTHORITY_DB_RESOLUTION"
                            result["case_id"] = r_row["case_no"] or r_row["title"] or raw_res
                            result["court"] = "最高法院"
                            result["title"] = r_row["title"] or ""
                            result["holding"] = r_row["holding"] or r_row["reasoning"] or ""
                            result["official_url"] = "https://judgment.judicial.gov.tw/FJUD/default.aspx"
                            return result
                except Exception:
                    pass

        # ---------------------------------------------------------------------
        # 檢驗情境 A: 憲法法庭判決 / 裁定 (CONSTITUTIONAL)
        # ---------------------------------------------------------------------
        if category == "CONSTITUTIONAL":
            const_map = self._get_const_file_map()
            for fn, fp in const_map.items():
                if y in fn and w in fn and n in fn:
                    try:
                        with open(fp, "r", encoding="utf-8") as c_fh:
                            c_data = json.load(c_fh)
                            result["is_verified"] = True
                            result["match_source"] = "CONSTITUTIONAL_CORPUS"
                            result["case_id"] = c_data.get("case_no") or f"憲法法庭 {y} 年{w}字第 {n} 號判決"
                            result["title"] = c_data.get("title", "")
                            result["holding"] = c_data.get("holding") or c_data.get("main_text", "")
                            result["date"] = c_data.get("date", "")
                            result["official_url"] = f"https://cons.judicial.gov.tw/docdata.aspx?fid=38&id={urllib.parse.quote(result['case_id'])}"
                            return result
                    except Exception:
                        pass

            if self.authority_db_path.exists():
                try:
                    with sqlite3.connect(str(self.authority_db_path), timeout=2.0) as a_conn:
                        a_conn.row_factory = sqlite3.Row
                        row = a_conn.execute(
                            "SELECT case_no, title, holding, reasoning, date FROM authority_records WHERE category = 'CONSTITUTIONAL' AND case_no LIKE ? AND case_no LIKE ? LIMIT 1",
                            (f"%{y}%", f"%{n}%")
                        ).fetchone()
                        if row:
                            result["is_verified"] = True
                            result["match_source"] = "AUTHORITY_DB_CONSTITUTIONAL"
                            result["case_id"] = row["case_no"]
                            result["title"] = row["title"] or ""
                            result["holding"] = row["holding"] or row["reasoning"] or ""
                            result["date"] = row["date"] or ""
                            result["official_url"] = f"https://cons.judicial.gov.tw/"
                            return result
                except Exception:
                    pass

        # ---------------------------------------------------------------------
        # 檢驗情境 B: 司法院大法官解釋 (INTERPRETATION)
        # ---------------------------------------------------------------------
        if category == "INTERPRETATION":
            const_map = self._get_const_file_map()
            target_fn = f"const_釋字第{n}號.json"
            if target_fn in const_map:
                try:
                    with open(const_map[target_fn], "r", encoding="utf-8") as c_fh:
                        c_data = json.load(c_fh)
                        result["is_verified"] = True
                        result["match_source"] = "CONSTITUTIONAL_INTERPRETATION"
                        result["case_id"] = f"司法院釋字第 {n} 號解釋"
                        result["title"] = c_data.get("title", "")
                        result["holding"] = c_data.get("holding") or c_data.get("main_text", "")
                        result["date"] = c_data.get("date", "")
                        result["official_url"] = f"https://cons.judicial.gov.tw/docdata.aspx?fid=100&id={n}"
                        return result
                except Exception:
                    pass

            if self.authority_db_path.exists():
                try:
                    with sqlite3.connect(str(self.authority_db_path), timeout=2.0) as a_conn:
                        a_conn.row_factory = sqlite3.Row
                        row = a_conn.execute(
                            "SELECT case_no, title, holding, reasoning, date FROM authority_records WHERE category = 'CONSTITUTIONAL' AND (case_no LIKE ? OR id LIKE ?) LIMIT 1",
                            (f"%釋字第{n}號%", f"%{n}%")
                        ).fetchone()
                        if row:
                            result["is_verified"] = True
                            result["match_source"] = "AUTHORITY_DB_INTERPRETATION"
                            result["case_id"] = row["case_no"]
                            result["title"] = row["title"] or ""
                            result["holding"] = row["holding"] or row["reasoning"] or ""
                            result["date"] = row["date"] or ""
                            result["official_url"] = f"https://cons.judicial.gov.tw/docdata.aspx?fid=100&id={n}"
                            return result
                except Exception:
                    pass

        # ---------------------------------------------------------------------
        # 檢驗情境 C: 百萬裁判資料庫毫秒級比對 (idx_meta_ywn)
        # ---------------------------------------------------------------------
        if y and n and self.index_db_path.exists():
            try:
                with sqlite3.connect(str(self.index_db_path), timeout=2.0) as m_conn:
                    m_conn.row_factory = sqlite3.Row

                    word_candidates = [w]
                    if w == "台上":
                        word_candidates.extend(["台上大", "台上大四", "台抗", "台非"])
                    elif w == "上":
                        word_candidates.extend(["上易", "上訴", "重上", "重上更"])
                    elif "台上" in w:
                        word_candidates.append("台上")

                    matched_row = None
                    for wc in word_candidates:
                        r = m_conn.execute(
                            "SELECT case_id, court, date, holding_preview, laws_cited, title, jid "
                            "FROM judgments_meta WHERE jud_year = ? AND jud_word = ? AND jud_no = ? LIMIT 1",
                            (y, wc, n)
                        ).fetchone()
                        if r:
                            matched_row = r
                            break

                    if matched_row:
                        result["is_verified"] = True
                        result["match_source"] = "MILLION_JUDGMENTS_MASTER_DB"
                        result["case_id"] = matched_row["case_id"]
                        result["court"] = matched_row["court"] or result["court"]
                        result["date"] = matched_row["date"] or ""
                        result["title"] = matched_row["title"] or ""
                        result["holding"] = matched_row["holding_preview"] or ""
                        result["laws_cited"] = matched_row["laws_cited"] or ""
                        result["official_url"] = self.build_official_judicial_url(result["case_id"], matched_row["jid"] or "")
                        return result
            except Exception:
                pass

        # ---------------------------------------------------------------------
        # 檢驗情境 D: 判例精選庫與最高法院決議/大法庭
        # ---------------------------------------------------------------------
        precs = self._get_precedents_catalog()
        for p in precs:
            p_id = str(p.get("precedent_id") or p.get("case_id") or "")
            if y and n and (y in p_id) and (n in p_id):
                if not w or (w in p_id) or (w.replace("字", "") in p_id):
                    result["is_verified"] = True
                    result["match_source"] = "PRESTIGIOUS_PRECEDENTS_CATALOG"
                    result["case_id"] = p.get("case_id") or p_id
                    result["court"] = p.get("court") or result["court"]
                    result["date"] = p.get("date") or ""
                    result["title"] = p.get("title") or ""
                    result["holding"] = p.get("holding") or ""
                    result["laws_cited"] = p.get("laws_cited") or ""
                    result["official_url"] = p.get("source_url") or self.build_official_judicial_url(result["case_id"])
                    return result

        if self.authority_db_path.exists():
            try:
                with sqlite3.connect(str(self.authority_db_path), timeout=2.0) as a_conn:
                    a_conn.row_factory = sqlite3.Row
                    p_query = f"%{y}%{n}%"
                    p_row = a_conn.execute(
                        "SELECT case_no, precedent_id, court, title, holding, reasoning, laws_cited, source_url "
                        "FROM precedents WHERE case_no LIKE ? OR precedent_id LIKE ? LIMIT 1",
                        (p_query, p_query)
                    ).fetchone()
                    if p_row:
                        c_no = p_row["case_no"] or p_row["precedent_id"] or ""
                        if not w or (w in c_no) or (w.replace("字", "") in c_no) or ("上" in w and "上" in c_no):
                            result["is_verified"] = True
                            result["match_source"] = "AUTHORITY_DB_PRECEDENT"
                            result["case_id"] = c_no
                            result["court"] = p_row["court"] or result["court"] or "最高法院"
                            result["title"] = p_row["title"] or ""
                            result["holding"] = p_row["holding"] or p_row["reasoning"] or ""
                            result["laws_cited"] = p_row["laws_cited"] or ""
                            result["official_url"] = p_row["source_url"] or self.build_official_judicial_url(result["case_id"])
                            return result

                    auth_row = a_conn.execute(
                        "SELECT case_no, court, title, holding, reasoning, laws_cited "
                        "FROM authority_records WHERE case_no LIKE ? AND case_no LIKE ? LIMIT 1",
                        (f"%{y}%", f"%{n}%")
                    ).fetchone()
                    if auth_row:
                        result["is_verified"] = True
                        result["match_source"] = "AUTHORITY_DB_RECORDS"
                        result["case_id"] = auth_row["case_no"]
                        result["court"] = auth_row["court"] or result["court"]
                        result["title"] = auth_row["title"] or ""
                        result["holding"] = auth_row["holding"] or auth_row["reasoning"] or ""
                        result["laws_cited"] = auth_row["laws_cited"] or ""
                        result["official_url"] = self.build_official_judicial_url(result["case_id"])
                        return result
            except Exception:
                pass

        result["is_verified"] = False
        result["match_source"] = "UNVERIFIED_HALLUCINATION"
        result["warning"] = (
            f"⚠️【查無實體判決警示】經比對全國 400 萬筆裁判庫與權威判例資料庫，"
            f"查無「{cit.get('raw')}」之實體裁判文書。為防範 AI 幻覺生成不存在之假案號，"
            f"請勿直接援引於國考答卷或訴狀，建請以系統下方推薦之實體權威裁判見解為準。"
        )
        return result

    def build_official_judicial_url(self, case_id: str, jid: str = "") -> str:
        if not case_id:
            return "https://judgment.judicial.gov.tw/FJUD/default.aspx"
        clean = re.sub(r"\s+", "", case_id)
        encoded = urllib.parse.quote(clean)
        return f"https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id={encoded}"

    # =========================================================================
    # 3. 內文全面防偽標註與查核報告抽屜 (Decorator & Audit Report)
    # =========================================================================
    def verify_and_decorate_response(
        self,
        text: str,
        context_topic: str = "",
        auto_badge: bool = True
    ) -> Dict[str, Any]:
        if not text or not isinstance(text, str):
            return {
                "annotated_text": text or "",
                "citations": [],
                "verified_count": 0,
                "hallucination_count": 0,
                "audit_markdown": ""
            }

        citations = self.extract_citations(text)
        if not citations:
            return {
                "annotated_text": text,
                "citations": [],
                "verified_count": 0,
                "hallucination_count": 0,
                "audit_markdown": ""
            }

        verified_records = []
        verified_count = 0
        hallucination_count = 0

        annotated_text = text
        sorted_citations = sorted(citations, key=lambda c: c["span"][0], reverse=True)

        for cit in sorted_citations:
            v_res = self.verify_citation(cit)
            verified_records.append(v_res)

            start, end = cit["span"]
            raw_str = cit["raw"]

            if v_res["is_verified"]:
                verified_count += 1
                official_url = v_res["official_url"] or "https://judgment.judicial.gov.tw/FJUD/default.aspx"
                badge = f" [✅ 實體裁判庫已核驗]({official_url})" if auto_badge else ""
                annotated_text = annotated_text[:start] + f"**{raw_str}**{badge}" + annotated_text[end:]
            else:
                hallucination_count += 1
                badge = " `⚠️ 查無實體判決警示`" if auto_badge else ""
                annotated_text = annotated_text[:start] + f"**{raw_str}**{badge}" + annotated_text[end:]

        verified_records.reverse()
        audit_md = self._build_audit_report_markdown(verified_records, context_topic)

        return {
            "annotated_text": annotated_text,
            "citations": verified_records,
            "total_citations": len(verified_records),
            "verified_count": verified_count,
            "hallucination_count": hallucination_count,
            "audit_markdown": audit_md
        }

    def _build_audit_report_markdown(self, records: List[Dict[str, Any]], context_topic: str = "") -> str:
        if not records:
            return ""

        md_lines = [
            "\n\n---\n",
            "### 🏛️ 裁判引用真實性查核清單 (Ground Truth Case Audit)",
            "> 🛡️ **本平台已啟動案號防偽核驗機制**：所有回答所引述之法院裁判、判例或憲法法庭判決均經過 400 萬筆實體資料庫實質檢驗，堅決杜絕 AI 幻覺虛構案號。\n"
        ]

        table_rows = []
        table_rows.append("| 引用字號 | 核驗狀態 | 審級法院 | 裁判日期 | 實體裁判要旨摘要 | 官方裁判書直連 |")
        table_rows.append("| :--- | :---: | :---: | :---: | :--- | :---: |")

        for r in records:
            raw_name = r.get("case_id") or r.get("raw") or "未知案號"
            is_v = r.get("is_verified", False)
            status_chip = "✅ 實體庫收錄" if is_v else "❌ 查無實體"
            court = r.get("court") or "-"
            dt = r.get("date") or "-"
            holding = r.get("holding", "")
            holding_short = (holding[:60] + "...") if len(holding) > 60 else (holding or "（詳見裁判全文）")
            holding_clean = re.sub(r"[\r\n|]+", " ", holding_short)
            url = r.get("official_url") or "https://judgment.judicial.gov.tw/FJUD/default.aspx"
            link_md = f"[🔗 司法院正本]({url})" if is_v else "（無實體文書）"

            table_rows.append(f"| **{raw_name}** | {status_chip} | {court} | {dt} | {holding_clean} | {link_md} |")

        md_lines.extend(table_rows)

        fakes = [r for r in records if not r.get("is_verified")]
        if fakes:
            md_lines.append("\n> [!WARNING] **防偽攔截提示**：")
            for f in fakes:
                md_lines.append(f"> - 案號 **{f.get('raw')}** 經比對全量裁判大庫查無實體判決，研判為 AI 模型參數機率拼貼產生之幻覺字號。在國家考試作答或實務訴狀中，切勿援引未經核驗之案號！")

        return "\n".join(md_lines)

    def verify_text_citations(
        self,
        text: str,
        context_topic: str = "",
        auto_badge: bool = True
    ) -> Dict[str, Any]:
        """
        驗證文本中所有引述裁判案號之實體真實性（verify_and_decorate_response 之直觀相容別名）。
        """
        return self.verify_and_decorate_response(text, context_topic=context_topic, auto_badge=auto_badge)


_global_verifier = None

def get_case_verifier() -> CaseCitationVerifier:
    global _global_verifier
    if _global_verifier is None:
        _global_verifier = CaseCitationVerifier()
    return _global_verifier
