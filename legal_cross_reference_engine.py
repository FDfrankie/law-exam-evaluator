# -*- coding: utf-8 -*-
"""
legal_cross_reference_engine.py
===============================
法條、行政命令與部會函釋交叉導航網絡引擎（對標法源法律網、七法 Laws.club、Lawsnote）。
功能：
1. 全國行政法規命令庫 (ChOrder.json: 10,452 部行政命令、要點、標準、辦法與注意事項) 極速檢索
2. 裁判引用法規解析器：將裁判引用之法條拆解並直連現行法條全文、立法意旨與主管部會
3. 雙向法條裁判直連網絡 (Statute ➔ Landmark Judgments)：智慧六法任一法條秒級反查最高法院標竿裁判
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from config import DATA_DIR, JUDICIAL_1M_DIR, NATIONAL_LAWS_DIR


class LegalCrossReferenceEngine:
    """
    法條、行政命令與裁判交叉關聯網絡核心引擎
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(LegalCrossReferenceEngine, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.chorder_path = Path("G:/我的雲端硬碟/LawExamData/national_laws/ChOrder.json")
        if not self.chorder_path.exists():
            cand = Path(DATA_DIR) / "national_laws" / "ChOrder.json"
            if cand.exists():
                self.chorder_path = cand

        self.chlaw_path = Path("G:/我的雲端硬碟/LawExamData/national_laws/ChLaw.json")
        if not self.chlaw_path.exists():
            cand = Path(DATA_DIR) / "national_laws" / "ChLaw.json"
            if cand.exists():
                self.chlaw_path = cand

        self.index_db_path = Path(JUDICIAL_1M_DIR) / "judicial_1m_index.db"
        if not self.index_db_path.exists():
            cand = Path(DATA_DIR) / "judicial_1m_db" / "judicial_1m_index.db"
            if cand.exists():
                self.index_db_path = cand

        self._orders_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._orders_name_index: Optional[List[str]] = None
        self._precedents_cache: Optional[List[Dict[str, Any]]] = None
        self._statute_cache: Dict[str, List[Dict[str, Any]]] = {}

    def _ensure_precedents_loaded(self):
        """加載 4,088 筆最高法院/大法官先例，加速條文判解直連"""
        if self._precedents_cache is not None:
            return
        self._precedents_cache = []
        p_path = Path(DATA_DIR) / "precedents_catalog.json"
        if not p_path.exists():
            cand = Path("G:/我的雲端硬碟/LawExamData/code/data/precedents_catalog.json")
            if cand.exists():
                p_path = cand
        if p_path.exists():
            try:
                with open(p_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._precedents_cache = data
                elif isinstance(data, dict):
                    self._precedents_cache = list(data.values())
            except Exception:
                self._precedents_cache = []

    def _ensure_orders_loaded(self):
        """延遲加載行政法規命令庫，建立名稱索引字典"""
        if self._orders_cache is not None:
            return
        self._orders_cache = {}
        self._orders_name_index = []

        if not self.chorder_path.exists():
            return

        try:
            with open(self.chorder_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            laws = data.get("Laws", []) if isinstance(data, dict) else []
            for item in laws:
                name = item.get("LawName", "").strip()
                if name:
                    self._orders_cache[name] = item
                    self._orders_name_index.append(name)
        except Exception:
            pass

    def search_administrative_orders(
        self,
        query: str,
        category: str = "",
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """
        全文與法規名稱檢索 10,452 部行政命令、要點、標準、辦法與注意事項
        """
        self._ensure_orders_loaded()
        if not query or not query.strip():
            return []

        q_clean = query.strip().lower()
        results = []

        for name in self._orders_name_index:
            order = self._orders_cache.get(name, {})
            cat = order.get("LawCategory", "")
            if category and category not in cat:
                continue

            # 名稱匹配
            if q_clean in name.lower():
                results.append({
                    "name": name,
                    "category": cat,
                    "date": order.get("LawModifiedDate", ""),
                    "level": order.get("LawLevel", "法規命令"),
                    "articles_count": len(order.get("LawArticles", [])),
                    "url": order.get("LawURL", ""),
                    "match_type": "EXACT_NAME" if q_clean == name.lower() else "PARTIAL_NAME"
                })
                if len(results) >= limit:
                    break

        # 若依名稱匹配未滿，可進一步檢索條文內文
        if len(results) < limit:
            for name in self._orders_name_index:
                if any(r["name"] == name for r in results):
                    continue
                order = self._orders_cache.get(name, {})
                for art in order.get("LawArticles", []):
                    c = art.get("ArticleContent", "")
                    if q_clean in c.lower():
                        results.append({
                            "name": name,
                            "category": order.get("LawCategory", ""),
                            "date": order.get("LawModifiedDate", ""),
                            "level": order.get("LawLevel", "法規命令"),
                            "articles_count": len(order.get("LawArticles", [])),
                            "url": order.get("LawURL", ""),
                            "snippet": c[:120].strip(),
                            "match_type": "CONTENT"
                        })
                        break
                if len(results) >= limit:
                    break

        return results

    def get_order_details(self, order_name: str) -> Optional[Dict[str, Any]]:
        """取得單一行政命令/要點之完整條文與編章結構"""
        self._ensure_orders_loaded()
        clean_name = order_name.strip()
        return self._orders_cache.get(clean_name)

    def resolve_laws_cited(self, laws_cited_str: str) -> Dict[str, Any]:
        """
        解析裁判書中 laws_cited 欄位字串，自動分類為：
        1. 核心實體與程序法律 (Statutes): 如民法第184條、公司法第19條、刑事訴訟法第159條
        2. 行政法規命令與作業要點 (Orders): 如道路交通安全規則、勞工請假規則
        3. 條文詳細內容與立法理由對接
        """
        if not laws_cited_str or not laws_cited_str.strip():
            return {"statutes": [], "orders": [], "unresolved": []}

        self._ensure_orders_loaded()

        raw_items = re.split(r'[,;\n\r\t]+', laws_cited_str)
        statutes = []
        orders = []
        unresolved = []

        seen_keys = set()

        for item in raw_items:
            clean_item = item.strip()
            if not clean_item or clean_item in seen_keys:
                continue
            seen_keys.add(clean_item)

            # 正則萃取法規名與條號
            m = re.search(r'([^\s第條款項]+法(?:規)?|民法|刑法|民事訴訟法|刑事訴訟法|行政訴訟法|公司法|票據法|海商法|保險法|憲法)\s*第\s*([0-9\-之]+)\s*條', clean_item)
            if m:
                law_name = m.group(1).strip()
                art_no = m.group(2).strip()

                # 嘗試對接 six_codes_engine 取得條文內容
                content = ""
                reason = ""
                try:
                    from six_codes_engine import get_six_codes_engine
                    sc_engine = get_six_codes_engine()
                    art_doc = sc_engine.get_article(law_name, art_no)
                    if art_doc:
                        content = art_doc.get("content", "")
                        reason = art_doc.get("legislative_reason", "")
                except Exception:
                    pass

                statutes.append({
                    "raw": clean_item,
                    "law_name": law_name,
                    "article_no": art_no,
                    "content": content,
                    "legislative_reason": reason,
                    "type": "STATUTE"
                })
                continue

            # 檢驗是否屬於行政命令/要點/規則
            m_order = re.search(r'([^\s第條款項]+(?:規則|辦法|標準|要點|細則|規程|注意事項|準則))\s*(?:第\s*([0-9\-之]+)\s*條)?', clean_item)
            if m_order:
                order_name = m_order.group(1).strip()
                art_no = m_order.group(2).strip() if m_order.group(2) else ""

                order_doc = self.get_order_details(order_name)
                art_content = ""
                if order_doc and art_no:
                    for a in order_doc.get("LawArticles", []):
                        if a.get("ArticleNo", "").strip() == f"第 {art_no} 條" or a.get("ArticleNo", "").strip() == art_no:
                            art_content = a.get("ArticleContent", "")
                            break

                orders.append({
                    "raw": clean_item,
                    "order_name": order_name,
                    "article_no": art_no,
                    "category": order_doc.get("LawCategory", "主管部會法規命令") if order_doc else "法規命令",
                    "content": art_content,
                    "type": "ORDER"
                })
                continue

            unresolved.append(clean_item)

        return {
            "statutes": statutes,
            "orders": orders,
            "unresolved": unresolved,
            "total_resolved": len(statutes) + len(orders)
        }

    def get_landmark_judgments_for_statute(
        self,
        law_name: str,
        article_no: str,
        court_filter: str = "最高法院",
        limit: int = 8
    ) -> List[Dict[str, Any]]:
        """
        雙向直連：依據法典與條號（如 民法 第 184 條），於百萬裁判庫中秒級檢索曾引用該條文之最高法院權威判決
        優先調閱權威先例庫 (Precedents)，兼顧極速響應與司律頂級權威性。
        """
        clean_law = law_name.strip()
        clean_art = str(article_no).strip().replace("第", "").replace("條", "").strip()
        if not clean_law or not clean_art:
            return []

        cache_key = f"{clean_law}_{clean_art}_{court_filter}_{limit}"
        if cache_key in self._statute_cache:
            return self._statute_cache[cache_key]

        results = []
        seen_case_ids = set()

        # 1. 優先從 4,088 筆權威先例庫匹配 (0 秒毫秒級)
        self._ensure_precedents_loaded()
        if self._precedents_cache:
            # 構造嚴格條號匹配樣式：例如 "184" 或 "184之1"
            art_pattern = re.compile(rf'(?:{re.escape(clean_law)}[^\d]*?第?\s*{re.escape(clean_art)}\s*(?:之\d+)?\s*條|第?\s*{re.escape(clean_art)}\s*條)')
            for p in self._precedents_cache:
                p_court = p.get("court", "")
                if court_filter and court_filter not in p_court:
                    continue
                laws_cited = str(p.get("laws_cited", ""))
                if clean_law in laws_cited and (f"{clean_art}" in laws_cited or art_pattern.search(laws_cited)):
                    cid = p.get("case_id") or p.get("precedent_id", "")
                    if cid and cid not in seen_case_ids:
                        seen_case_ids.add(cid)
                        results.append({
                            "case_id": cid,
                            "court": p.get("court", court_filter),
                            "year": "",
                            "word": "",
                            "no": p.get("precedent_id", ""),
                            "date": p.get("date", ""),
                            "title": p.get("title") or cid,
                            "level": p.get("level", "最高法院指標裁判"),
                            "holding": p.get("holding", "") or p.get("title", ""),
                            "laws_cited": laws_cited,
                            "official_url": p.get("source_url") or "https://judgment.judicial.gov.tw/FJUD/default.aspx"
                        })
                        if len(results) >= limit:
                            break

        # 2. 若先例庫未滿額且大庫可用，查詢實體裁判庫
        if len(results) < limit and self.index_db_path.exists():
            target_pattern = f"%{clean_law}%{clean_art}%"
            try:
                with sqlite3.connect(str(self.index_db_path), timeout=1.5) as conn:
                    conn.row_factory = sqlite3.Row
                    query_sql = (
                        "SELECT case_id, court, jud_year, jud_word, jud_no, date, title, "
                        "       holding_preview, laws_cited, substantive_prior "
                        "FROM judgments_meta "
                        "WHERE court = ? AND laws_cited LIKE ? "
                        "ORDER BY jud_year DESC LIMIT ?"
                    )
                    rows = conn.execute(query_sql, (court_filter, target_pattern, limit - len(results))).fetchall()
                    for r in rows:
                        cid = r["case_id"]
                        if cid not in seen_case_ids:
                            seen_case_ids.add(cid)
                            results.append({
                                "case_id": cid,
                                "court": r["court"],
                                "year": r["jud_year"],
                                "word": r["jud_word"],
                                "no": r["jud_no"],
                                "date": r["date"],
                                "title": r["title"],
                                "level": "最高法院裁判",
                                "holding": r["holding_preview"] or r["title"],
                                "laws_cited": r["laws_cited"],
                                "official_url": "https://judgment.judicial.gov.tw/FJUD/default.aspx"
                            })
            except Exception:
                pass

        self._statute_cache[cache_key] = results
        return results


_cross_ref_engine = None

def get_cross_reference_engine() -> LegalCrossReferenceEngine:
    global _cross_ref_engine
    if _cross_ref_engine is None:
        _cross_ref_engine = LegalCrossReferenceEngine()
    return _cross_ref_engine
