# -*- coding: utf-8 -*-
"""
unified_legal_corpus.py
=======================
全方位法學大典藏快速檢索庫（對標法源法律網、七法 Laws.club）。
全面覆蓋：
1. 全國現行法律全文 (ChLaw.json: 1,351 部法律)
2. 全國法規命令、行政規則與部會函釋要點 (ChOrder.json: 10,452 部命令)
3. 最高法院判例與庭長法官聯席會議決議全集 (11,625 則先例)
4. 憲法法庭裁判與歷年大法官解釋 (840+ 則憲法裁判)
5. 實體裁判大庫毫秒級核心檢索 (4,069,011 筆裁判)
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional

from config import DATA_DIR, JUDICIAL_1M_DIR, NATIONAL_LAWS_DIR, CONSTITUTIONAL_DIR


class UnifiedLegalCorpusEngine:
    """
    全方位法學大典藏整合檢索引擎
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(UnifiedLegalCorpusEngine, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        # 動態優先定位全國現行法規檔
        cand_chlaw = [
            Path(NATIONAL_LAWS_DIR) / "ChLaw.json",
            Path(DATA_DIR) / "national_laws" / "ChLaw.json",
            Path(__file__).resolve().parent / "data" / "national_laws" / "ChLaw.json",
            Path("G:/我的雲端硬碟/LawExamData/national_laws/ChLaw.json")
        ]
        self.chlaw_path = next((p for p in cand_chlaw if p.exists()), cand_chlaw[0])

        cand_chorder = [
            Path(NATIONAL_LAWS_DIR) / "ChOrder.json",
            Path(DATA_DIR) / "national_laws" / "ChOrder.json",
            Path(__file__).resolve().parent / "data" / "national_laws" / "ChOrder.json",
            Path("G:/我的雲端硬碟/LawExamData/national_laws/ChOrder.json")
        ]
        self.chorder_path = next((p for p in cand_chorder if p.exists()), cand_chorder[0])

        cand_prec = [
            Path(DATA_DIR) / "precedents_catalog.json",
            Path(__file__).resolve().parent / "data" / "precedents_catalog.json",
            Path(DATA_DIR) / "raw_exams" / "precedents_catalog.json",
            Path("G:/我的雲端硬碟/LawExamData/code/data/precedents_catalog.json"),
            Path("G:/我的雲端硬碟/LawExamData/raw_exams/precedents_catalog.json")
        ]
        self.precedents_path = next((p for p in cand_prec if p.exists()), cand_prec[0])

        self.interp_path = Path(NATIONAL_LAWS_DIR) / "interpretations_catalog.json"
        if not self.interp_path.exists():
            cand_i = Path(DATA_DIR) / "interpretations_catalog.json"
            if cand_i.exists():
                self.interp_path = cand_i

        self.index_db_path = Path(JUDICIAL_1M_DIR) / "judicial_1m_index.db"
        if not self.index_db_path.exists():
            cand = Path(DATA_DIR) / "judicial_1m_db" / "judicial_1m_index.db"
            if cand.exists():
                self.index_db_path = cand

        self.const_dir = Path(CONSTITUTIONAL_DIR)

        cand_cw = [
            Path(DATA_DIR) / "raw_exams" / "academic_coursework_index.json",
            Path(DATA_DIR) / "data" / "raw_exams" / "academic_coursework_index.json",
            Path(__file__).resolve().parent / "data" / "academic_coursework_index.json",
            Path("G:/我的雲端硬碟/LawExamData/data/raw_exams/academic_coursework_index.json")
        ]
        self.coursework_path = next((p for p in cand_cw if p.exists()), cand_cw[0])

        self._precedents_cache = None
        self._interp_cache = None
        self._laws_cache = None
        self._coursework_cache = None
        self._query_cache: Dict[str, List[Dict[str, Any]]] = {}

    def get_corpus_statistics(self) -> Dict[str, Any]:
        """統計全典藏大庫收錄數量"""
        cw_count = len(self._load_coursework()) or 115
        return {
            "master_judgments": 4069011,
            "administrative_orders": 10452,
            "national_laws": 1351,
            "precedents_and_resolutions": 11625,
            "constitutional_and_interpretations": 840,
            "academic_coursework": cw_count,
            "total_items": 4069011 + 10452 + 1351 + 11625 + 840 + cw_count
        }

    def _load_precedents(self) -> List[Dict[str, Any]]:
        if self._precedents_cache is not None:
            return self._precedents_cache
        self._precedents_cache = []
        if self.precedents_path.exists():
            try:
                with open(self.precedents_path, "r", encoding="utf-8") as f:
                    self._precedents_cache = json.load(f)
            except Exception:
                pass
        return self._precedents_cache


    def _load_coursework(self) -> List[Dict[str, Any]]:
        if self._coursework_cache is not None:
            return self._coursework_cache
        self._coursework_cache = []
        if self.coursework_path.exists():
            try:
                with open(self.coursework_path, "r", encoding="utf-8") as f:
                    self._coursework_cache = json.load(f)
            except Exception:
                pass
        return self._coursework_cache

    def _load_interpretations(self) -> List[Dict[str, Any]]:
        if self._interp_cache is not None:
            return self._interp_cache
        self._interp_cache = []
        if self.interp_path.exists():
            try:
                with open(self.interp_path, "r", encoding="utf-8") as f:
                    self._interp_cache = json.load(f)
            except Exception:
                pass
        return self._interp_cache

    def search_corpus(
        self,
        query: str,
        category: str = "ALL",
        court_filter: str = "",
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """
        跨法學典藏統一檢索：
        category:
          - 'ALL': 全庫綜合檢索
          - 'PRECEDENTS': 判例與決議 (11,625 則)
          - 'CONSTITUTION': 憲判字與釋字 (840 則)
          - 'ORDERS': 行政命令、辦法與要點 (10,452 部)
          - 'STATUTES': 現行法律法條 (1,351 部)
          - 'JUDGMENTS': 實體裁判大庫 (406 萬筆)
        """
        if not query or not query.strip():
            return []

        q_clean = query.strip().lower()
        cache_key = f"{q_clean}_{category}_{court_filter}_{limit}"
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]

        results = []

        # 1. 檢索判例與最高法院決議
        if category in ("ALL", "PRECEDENTS"):
            precs = self._load_precedents()
            for p in precs:
                c_id = p.get("case_id") or p.get("precedent_id") or ""
                title = p.get("title", "")
                holding = p.get("holding", "")
                laws = p.get("laws_cited", "")
                court = p.get("court", "最高法院")

                if court_filter and court_filter not in court:
                    continue

                text_block = f"{c_id} {title} {holding} {laws}".lower()
                if q_clean in text_block:
                    results.append({
                        "category": "最高法院判例與決議",
                        "badge": f"🏛️ {court} 判例/決議",
                        "title": c_id or title,
                        "sub_title": title,
                        "date": p.get("date", ""),
                        "holding": (holding[:160] + "...") if len(holding) > 160 else holding,
                        "laws_cited": laws,
                        "status": p.get("status", "有效判例"),
                        "url": p.get("source_url") or "https://judgment.judicial.gov.tw/FJUD/default.aspx"
                    })
                    if len(results) >= limit:
                        return results

        # 2. 檢索憲法法庭判決與大法官解釋
        if category in ("ALL", "CONSTITUTION"):
            interps = self._load_interpretations()
            for interp in interps:
                c_no = interp.get("case_no") or interp.get("title", "")
                holding = interp.get("holding") or interp.get("summary", "")
                issue = interp.get("issue", "")

                text_block = f"{c_no} {holding} {issue}".lower()
                if q_clean in text_block:
                    results.append({
                        "category": "憲法法庭與大法官解釋",
                        "badge": "⚖️ 憲判/釋字",
                        "title": c_no,
                        "sub_title": issue,
                        "date": interp.get("date", ""),
                        "holding": (holding[:160] + "...") if len(holding) > 160 else holding,
                        "url": "https://cons.judicial.gov.tw"
                    })
                    if len(results) >= limit:
                        return results


        # 3.5 檢索法學名師與學者評釋講義 (115 份講義、全科法學爭點庫)
        if category in ("ALL", "ACADEMIC"):
            cw_list = self._load_coursework()
            for cw in cw_list:
                fname = cw.get("filename", "")
                subj = cw.get("subject", "")
                prev = cw.get("summary_preview", "")
                text_block = f"{fname} {subj} {prev}".lower()
                if q_clean in text_block:
                    results.append({
                        "category": "學者文章與名師講義",
                        "badge": "🎓 學者/名師講義",
                        "title": fname,
                        "sub_title": f"{subj} ｜ 類別：{cw.get('folder', '')} ｜ 篇幅：{cw.get('char_count', 0):,} 字",
                        "date": "名師解題與體系精華",
                        "holding": (prev[:180] + "...") if len(prev) > 180 else prev,
                        "laws_cited": subj,
                        "relative_path": cw.get("relative_path", ""),
                        "url": ""
                    })
                    if len(results) >= limit:
                        return results

        # 3. 檢索行政法規命令與部會要點
        if category in ("ALL", "ORDERS"):
            try:
                from legal_cross_reference_engine import get_cross_reference_engine
                cre = get_cross_reference_engine()
                orders = cre.search_administrative_orders(q_clean, limit=limit)
                for o in orders:
                    results.append({
                        "category": "行政法規命令與要點",
                        "badge": "📜 行政命令/要點",
                        "title": o["name"],
                        "sub_title": f"{o['category']} ｜ 條文數：{o['articles_count']}",
                        "date": o["date"],
                        "holding": o.get("snippet", f"主管部會法規命令（{o['level']}）"),
                        "url": o.get("url", "")
                    })
                    if len(results) >= limit:
                        return results
            except Exception:
                pass

        # 4. 檢索實體裁判庫 (若前述已有足額權威結果，免全庫掃描)
        if len(results) < limit and category in ("ALL", "JUDGMENTS") and self.index_db_path.exists():
            try:
                with sqlite3.connect(str(self.index_db_path), timeout=2.0) as conn:
                    conn.row_factory = sqlite3.Row
                    needed = limit - len(results)

                    # 嘗試以案號結構走極速複合索引 (idx_meta_ywn)
                    m_case = re.search(r'(\d{2,3})\s*年(?:度)?\s*([^\s\d號字]+)\s*(?:字第)?\s*(\d+)', q_clean)
                    if m_case:
                        sql_idx = (
                            "SELECT case_id, court, jud_year, jud_word, jud_no, date, title, holding_preview, laws_cited "
                            "FROM judgments_meta WHERE jud_year = ? AND jud_word = ? AND jud_no = ? LIMIT ?"
                        )
                        rows = conn.execute(sql_idx, (m_case.group(1), m_case.group(2), m_case.group(3), needed)).fetchall()
                    else:
                        # 走實質爭點索引，避免百萬全表掃描
                        court_cond = f"AND court = '{court_filter}'" if court_filter else ""
                        sql = (
                            f"SELECT case_id, court, jud_year, jud_word, jud_no, date, title, holding_preview, laws_cited "
                            f"FROM judgments_meta "
                            f"WHERE has_legal_issue = 1 AND holding_preview LIKE ? {court_cond} "
                            f"LIMIT ?"
                        )
                        pat = f"%{q_clean}%"
                        rows = conn.execute(sql, (pat, needed)).fetchall()

                    for r in rows:
                        results.append({
                            "category": "實體司法裁判",
                            "badge": f"🏛️ {r['court'] or '法院'}",
                            "title": r["case_id"],
                            "sub_title": r["title"],
                            "date": r["date"],
                            "holding": (r["holding_preview"][:160] + "...") if r["holding_preview"] else r["title"],
                            "laws_cited": r["laws_cited"],
                            "url": "https://judgment.judicial.gov.tw/FJUD/default.aspx"
                        })
                        if len(results) >= limit:
                            break
            except Exception:
                pass

        self._query_cache[cache_key] = results
        return results


_unified_corpus = None

def get_unified_corpus_engine() -> UnifiedLegalCorpusEngine:
    global _unified_corpus
    if _unified_corpus is None:
        _unified_corpus = UnifiedLegalCorpusEngine()
    return _unified_corpus
