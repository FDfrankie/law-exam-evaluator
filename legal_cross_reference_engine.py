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
import logging
import re
import sqlite3
import tempfile
import urllib.parse
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from config import DATA_DIR, JUDICIAL_1M_DIR, NATIONAL_LAWS_DIR

logger = logging.getLogger(__name__)


class ClosingConnection(sqlite3.Connection):
    """Ensure SQLite connections close upon exiting a `with` block."""

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def _open_ro_sqlite(db_path: Path, timeout: float = 10.0) -> ClosingConnection:
    """Open a read-only SQLite connection with busy timeout and guaranteed cleanup."""
    uri = f"{Path(db_path).resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=timeout, factory=ClosingConnection)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 60000;")
    except Exception:
        conn.close()
        raise
    return conn

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

def format_statute_citations_display(laws_input) -> List[str]:
    """
    將 OpenData 裁判引註條文陣列（如 ['山坡地保育利用條例', '第', '37', '條', '民法', '第', '71、113...']）
    或其字串形式，精準轉換為使用者易讀的法條徽章列表（如：['山坡地保育利用條例 第 37 條', '民法 第 71、113、179 條']）。
    徹底杜絕 Python 原始 list repr、括號引號與零散數字。
    """
    import ast
    if not laws_input:
        return []
    
    tokens = []
    if isinstance(laws_input, list):
        tokens = [str(x).strip() for x in laws_input if str(x).strip()]
    elif isinstance(laws_input, str):
        raw_s = laws_input.strip()
        if raw_s.startswith("[") and raw_s.endswith("]"):
            try:
                parsed = ast.literal_eval(raw_s)
                if isinstance(parsed, list):
                    tokens = [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        if not tokens:
            parts = re.split(r'[,、;\n\r]+', raw_s)
            return [p.strip() for p in parts if p.strip()]

    if not tokens:
        return []

    # 若原本即為標準完整法條引註（如 ['民法第184條', '刑法第271條']）
    if all('第' in t and any(sfx in t for sfx in ['法', '條例', '規則', '辦法', '細則']) for t in tokens if len(t) > 3):
        return tokens

    # 分組重組 OpenData 條文碎片：法規名 + '第' + 條號 + '條(...)'
    law_suffixes = ('法', '條例', '辦法', '規則', '細則', '準則', '要點', '規程', '標準', '憲法增修條文', '憲法')
    grouped = []
    current_law = ""
    current_articles = []

    for tok in tokens:
        is_law = (
            any(tok.endswith(sfx) for sfx in law_suffixes) or 
            tok in ["民法", "刑法", "憲法", "貪污治罪條例", "公司法", "保險法", "票據法", "證券交易法", "法院組織法"]
        ) and not re.search(r'^\d', tok) and '第' not in tok
        
        if is_law:
            if current_law:
                art_str = "、".join(current_articles) if current_articles else ""
                disp = f"{current_law} 第 {art_str} 條" if art_str else current_law
                grouped.append(disp)
            current_law = tok
            current_articles = []
        elif tok in ['第', '條'] or tok.startswith('條（') or tok.startswith('條('):
            continue
        elif current_law:
            clean_tok = re.sub(r'條.*$', '', tok).replace('第', '').strip()
            nums = [n.strip() for n in re.split(r'[、,]+', clean_tok) if n.strip()]
            for n in nums:
                if n and n not in current_articles:
                    current_articles.append(n)
        else:
            if tok and not tok.isdigit():
                grouped.append(tok)

    if current_law:
        art_str = "、".join(current_articles) if current_articles else ""
        disp = f"{current_law} 第 {art_str} 條" if art_str else current_law
        grouped.append(disp)

    return grouped

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

        try:
            from build_million_judgments_db import get_million_db_engine
            _mdb = get_million_db_engine()
            self.index_db_path = _mdb.index_db_path
        except Exception:
            self.index_db_path = Path(JUDICIAL_1M_DIR) / "judicial_1m_index.db"
            for cand in [
                Path(DATA_DIR) / "judicial_1m_db" / "judicial_1m_index.db",
                Path(DATA_DIR) / "judicial_exam_core.db",
                Path(__file__).resolve().parent / "data" / "judicial_exam_core.db",
            ]:
                if cand.exists():
                    self.index_db_path = cand
                    break

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

    @staticmethod
    def _matches_statute_citation(laws_cited: Any, clean_law: str, clean_art: str) -> bool:
        """Strictly match `(clean_law, clean_art)` without substring false positives (e.g. 1 vs 10/184/1-1/1之1/1條之1/第1項)."""
        text = "、".join(str(x) for x in laws_cited) if isinstance(laws_cited, (list, tuple)) else str(laws_cited or "")
        if not text or clean_law not in text:
            return False

        art_norm = clean_art.replace("之", "-")
        art_variants = [re.escape(clean_art)]
        if "-" in art_norm:
            main_no, sub_no = art_norm.split("-", 1)
            for v in (
                f"{re.escape(main_no)}-{re.escape(sub_no)}",
                f"{re.escape(main_no)}之{re.escape(sub_no)}",
                rf"{re.escape(main_no)}\s*條\s*之\s*{re.escape(sub_no)}",
            ):
                if v not in art_variants:
                    art_variants.append(v)
        art_alt = "|".join(art_variants)

        # Reject trailing sub-articles (之1, 條之1, -1), extra digits, or paragraph/subparagraph markers (項/款/目)
        strict_art_re = re.compile(
            rf"(?<![\d\-之])(?:{art_alt})(?!\s*條\s*之\s*[\d一二三四五六七八九十]|\s*之\s*[\d一二三四五六七八九十]|[\d\-]|\s*[項款目])"
        )
        if not strict_art_re.search(text):
            return False

        law_name_re = re.compile(
            r"([\u4e00-\u9fff]+?(?:增修條文|施行法|訴訟法|條例|通則|規則|辦法|標準|準則|規程|憲法|法))"
        )

        # Track most recent law across comma-separated segments and immediately before each article match
        last_law = ""
        for seg in re.split(r"[,，、;；\n]+", text):
            seg_s = seg.strip()
            if not seg_s:
                continue
            seg_laws = law_name_re.findall(seg_s)
            seg_has_target_law = clean_law in seg_s
            if seg_has_target_law or last_law == clean_law:
                for m_hit in strict_art_re.finditer(seg_s):
                    prefix = seg_s[:m_hit.start()].rstrip()
                    if prefix.endswith(("之", "-")):
                        continue
                    law_ctx = re.sub(r"(?:\s*第\s*|_)$", "", prefix).strip()
                    if not law_ctx:
                        effective_law = last_law
                    elif law_ctx == clean_law or (
                        law_ctx.endswith(clean_law)
                        and (
                            len(law_ctx) == len(clean_law)
                            or not ("\u4e00" <= law_ctx[-len(clean_law) - 1] <= "\u9fff")
                        )
                    ):
                        effective_law = clean_law
                    else:
                        ctx_laws = law_name_re.findall(law_ctx)
                        effective_law = ctx_laws[-1] if ctx_laws else law_ctx

                    if effective_law == clean_law or (
                        clean_law in ("刑法", "中華民國刑法") and effective_law in ("刑法", "中華民國刑法")
                    ) or (
                        clean_law in ("憲法", "中華民國憲法") and effective_law in ("憲法", "中華民國憲法")
                    ):
                        return True
            if seg_laws:
                last_law = seg_laws[-1]
            else:
                m_tail = re.match(r"^\s*([^\d_\s第]+)", seg_s)
                if m_tail and not seg_s.startswith("第"):
                    last_law = m_tail.group(1)
        return False

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
            cached_val = self._statute_cache.pop(cache_key)
            self._statute_cache[cache_key] = cached_val
            return list(cached_val)

        results = []
        seen_case_ids = set()

        # 1. 優先從 4,088 筆權威先例快取匹配 (0 秒毫秒級)
        self._ensure_precedents_loaded()
        if self._precedents_cache:
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

                if self._matches_statute_citation(laws_cited, clean_law, clean_art):
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

        # 2. 自權威先例庫 (judicial_authority.db) 與國考精華子庫 (judicial_exam_core.db) 快速檢索
        raw_db_candidates = [
            Path(DATA_DIR) / "judicial_authority.db",
            Path(__file__).resolve().parent / "data" / "judicial_authority.db",
            Path(DATA_DIR) / "judicial_exam_core.db",
            Path(__file__).resolve().parent / "data" / "judicial_exam_core.db",
            Path(tempfile.gettempdir()) / "judicial_exam_core.db",
        ]
        stage2_dbs: List[Path] = []
        seen_db_paths = set()
        for db_cand in raw_db_candidates:
            if db_cand.exists():
                resolved_str = str(db_cand.resolve())
                if resolved_str not in seen_db_paths:
                    seen_db_paths.add(resolved_str)
                    stage2_dbs.append(db_cand)

        if len(results) < limit * 2 and stage2_dbs:
            art_zhi = clean_art.replace("-", "之") if "-" in clean_art else clean_art.replace("之", "-")
            sql_like_pats = [
                f"%第{clean_art}條%",
                f"%第 {clean_art} 條%",
                f"%_{clean_art}%",
            ]
            if art_zhi != clean_art:
                sql_like_pats.extend([f"%第{art_zhi}條%", f"%第 {art_zhi} 條%"])
            sql_art_clause = " OR ".join("laws_cited LIKE ?" for _ in sql_like_pats)
            sql_params_prefix = [f"%{clean_law}%", *sql_like_pats]

            for db_cand in stage2_dbs:
                if len(results) >= limit * 2:
                    break
                try:
                    with _open_ro_sqlite(db_cand, timeout=10.0) as conn:
                        existing_tables = {
                            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                        }
                        fetch_cap = max((limit * 2 - len(results)) * 4, 40)

                        if "authority_records" in existing_tables and len(results) < limit * 2:
                            auth_rows = conn.execute(
                                f"SELECT id, case_no, court, title, holding, laws_cited, date "
                                f"FROM authority_records WHERE laws_cited LIKE ? AND ({sql_art_clause}) LIMIT ?",
                                (*sql_params_prefix, fetch_cap)
                            ).fetchall()
                            for r in auth_rows:
                                if not self._matches_statute_citation(r["laws_cited"], clean_law, clean_art):
                                    continue
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

                        if "precedents" in existing_tables and len(results) < limit * 2:
                            prec_rows = conn.execute(
                                f"SELECT precedent_id, case_no, year, court, title, holding, laws_cited, date "
                                f"FROM precedents WHERE laws_cited LIKE ? AND ({sql_art_clause}) LIMIT ?",
                                (*sql_params_prefix, fetch_cap)
                            ).fetchall()
                            for r in prec_rows:
                                if not self._matches_statute_citation(r["laws_cited"], clean_law, clean_art):
                                    continue
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

                        core_meta_tbl = next((t for t in ("judgments_meta", "exam_judgments_meta") if t in existing_tables), "")
                        if core_meta_tbl and len(results) < limit * 2:
                            core_rows = conn.execute(
                                f"SELECT case_id, jid, court, jud_year, jud_word, jud_no, date, title, level, holding_preview, laws_cited "
                                f"FROM {core_meta_tbl} WHERE laws_cited LIKE ? AND ({sql_art_clause}) LIMIT ?",
                                (*sql_params_prefix, fetch_cap)
                            ).fetchall()
                            for r in core_rows:
                                if not self._matches_statute_citation(r["laws_cited"], clean_law, clean_art):
                                    continue
                                cid = r["case_id"]
                                if cid and cid not in seen_case_ids:
                                    c_court = r["court"] or ""
                                    if court_filter and court_filter != "全部法院" and court_filter not in c_court:
                                        continue
                                    t_title = r["title"] or cid
                                    h_holding = r["holding_preview"] or t_title
                                    if search_clean and search_clean not in cid and search_clean not in t_title and search_clean not in h_holding:
                                        continue
                                    seen_case_ids.add(cid)
                                    jid_val = r["jid"] or ""
                                    if jid_val and "," in str(jid_val) and len(str(jid_val).split(",")) >= 4:
                                        u_url = f"https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id={str(jid_val).strip()}"
                                    else:
                                        clean_cid_url = re.sub(r"\(.*?\)|（.*?）", "", cid).strip()
                                        u_url = f"https://judgment.judicial.gov.tw/FJUD/qryresultlst.aspx?q={urllib.parse.quote(clean_cid_url)}"
                                    results.append({
                                        "case_id": cid,
                                        "court": c_court,
                                        "year": r["jud_year"] or "",
                                        "word": r["jud_word"] or "",
                                        "no": r["jud_no"] or "",
                                        "date": r["date"] or "",
                                        "title": t_title,
                                        "level": r["level"] or "國考核心裁判",
                                        "holding": h_holding,
                                        "laws_cited": r["laws_cited"] or f"{clean_law}第{clean_art}條",
                                        "official_url": u_url,
                                    })
                                    if len(results) >= limit * 2:
                                        break
                except Exception as exc:
                    logger.warning("Stage 2 cross-reference DB query failed (%s): %s", db_cand, exc)

        # 3. 實體裁判大庫檢索（統一透過 MillionJudgmentsSQLiteEngine FTS5 + 索引，支援 797 萬母庫與精華子庫）
        if len(results) < limit * 2:
            try:
                from build_million_judgments_db import get_million_db_engine
                db_engine = get_million_db_engine()
                if db_engine.is_available():
                    cited_target = f"{clean_law}第{clean_art}條"
                    needed = (limit * 2) - len(results)
                    hits = db_engine.search_fts_and_meta(
                        query=search_clean,
                        cited_laws=cited_target,
                        court_system=court_filter or "全部法院 (全體司法體系)",
                        filter_no_legal_issue=True,
                        top_k=needed
                    )
                    if not hits and not search_clean:
                        hits = db_engine.search_fts_and_meta(
                            query=f"{clean_law} {clean_art}",
                            court_system=court_filter or "全部法院 (全體司法體系)",
                            filter_no_legal_issue=True,
                            top_k=needed
                        )
                    for r in hits:
                        cid = r.get("case_id", "")
                        if not cid or cid in seen_case_ids:
                            continue
                        t_title = r.get("title") or cid
                        h_holding = r.get("holding") or t_title
                        if search_clean and search_clean not in cid and search_clean not in t_title and search_clean not in h_holding:
                            continue
                        lc_val = r.get("laws_cited", [])
                        raw_lc = "、".join(lc_val) if isinstance(lc_val, list) else str(lc_val or "")
                        if raw_lc and not self._matches_statute_citation(raw_lc, clean_law, clean_art):
                            continue
                        if not raw_lc and h_holding:
                            extracted = extract_statute_citations_from_text(h_holding)
                            raw_lc = "、".join([x["canonical"] for x in extracted])
                            if raw_lc and not self._matches_statute_citation(raw_lc, clean_law, clean_art):
                                continue
                        seen_case_ids.add(cid)
                        results.append({
                            "case_id": cid,
                            "court": r.get("court", ""),
                            "year": r.get("jud_year", ""),
                            "word": r.get("jud_word", ""),
                            "no": r.get("jud_no", ""),
                            "date": r.get("date", ""),
                            "title": t_title,
                            "level": r.get("level") or "權威司法裁判",
                            "holding": h_holding,
                            "laws_cited": raw_lc or cited_target,
                            "official_url": r.get("official_url") or db_engine.get_official_url(cid, r.get("jid", ""))
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
        if cache_key in self._statute_cache:
            self._statute_cache.pop(cache_key)
        elif len(self._statute_cache) >= 256:
            self._statute_cache.pop(next(iter(self._statute_cache)))
        self._statute_cache[cache_key] = final_results
        return list(final_results)


_cross_ref_engine = None

def get_cross_reference_engine() -> LegalCrossReferenceEngine:
    global _cross_ref_engine
    if _cross_ref_engine is None:
        _cross_ref_engine = LegalCrossReferenceEngine()
    return _cross_ref_engine
