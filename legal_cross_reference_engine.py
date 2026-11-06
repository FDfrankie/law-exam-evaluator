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

def parse_chinese_number(s: str) -> int:
    """繁體中文數字轉阿拉伯數字（支援千、百、十、零與大寫）"""
    if not s:
        return 0
    s = str(s).strip().replace('零', '')
    if not s:
        return 0
    cn_map = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
        '壹': 1, '貳': 2, '參': 3, '肆': 4, '伍': 5, '陸': 6, '柒': 7, '捌': 8, '玖': 9
    }
    total = 0
    if '千' in s:
        parts = s.split('千', 1)
        total += (cn_map.get(parts[0], 1) if parts[0] else 1) * 1000
        s = parts[1]
    if '百' in s:
        parts = s.split('百', 1)
        total += (cn_map.get(parts[0], 1) if parts[0] else 1) * 100
        s = parts[1]
    if '十' in s:
        parts = s.split('十', 1)
        total += (cn_map.get(parts[0], 1) if parts[0] else 1) * 10
        s = parts[1]
    if s:
        total += cn_map.get(s, 0)
    return total

COMMON_CORE_LAWS = [
    "民法總則施行法", "民法債編施行法", "民法物權編施行法", "民法親屬編施行法", "民法繼承編施行法",
    "民事訴訟法施行法", "刑事訴訟法施行法", "行政訴訟法施行法",
    "消費者保護法", "涉外民事法律適用法", "家事事件法", "強制執行法", "非訟事件法", "勞動事件法",
    "中華民國刑法", "貪污治罪條例", "毒品危害防制條例", "洗錢防制法", "槍砲彈藥刀械管制條例",
    "國民法官法", "少年事件處理法", "通訊保障及監察法", "道路交通管理處罰條例",
    "行政程序法", "行政罰法", "行政執行法", "訴願法", "國家賠償法", "公務員懲戒法", "公務人員保障法",
    "證券交易法", "保險法", "票據法", "期貨交易法", "企業併購法", "金融消費者保護法", "銀行法", "信託法",
    "智慧財產案件審理法", "專利法", "商標法", "著作權法", "營業秘密法", "個人資料保護法",
    "勞動基準法", "工會法", "勞工保險條例", "性別平等工作法",
    "土地法", "土地稅法", "稅捐稽徵法", "建築法", "都市計畫法", "區域計畫法",
    "中華民國憲法增修條文", "中華民國憲法", "憲法訴訟法", "司法院大法官審理案件法",
    "民事訴訟法", "刑事訴訟法", "行政訴訟法", "公司法", "刑法", "民法", "憲法"
]

_LAW_REGEX_FRAGMENT = "|".join(re.escape(k) for k in COMMON_CORE_LAWS)
_STATUTE_CITATION_PATTERN = re.compile(
    rf'(?:(?:依|按|同法|參照)\s*)?({_LAW_REGEX_FRAGMENT})?\s*'
    r'第\s*([0-9]+|[一二三四五六七八九十百千]+)\s*'
    r'(?:條\s*之\s*([0-9]+|[一二三四五六七八九十百]+)|之\s*([0-9]+|[一二三四五六七八九十百]+)|-\s*([0-9]+))?\s*(?:條)?'
    r'(?:\s*第\s*([0-9]+|[一二三四五六七八九十]+)\s*項)?'
    r'(?:\s*第\s*([0-9]+|[一二三四五六七八九十]+)\s*款)?'
    r'(?:\s*(前段|後段|本文|但書))?'
)

def extract_statute_citations_from_text(text: str) -> List[Dict[str, Any]]:
    """
    自裁判全文或裁判要旨中，精準萃取所有被引用的中華民國法律條文與法規命令。
    支援中文數字（第一百八十四條）、枝條（第172條之1）、項次與款目。
    支援上下文法典名稱繼承（如：依民法第184條及第195條）。
    """
    if not text:
        return []
    citations = []
    seen = set()
    current_law = ""
    for m in _STATUTE_CITATION_PATTERN.finditer(text):
        law, num1, sub1, sub2, sub3, par, item, pos = m.groups()
        if law:
            current_law = law
        if not current_law:
            continue
        sub = sub1 or sub2 or sub3 or ""
        clean_no = str(parse_chinese_number(num1)) if not num1.isdigit() else num1
        if sub:
            clean_sub = str(parse_chinese_number(sub)) if not sub.isdigit() else sub
            clean_no = f"{clean_no}-{clean_sub}"

        par_str = f"第{parse_chinese_number(par) if not par.isdigit() else par}項" if par else ""
        item_str = f"第{parse_chinese_number(item) if not item.isdigit() else item}款" if item else ""
        pos_str = pos or ""
        canonical = f"{current_law}第{clean_no}條{par_str}{item_str}{pos_str}"
        if canonical not in seen:
            seen.add(canonical)
            citations.append({
                "law_name": current_law,
                "article_no": clean_no,
                "paragraph": par or "",
                "subparagraph": item or "",
                "position": pos_str,
                "canonical": canonical,
                "raw_text": m.group(0)
            })
    return citations

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
        cand_chorder = [
            Path(NATIONAL_LAWS_DIR) / "ChOrder.json",
            Path(DATA_DIR) / "national_laws" / "ChOrder.json",
            Path(__file__).resolve().parent / "data" / "national_laws" / "ChOrder.json",
            Path("G:/我的雲端硬碟/LawExamData/national_laws/ChOrder.json")
        ]
        self.chorder_path = next((p for p in cand_chorder if p.exists()), cand_chorder[0])

        cand_chlaw = [
            Path(NATIONAL_LAWS_DIR) / "ChLaw.json",
            Path(DATA_DIR) / "national_laws" / "ChLaw.json",
            Path(__file__).resolve().parent / "data" / "national_laws" / "ChLaw.json",
            Path("G:/我的雲端硬碟/LawExamData/national_laws/ChLaw.json")
        ]
        self.chlaw_path = next((p for p in cand_chlaw if p.exists()), cand_chlaw[0])

        self.index_db_path = Path(JUDICIAL_1M_DIR) / "judicial_1m_index.db"
        if not self.index_db_path.exists():
            cand = Path(DATA_DIR) / "judicial_1m_db" / "judicial_1m_index.db"
            if cand.exists():
                self.index_db_path = cand

        self._orders_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._orders_name_index: Optional[List[str]] = None
        self._precedents_cache: Optional[List[Dict[str, Any]]] = None
        self._statute_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._search_orders_cache: Dict[Tuple[str, str, int], List[Dict[str, Any]]] = {}

    def _ensure_precedents_loaded(self):
        """加載 4,088 筆最高法院/大法官先例，加速條文判解直連"""
        if self._precedents_cache is not None:
            return
        self._precedents_cache = []
        cand_prec = [
            Path(DATA_DIR) / "precedents_catalog.json",
            Path(__file__).resolve().parent / "data" / "precedents_catalog.json",
            Path(DATA_DIR) / "raw_exams" / "precedents_catalog.json",
            Path("G:/我的雲端硬碟/LawExamData/code/data/precedents_catalog.json")
        ]
        p_path = next((p for p in cand_prec if p.exists()), cand_prec[0])
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
        具備全自動記憶體快取與多級極速篩選機制。
        """
        self._ensure_orders_loaded()
        if not query or not query.strip():
            return []

        q_clean = query.strip().lower()
        cache_key = (q_clean, category.strip(), limit)
        if cache_key in self._search_orders_cache:
            return self._search_orders_cache[cache_key]

        results = []

        for name in self._orders_name_index:
            order = self._orders_cache.get(name, {})
            cat = order.get("LawCategory", "")
            if category and category not in cat:
                continue

            # 名稱匹配（秒級）
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

        # 若依名稱匹配未滿，可進一步檢索條文內文（僅限前 500 部或命中即停）
        if len(results) < limit:
            checked_count = 0
            for name in self._orders_name_index:
                if any(r["name"] == name for r in results):
                    continue
                checked_count += 1
                if checked_count > 500:
                    break
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

        self._search_orders_cache[cache_key] = results
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
        court_filter: Optional[str] = "全部法院",
        order_by: str = "authority",
        search_kw: str = "",
        limit: int = 15
    ) -> List[Dict[str, Any]]:
        """
        雙向直連：依據法典與條號（如 民法 第 184 條），於百萬裁判庫與權威先例庫中秒級檢索
        曾引用該條文之憲法法庭裁判、最高法院大法庭裁定、指標判例與各級實務判決。
        支援審級篩選 (court_filter)、即時關鍵字查詢 (search_kw) 與多維度排序 (order_by)。
        """
        clean_law = law_name.strip()
        clean_art = str(article_no).strip().replace("第", "").replace("條", "").strip()
        if not clean_law or not clean_art:
            return []

        search_clean = str(search_kw or "").strip()
        cache_key = f"{clean_law}_{clean_art}_{court_filter}_{order_by}_{search_clean}_{limit}"
        if cache_key in self._statute_cache:
            return self._statute_cache[cache_key]

        results = []
        seen_case_ids = set()

        # 1. 優先從 4,088 筆權威先例快取匹配 (0 秒毫秒級)
        self._ensure_precedents_loaded()
        if self._precedents_cache:
            art_pattern = re.compile(rf'(?:{re.escape(clean_law)}[^\d]*?第?\s*{re.escape(clean_art)}\s*(?:之\d+)?\s*條|第?\s*{re.escape(clean_art)}\s*條)')
            for p in self._precedents_cache:
                p_court = p.get("court", "")
                if court_filter and court_filter not in p_court and court_filter != "全部法院":
                    continue
                laws_cited = str(p.get("laws_cited", ""))
                cid = p.get("case_id") or p.get("precedent_id", "")
                title_s = p.get("title", "") or cid
                holding_s = p.get("holding", "") or title_s

                # 若提供關鍵字，需匹配字號、標題或判旨
                if search_clean and search_clean not in cid and search_clean not in title_s and search_clean not in holding_s:
                    continue

                if clean_law in laws_cited and (f"{clean_art}" in laws_cited or art_pattern.search(laws_cited)):
                    if cid and cid not in seen_case_ids:
                        seen_case_ids.add(cid)
                        # 動態萃取判決使用法條（若原欄位過於簡略）
                        resolved_laws = [laws_cited] if isinstance(laws_cited, str) else list(laws_cited)
                        if len(resolved_laws) <= 1 and holding_s:
                            extracted = extract_statute_citations_from_text(holding_s)
                            if extracted:
                                resolved_laws = list(set([x["canonical"] for x in extracted]))
                        results.append({
                            "case_id": cid,
                            "court": p.get("court", "最高法院"),
                            "year": p.get("year", ""),
                            "word": "",
                            "no": p.get("precedent_id", ""),
                            "date": p.get("date", ""),
                            "title": title_s,
                            "level": p.get("level", "最高法院指標裁判"),
                            "holding": holding_s,
                            "laws_cited": "、".join(resolved_laws) if isinstance(resolved_laws, list) else str(resolved_laws),
                            "official_url": p.get("source_url") or f"https://judgment.judicial.gov.tw/FJUD/default.aspx"
                        })
                        if len(results) >= limit * 2:
                            break

        # 2. 自權威先例與大法庭/憲法裁判庫 (judicial_authority.db: 11,625+ 則) 快速檢索
        auth_db_path = Path(DATA_DIR) / "judicial_authority.db"
        if not auth_db_path.exists():
            cand_auth = Path(__file__).resolve().parent / "data" / "judicial_authority.db"
            if cand_auth.exists():
                auth_db_path = cand_auth

        if len(results) < limit * 2 and auth_db_path.exists():
            try:
                target_pat = f"%{clean_law}%{clean_art}%"
                with sqlite3.connect(str(auth_db_path), timeout=3.0) as conn:
                    conn.row_factory = sqlite3.Row
                    auth_rows = conn.execute(
                        "SELECT id, case_no, court, title, holding, laws_cited, date "
                        "FROM authority_records WHERE laws_cited LIKE ? LIMIT ?",
                        (target_pat, (limit * 2) - len(results))
                    ).fetchall()
                    for r in auth_rows:
                        cid = r["case_no"] or r["id"]
                        if cid and cid not in seen_case_ids:
                            c_court = r["court"] or "最高法院大法庭/憲法裁判"
                            if court_filter and court_filter != "全部法院" and court_filter not in c_court:
                                continue
                            t_title = r["title"] or cid
                            h_holding = r["holding"] or t_title
                            if search_clean and search_clean not in cid and search_clean not in t_title and search_clean not in h_holding:
                                continue
                            seen_case_ids.add(cid)
                            results.append({
                                "case_id": cid,
                                "court": c_court,
                                "year": "",
                                "word": "",
                                "no": r["case_no"] or r["id"],
                                "date": r["date"] or "",
                                "title": t_title,
                                "level": "權威大法庭/憲法裁判",
                                "holding": h_holding,
                                "laws_cited": r["laws_cited"] or f"{clean_law}第{clean_art}條",
                                "official_url": "https://judgment.judicial.gov.tw/FJUD/default.aspx"
                            })
                            if len(results) >= limit * 2:
                                break

                    if len(results) < limit * 2:
                        prec_rows = conn.execute(
                            "SELECT precedent_id, case_no, year, court, title, holding, laws_cited, date "
                            "FROM precedents WHERE laws_cited LIKE ? LIMIT ?",
                            (target_pat, (limit * 2) - len(results))
                        ).fetchall()
                        for r in prec_rows:
                            cid = r["case_no"] or r["precedent_id"]
                            if cid and cid not in seen_case_ids:
                                c_court = r["court"] or "最高法院"
                                if court_filter and court_filter != "全部法院" and court_filter not in c_court:
                                    continue
                                t_title = r["title"] or cid
                                h_holding = r["holding"] or t_title
                                if search_clean and search_clean not in cid and search_clean not in t_title and search_clean not in h_holding:
                                    continue
                                seen_case_ids.add(cid)
                                results.append({
                                    "case_id": cid,
                                    "court": c_court,
                                    "year": r["year"] or "",
                                    "word": "",
                                    "no": r["case_no"] or r["precedent_id"],
                                    "date": r["date"] or "",
                                    "title": t_title,
                                    "level": "最高法院判例/要旨",
                                    "holding": h_holding,
                                    "laws_cited": r["laws_cited"] or f"{clean_law}第{clean_art}條",
                                    "official_url": "https://judgment.judicial.gov.tw/FJUD/default.aspx"
                                })
                                if len(results) >= limit * 2:
                                    break
            except Exception:
                pass

        # 3. 實體裁判大庫檢索
        if len(results) < limit * 2 and self.index_db_path.exists():
            target_pattern = f"%{clean_law}%{clean_art}%"
            try:
                with sqlite3.connect(str(self.index_db_path), timeout=1.0) as conn:
                    conn.row_factory = sqlite3.Row
                    if court_filter and court_filter != "全部法院":
                        query_sql = (
                            "SELECT case_id, court, jud_year, jud_word, jud_no, date, title, "
                            "       holding_preview, laws_cited, substantive_prior "
                            "FROM judgments_meta "
                            "WHERE court LIKE ? AND has_legal_issue = 1 AND laws_cited LIKE ? "
                            "LIMIT ?"
                        )
                        rows = conn.execute(query_sql, (f"%{court_filter}%", target_pattern, (limit * 2) - len(results))).fetchall()
                    else:
                        query_sql = (
                            "SELECT case_id, court, jud_year, jud_word, jud_no, date, title, "
                            "       holding_preview, laws_cited, substantive_prior "
                            "FROM judgments_meta "
                            "WHERE has_legal_issue = 1 AND laws_cited LIKE ? "
                            "LIMIT ?"
                        )
                        rows = conn.execute(query_sql, (target_pattern, (limit * 2) - len(results))).fetchall()

                    for r in rows:
                        cid = r["case_id"]
                        if cid not in seen_case_ids:
                            t_title = r["title"] or cid
                            h_holding = r["holding_preview"] or t_title
                            if search_clean and search_clean not in cid and search_clean not in t_title and search_clean not in h_holding:
                                continue
                            seen_case_ids.add(cid)
                            
                            # 萃取法條
                            raw_lc = r["laws_cited"] or ""
                            if not raw_lc and h_holding:
                                extracted = extract_statute_citations_from_text(h_holding)
                                raw_lc = "、".join([x["canonical"] for x in extracted])
                            
                            results.append({
                                "case_id": cid,
                                "court": r["court"],
                                "year": r["jud_year"],
                                "word": r["jud_word"],
                                "no": r["jud_no"],
                                "date": r["date"],
                                "title": t_title,
                                "level": "權威司法裁判",
                                "holding": h_holding,
                                "laws_cited": raw_lc or f"{clean_law}第{clean_art}條",
                                "official_url": "https://judgment.judicial.gov.tw/FJUD/default.aspx"
                            })
            except Exception:
                pass

        # 4. 排序邏輯 (Sorting)
        if order_by == "date_desc":
            results.sort(key=lambda x: str(x.get("date", "")), reverse=True)
        elif order_by == "date_asc":
            results.sort(key=lambda x: str(x.get("date", "")))
        else:
            # 預設：審級重要性優先 (憲法法庭 > 大法庭 > 判例 > 最高法院 > 高等法院 > 地方法院)
            def _level_score(item):
                c = item.get("court", "") + " " + item.get("level", "")
                if "憲法" in c or "大法官" in c or "釋字" in c: return 0
                if "大法庭" in c: return 1
                if "判例" in c: return 2
                if "最高" in c: return 3
                if "高等" in c or "高分院" in c: return 4
                return 5
            results.sort(key=_level_score)

        final_results = results[:limit]
        self._statute_cache[cache_key] = final_results
        return final_results


_cross_ref_engine = None

def get_cross_reference_engine() -> LegalCrossReferenceEngine:
    global _cross_ref_engine
    if _cross_ref_engine is None:
        _cross_ref_engine = LegalCrossReferenceEngine()
    return _cross_ref_engine
