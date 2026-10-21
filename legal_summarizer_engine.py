"""
權威法學智慧引擎模組：
1. 專業布林邏輯搜尋語法引擎 (Boolean Precision Engine: ＆, ＋, －, ( ))
2. 一鍵 AI 裁判與長篇函釋核心要旨自動精鍊 (AI Legal Summarizer)
"""
import os
import sys
import json
import re
from typing import Dict, Any, List, Optional, Tuple

try:
    from google import genai
    from google.genai import types as genai_types
    USE_MODERN_GENAI = True
except ImportError:
    try:
        import google.generativeai as legacy_genai
    except ImportError:
        legacy_genai = None
    USE_MODERN_GENAI = False

from config import get_gemini_api_key, DEFAULT_GEMINI_MODEL, get_gemini_models_to_try
from legal_query_engine import (
    get_precedents_catalog,
    get_precedent_by_id,
    generate_judicial_search_urls,
    get_precedent_history_chain
)
from legal_judgment_analyzer import (
    evaluate_judgment_substance,
    extract_instance_history,
    format_instance_evolution_markdown
)

# ==============================================================================
# 模組 1：專業布林邏輯搜尋語法引擎 (Boolean Precision Engine)
# ==============================================================================

class BooleanQueryParser:
    """
    專業布林邏輯解析器：
    - ＆ 或 &：AND（且）
    - ＋ 或 +：OR（或）
    - － 或 -：NOT（不含、排除）
    - （ ）或 ( )：括號優先運算
    - 支援引號 "..." 精確詞組匹配與空白隱式 AND
    """
    BOOLEAN_CHARS = set("&+-( )＆＋－（）")

    @classmethod
    def is_boolean_query(cls, query: str) -> bool:
        if not query:
            return False
        s = query.strip()
        if any(c in s for c in ['＆', '&', '＋', '+', '－']):
            return True
        if re.search(r'(?:^|\s)[-－][^\s\d]', s):
            return True
        if ('(' in s and ')' in s) or ('（' in s and '）' in s):
            return True
        if re.search(r'\b(AND|OR|NOT)\b', s, re.IGNORECASE):
            return True
        return False

    def __init__(self, query: str):
        self.raw_query = query
        self.tokens = self._tokenize(query)
        self.pos = 0

    def _tokenize(self, s: str) -> List[Tuple[str, str]]:
        s = s.replace('＆', '&').replace('＋', '+').replace('－', '-')
        s = s.replace('（', '(').replace('）', ')')
        s = re.sub(r'\bAND\b', '&', s, flags=re.IGNORECASE)
        s = re.sub(r'\bOR\b', '+', s, flags=re.IGNORECASE)
        s = re.sub(r'\bNOT\b', '-', s, flags=re.IGNORECASE)

        pattern = r'(\s+|&|\+|-|\(|\)|"[^"]*"|\'[^\']*\')'
        parts = re.split(pattern, s)
        tokens = []
        for p in parts:
            if not p:
                continue
            p_strip = p.strip()
            if not p_strip:
                continue
            if p_strip in ('&', '+', '-', '(', ')'):
                tokens.append((p_strip, p_strip))
            else:
                term = p_strip
                if (term.startswith('"') and term.endswith('"')) or (term.startswith("'") and term.endswith("'")):
                    term = term[1:-1].strip()
                if term:
                    tokens.append(('TERM', term))
        return tokens

    def peek(self) -> Tuple[str, str]:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return ('EOF', '')

    def get(self) -> Tuple[str, str]:
        t = self.peek()
        self.pos += 1
        return t

    def parse(self):
        if not self.tokens:
            return None
        return self._parse_or()

    def _parse_or(self):
        node = self._parse_and()
        while self.peek()[0] == '+':
            self.get()
            right = self._parse_and()
            node = ('OR', node, right)
        return node

    def _parse_and(self):
        node = self._parse_not()
        while True:
            nxt, val = self.peek()
            if nxt == '&':
                self.get()
                right = self._parse_not()
                node = ('AND', node, right)
            elif nxt in ('TERM', '(', '-'):
                right = self._parse_not()
                node = ('AND', node, right)
            else:
                break
        return node

    def _parse_not(self):
        if self.peek()[0] == '-':
            self.get()
            operand = self._parse_primary()
            return ('NOT', operand)
        node = self._parse_primary()
        while self.peek()[0] == '-':
            self.get()
            right = self._parse_primary()
            node = ('AND', node, ('NOT', right))
        return node

    def _parse_primary(self):
        nxt, val = self.peek()
        if nxt == '(':
            self.get()
            node = self._parse_or()
            if self.peek()[0] == ')':
                self.get()
            return node
        elif nxt == 'TERM':
            self.get()
            return ('TERM', val)
        elif nxt == 'EOF':
            return None
        else:
            self.get()
            return ('TERM', val)


def normalize_legal_search_text(t: str) -> str:
    """法學文字與案號泛化正規化"""
    return re.sub(r'[\s\r\n\t,，、。！？（）()]+', '', t.lower())


def match_term_in_legal_text(term: str, text: str) -> bool:
    """判斷單一關鍵字或判決字號是否命中文字池"""
    t_lower = text.lower()
    term_lower = term.lower().strip()
    if not term_lower:
        return True
    if term_lower in t_lower:
        return True

    if re.search(r'\d+', term_lower):
        norm_t = normalize_legal_search_text(text)
        norm_term = normalize_legal_search_text(term)
        norm_t_clean = re.sub(r'(?:年度|年|第|號|字)', '', norm_t)
        norm_term_clean = re.sub(r'(?:年度|年|第|號|字)', '', norm_term)
        if norm_term_clean and norm_term_clean in norm_t_clean:
            return True

    return False


def evaluate_boolean_ast(node: Any, text: str) -> bool:
    """遞迴求值 AST 節點"""
    if node is None:
        return True
    kind = node[0]
    if kind == 'TERM':
        return match_term_in_legal_text(node[1], text)
    elif kind == 'AND':
        return evaluate_boolean_ast(node[1], text) and evaluate_boolean_ast(node[2], text)
    elif kind == 'OR':
        return evaluate_boolean_ast(node[1], text) or evaluate_boolean_ast(node[2], text)
    elif kind == 'NOT':
        return not evaluate_boolean_ast(node[1], text)
    return True


def evaluate_boolean_query(query: str, text: str) -> bool:
    """對任意文字串求值專業布林查詢"""
    if not query.strip():
        return True
    try:
        parser = BooleanQueryParser(query)
        ast = parser.parse()
        if ast is None:
            return True
        return evaluate_boolean_ast(ast, text)
    except Exception:
        raw_words = [w.strip() for w in re.split(r'[\s&+\-＆＋－()（）]+', query) if len(w.strip()) >= 2]
        if not raw_words:
            return True
        return all(w in text for w in raw_words)


def extract_boolean_positive_terms(node: Any) -> List[str]:
    """提取布林樹中正向應包含的關鍵字列表"""
    if node is None:
        return []
    kind = node[0]
    if kind == 'TERM':
        return [node[1]]
    elif kind in ('AND', 'OR'):
        return extract_boolean_positive_terms(node[1]) + extract_boolean_positive_terms(node[2])
    elif kind == 'NOT':
        return []
    return []


# ==============================================================================
# 模組 1.5：司法裁判案號縮寫智慧解析與查找引擎 (Court Citation Abbreviation Engine)
# ==============================================================================

CHINESE_DIGIT_MAP = {
    '一': '1', '二': '2', '三': '3', '四': '4', '五': '5',
    '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'
}

TRACK_COURT_TAXONOMY = [
    ('智民上', '智慧財產及商業法院'),
    ('智刑上', '智慧財產及商業法院'),
    ('智行上', '智慧財產及商業法院'),
    ('民著上', '智慧財產及商業法院'),
    ('民專上', '智慧財產及商業法院'),
    ('民商上', '智慧財產及商業法院'),
    ('行專上', '智慧財產及商業法院'),
    ('行商上', '智慧財產及商業法院'),
    ('台上大', '最高法院'),
    ('台抗大', '最高法院'),
    ('台上', '最高法院'),
    ('台抗', '最高法院'),
    ('重上更', '臺灣高等法院'),
    ('重上', '臺灣高等法院'),
    ('上易', '臺灣高等法院'),
    ('上訴', '臺灣高等法院'),
    ('重勞上', '臺灣高等法院'),
    ('勞上', '臺灣高等法院'),
    ('重家上', '臺灣高等法院'),
    ('家上', '臺灣高等法院'),
    ('加上', '臺灣高等法院'),
    ('上', '最高行政法院'),
    ('抗', '最高行政法院'),
]

# 常用法院簡稱與標準法院全稱對照表（支援最高行、北高行、最高院、高院、智財法院、各地院等）
COURT_ABBREVIATIONS = {
    # 最高行政法院
    "最高行": "最高行政法院",
    "最高行政法院": "最高行政法院",
    "最高行政": "最高行政法院",
    "最行": "最高行政法院",
    "SC行": "最高行政法院",
    "sc行": "最高行政法院",
    "Sc行": "最高行政法院",
    # 高等行政法院
    "北高行": "臺北高等行政法院",
    "台北高等行政法院": "臺北高等行政法院",
    "臺北高等行政法院": "臺北高等行政法院",
    "中高行": "臺中高等行政法院",
    "台中高等行政法院": "臺中高等行政法院",
    "臺中高等行政法院": "臺中高等行政法院",
    "高高行": "高雄高等行政法院",
    "高雄高等行政法院": "高雄高等行政法院",
    "高行": "高等行政法院",
    # 最高法院
    "最高院": "最高法院",
    "最高法院": "最高法院",
    "最高法": "最高法院",
    "最高": "最高法院",
    "SC": "最高法院",
    "sc": "最高法院",
    "Sc": "最高法院",
    # 臺灣高等法院及各分院
    "高院": "臺灣高等法院",
    "臺灣高等法院": "臺灣高等法院",
    "台灣高等法院": "臺灣高等法院",
    "臺高院": "臺灣高等法院",
    "台高院": "臺灣高等法院",
    "台中高分院": "臺灣高等法院臺中分院",
    "臺中高分院": "臺灣高等法院臺中分院",
    "中高分院": "臺灣高等法院臺中分院",
    "中高分": "臺灣高等法院臺中分院",
    "台南高分院": "臺灣高等法院臺南分院",
    "臺南高分院": "臺灣高等法院臺南分院",
    "南高分院": "臺灣高等法院臺南分院",
    "南高分": "臺灣高等法院臺南分院",
    "高雄高分院": "臺灣高等法院高雄分院",
    "高高分院": "臺灣高等法院高雄分院",
    "高高分": "臺灣高等法院高雄分院",
    "花蓮高分院": "臺灣高等法院花蓮分院",
    "花高分院": "臺灣高等法院花蓮分院",
    "金門高分院": "福建高等法院金門分院",
    "金高分院": "福建高等法院金門分院",
    # 智慧財產及商業法院
    "智財法院": "智慧財產及商業法院",
    "智財高院": "智慧財產及商業法院",
    "智商法院": "智慧財產及商業法院",
    "智商": "智慧財產及商業法院",
    "智財": "智慧財產及商業法院",
    "智慧財產法院": "智慧財產及商業法院",
    "智慧財產及商業法院": "智慧財產及商業法院",
    # 憲法法庭與大法官
    "憲法法庭": "憲法法庭",
    "憲法庭": "憲法法庭",
    "憲判": "憲法法庭",
    "大法官": "司法院大法官",
    # 懲戒法院
    "懲戒法院": "懲戒法院",
    "公懲會": "公務員懲戒委員會",
    # 地方法院簡稱
    "北院": "臺灣臺北地方法院",
    "台北地院": "臺灣臺北地方法院",
    "臺北地院": "臺灣臺北地方法院",
    "士院": "臺灣士林地方法院",
    "士林地院": "臺灣士林地方法院",
    "板院": "臺灣新北地方法院",
    "新北地院": "臺灣新北地方法院",
    "桃院": "臺灣桃園地方法院",
    "桃園地院": "臺灣桃園地方法院",
    "竹院": "臺灣新竹地方法院",
    "新竹地院": "臺灣新竹地方法院",
    "苗院": "臺灣苗栗地方法院",
    "苗栗地院": "臺灣苗栗地方法院",
    "中院": "臺灣臺中地方法院",
    "台中地院": "臺灣臺中地方法院",
    "臺中地院": "臺灣臺中地方法院",
    "彰院": "臺灣彰化地方法院",
    "彰化地院": "臺灣彰化地方法院",
    "投院": "臺灣南投地方法院",
    "南投地院": "臺灣南投地方法院",
    "雲院": "臺灣雲林地方法院",
    "雲林地院": "臺灣雲林地方法院",
    "嘉院": "臺灣嘉義地方法院",
    "嘉義地院": "臺灣嘉義地方法院",
    "南院": "臺灣臺南地方法院",
    "台南地院": "臺灣臺南地方法院",
    "臺南地院": "臺灣臺南地方法院",
    "雄院": "臺灣高雄地方法院",
    "高雄地院": "臺灣高雄地方法院",
    "橋院": "臺灣橋頭地方法院",
    "橋頭地院": "臺灣橋頭地方法院",
    "屏院": "臺灣屏東地方法院",
    "屏東地院": "臺灣屏東地方法院",
    "東院": "臺灣臺東地方法院",
    "台東地院": "臺灣臺東地方法院",
    "花院": "臺灣花蓮地方法院",
    "花蓮地院": "臺灣花蓮地方法院",
    "宜院": "臺灣宜蘭地方法院",
    "宜蘭地院": "臺灣宜蘭地方法院",
    "基院": "臺灣基隆地方法院",
    "基隆地院": "臺灣基隆地方法院",
    "澎院": "臺灣澎湖地方法院",
    "澎湖地院": "臺灣澎湖地方法院",
    "金院": "福建金門地方法院",
    "金門地院": "福建金門地方法院",
    "連院": "福建連江地方法院",
    "連江地院": "福建連江地方法院"
}

def normalize_citation_track(s: str) -> str:
    """
    正規化裁判字軌：
    - 更審跨括號與中文數字相容：如「重上更(一)」、「重上更一」、「重上更（一）」、「重上更1」皆正規化為「重上更1」
    - 專業法院字軌相容：如「加上」相容「家上」
    """
    t = s.strip().replace('（', '(').replace('）', ')')
    def repl_geng(m):
        inner = m.group(1)
        num = CHINESE_DIGIT_MAP.get(inner, inner)
        return f"更{num}"
    t = re.sub(r'更\s*\(\s*([0-9一二三四五六七八九]+)\s*\)', repl_geng, t)
    t = re.sub(r'更\s*([0-9一二三四五六七八九]+)', repl_geng, t)
    if t.startswith('加上'):
        t = '家上' + t[2:]
    return t

def normalize_court_case_citation(s: str) -> str:
    """
    裁判字號全文正規化（用於精準/包含比對）：
    - 保護專門字軌：院字、院解字、釋字、憲判字
    - 更審字軌統一
    - 消除年度、年、第、號、字等標籤虛字
    """
    res = s.strip().replace('（', '(').replace('）', ')')
    res = res.replace('院解字', '@@YUANJIE@@')
    res = res.replace('院字', '@@YUAN@@')
    res = res.replace('釋字', '@@SHI@@')
    res = res.replace('憲判字', '@@XIANPAN@@')
    res = res.replace('憲判', '@@XIANPAN@@')

    def repl_geng(m):
        inner = m.group(1)
        num = CHINESE_DIGIT_MAP.get(inner, inner)
        return f"更{num}"
    res = re.sub(r'更\s*\(\s*([0-9一二三四五六七八九]+)\s*\)', repl_geng, res)
    res = re.sub(r'更\s*([0-9一二三四五六七八九]+)', repl_geng, res)
    res = re.sub(r'加上', '家上', res)

    res = re.sub(r'(?:年度|年|第|號|字)', '', res)
    res = re.sub(r'[\s\-_()（）/.,，]+', '', res.lower())

    res = res.replace('@@yuanjie@@', '院解')
    res = res.replace('@@yuan@@', '院')
    res = res.replace('@@shi@@', '釋')
    res = res.replace('@@xianpan@@', '憲判')
    return res

def extract_case_components(text: str) -> Dict[str, Optional[str]]:
    """
    從裁判字號、公報名稱或標題中精確解析（年度、字軌、案號）
    防止案號數字部分重疊（如 15 誤命中 4015、151、2150）以及字軌混淆（如 上 誤命中 台上）
    """
    if not text:
        return {"year": None, "track": None, "no": None}
    t = text.strip().replace(' ', '')
    
    # 1. 司法院解釋與憲法法庭判決
    m_yj = re.search(r'院解字第?(\d+)號?', t)
    if m_yj: return {'year': None, 'track': '院解', 'no': m_yj.group(1)}
    m_yz = re.search(r'院字第?(\d+)號?', t)
    if m_yz: return {'year': None, 'track': '院', 'no': m_yz.group(1)}
    m_sz = re.search(r'釋字第?(\d+)號?', t)
    if m_sz: return {'year': None, 'track': '釋', 'no': m_sz.group(1)}
    m_xp = re.search(r'(?:(\d{1,3})年)?憲判字第?(\d+)號?', t)
    if m_xp: return {'year': m_xp.group(1), 'track': '憲判', 'no': m_xp.group(2)}

    # 2. 一般司法裁判: 如 "最高法院110年度台上字第4015號"、"最高行政法院 110 年度上字第 15 號判決"
    m_std = re.search(r'(\d{1,3})\s*(?:年度|年)\s*([^\d]+?)\s*(?:字第|字|第)\s*(\d+)\s*號', t)
    if m_std:
        return {'year': m_std.group(1), 'track': m_std.group(2), 'no': m_std.group(3)}
    
    # 3. 縮寫或簡短案號: 如 "110台上4015"、"110上15"
    m_short = re.search(r'^(\d{1,3})\s*([a-zA-Z\u4e00-\u9fa5\(\)（）]+?)\s*(\d+)$', t)
    if m_short:
        return {'year': m_short.group(1), 'track': m_short.group(2), 'no': m_short.group(3)}

    # 4. 備援抓取
    m_num = re.search(r'(?:字第|第)\s*(\d+)\s*號', t) or re.search(r'(?<!\d)(\d+)\s*號', t)
    m_yr = re.search(r'(?<!\d)(\d{1,3})\s*(?:年度|年)', t)
    return {
        'year': m_yr.group(1) if m_yr else None,
        'track': None,
        'no': m_num.group(1) if m_num else None
    }

def parse_case_abbreviation_query(query: str) -> Dict[str, Any]:
    """
    智慧解析案號縮寫：
    - 最高行110上15 -> 最高行政法院 110 年度上字第 15 號判決
    - 北高行109訴567 -> 臺北高等行政法院 109 年度訴字第 567 號判決
    - 最高院108台上1719 -> 最高法院 108 年度台上字第 1719 號判決
    - 智財法院111民專上2 -> 智慧財產及商業法院 111 年度民專上字第 2 號判決
    - 108台上908 -> 108年度台上字第908號判決/裁定
    - 108台上908民 -> 108年度台上字第908號民事判決
    - 108台上908民決 -> 108年度台上字第908號民事判決
    - 108台上大1719裁 -> 108年度台上大字第1719號大法庭裁定
    - 40台上86例 -> 40年台上字第86號判例
    - 院字2949 -> 司法院院字第2949號解釋
    - 院解字3001 / 院解3001 -> 司法院院解字第3001號解釋
    - 釋字785 -> 司法院釋字第785號解釋
    - 111憲判1 -> 憲法法庭111年憲判字第1號判決
    - 重上更一15 / 重上更(一)15 -> 重上更(一)字第15號
    - 109家上12 / 109加上12 -> 109年度家上字第12號
    - 110最高行上15 -> 最高行政法院 110 年度上字第 15 號判決
    """
    q = query.strip()
    raw_q = q
    info = {
        "raw": raw_q,
        "court": None,         # 正式法院全銜 (如 最高行政法院、最高法院、臺北高等行政法院)
        "court_abbr": None,    # 使用者輸入或比對之法院簡稱 (如 最高行、北高行)
        "year": None,
        "track": None,
        "no": None,
        "nature": None,       # 民 / 刑 / 行
        "doc_type": None,     # 判決 / 裁定 / 判例 / 解釋
        "clean_norm": normalize_court_case_citation(raw_q)
    }

    # 0. 識別法院前綴或年份後之法院簡稱 (如 "最高行110上15" 或 "110最高行上15")
    # 先依照簡稱長度由長至短排序比對，避免前綴衝突（例如 "臺北高等行政法院" 比 "北高行" 比 "高行"）
    sorted_court_abbrs = sorted(COURT_ABBREVIATIONS.keys(), key=lambda x: len(x), reverse=True)
    
    # 情況 A: 法院簡稱在最開頭，如 "最高行 110 上 15" 或 "北院 110 訴 10"
    for abbr in sorted_court_abbrs:
        pattern_prefix = rf'^{re.escape(abbr)}\s*'
        if re.match(pattern_prefix, q):
            info["court_abbr"] = abbr
            info["court"] = COURT_ABBREVIATIONS[abbr]
            q = re.sub(pattern_prefix, '', q)
            # 若為行政法院系列，預設性質為 "行"
            if "行政" in info["court"]:
                info["nature"] = "行"
            break

    # 1. 書類尾綴判定 (例 / 判例 / 決 / 判決 / 裁 / 裁定)
    if q.endswith(('判例', '例')):
        info["doc_type"] = "判例"
        q = re.sub(r'(?:判例|例)$', '', q)
    elif q.endswith(('判決', '決')):
        info["doc_type"] = "判決"
        q = re.sub(r'(?:判?決)$', '', q)
    elif q.endswith(('裁定', '裁')):
        info["doc_type"] = "裁定"
        q = re.sub(r'(?:裁定|裁)$', '', q)

    # 2. 性質判定 (民 / 刑 / 行)
    if q.endswith(('民事', '民')) and not any(q.endswith(k) for k in ['智民', '商民']):
        info["nature"] = "民"
        q = re.sub(r'(?:民事|民)$', '', q)
    elif q.endswith(('刑事', '刑')) and not q.endswith('智刑'):
        info["nature"] = "刑"
        q = re.sub(r'(?:刑事|刑)$', '', q)
    elif q.endswith(('行政', '行')) and not q.endswith('智行'):
        info["nature"] = "行"
        q = re.sub(r'(?:行政|行)$', '', q)

    # 情況 B: 法院簡稱在年份之後，如 "110最高行上15"、"109北高行訴567"
    if not info.get("court"):
        m_yr_court = re.match(r'^(\d{1,3})\s*(?:年|年度)?\s*([a-zA-Z\u4e00-\u9fa5]+)', q)
        if m_yr_court:
            yr_candidate = m_yr_court.group(1)
            rest_candidate = m_yr_court.group(2)
            for abbr in sorted_court_abbrs:
                if rest_candidate.startswith(abbr):
                    info["court_abbr"] = abbr
                    info["court"] = COURT_ABBREVIATIONS[abbr]
                    if "行政" in info["court"]:
                        info["nature"] = "行"
                    # 將 q 替換為 去掉法院簡稱的字串：如 "110最高行上15" -> "110上15"
                    q = q[:m_yr_court.start(2)] + rest_candidate[len(abbr):] + q[m_yr_court.end(2):]
                    break

    # 3. 司法院院字、院解字、釋字、憲判
    m_special = re.search(r'^(?:司法院)?\s*(\d{1,3})?\s*(?:年|年度)?\s*(院解字|院解|院字|釋字|憲判(?:字)?)(?:第)?\s*(\d+)(?:號)?$', q)
    if m_special:
        info["year"] = m_special.group(1)
        tr = m_special.group(2)
        if tr == '院解': tr = '院解字'
        if tr.startswith('院解'): info["track"] = '院解'
        elif tr.startswith('院'): info["track"] = '院'
        elif tr.startswith('釋'): info["track"] = '釋'
        elif tr.startswith('憲判'): info["track"] = '憲判'
        info["no"] = m_special.group(3)
        if '憲判' in tr:
            info["doc_type"] = info["doc_type"] or "判決"
            info["court"] = "憲法法庭"
        else:
            info["doc_type"] = info["doc_type"] or "解釋"
            info["court"] = "司法院大法官"
        return info

    # 4. 常見格式: [年度] [字軌] [號數]
    q_compact = re.sub(r'\s+', '', q)
    pattern = r'^(\d{1,3})?\s*(?:年|年度)?\s*([a-zA-Z\u4e00-\u9fa5\(\)（）\d]+?)\s*(?:字|字第|第)?\s*(\d+)(?:號)?$'
    m = re.match(pattern, q_compact)
    if m:
        grp2 = m.group(2)
        grp3 = m.group(3)
        # 判斷是否為行政函釋 (部會機關代字或長流水號)
        if any(k in grp2 for k in ['經商', '經企', '經工', '金管', '勞動', '智著', '智專', '智商', '台財', '財政', '內授', '內政', '衛部', '法檢', '保訓']) or len(grp3) >= 6:
            info["doc_type"] = "行政函釋"
            info["track"] = grp2
            info["no"] = grp3
        else:
            info["year"] = m.group(1)
            info["track"] = normalize_citation_track(grp2)
            info["no"] = grp3
            if not info.get("court"):
                for track_key, ct in sorted(TRACK_COURT_TAXONOMY, key=lambda x: len(x[0]), reverse=True):
                    if track_key == info["track"] or (len(track_key) > 1 and track_key in info["track"]):
                        info["court"] = ct
                        if "行政" in ct:
                            info["nature"] = "行"
                        break
    else:
        if q_compact.isdigit():
            info["no"] = q_compact
        elif any(k in q_compact for k in ['經商', '金管', '勞動', '智著', '台財', '財政', '函', '令']):
            info["doc_type"] = "行政函釋"
            info["track"] = q_compact
        else:
            info["track"] = normalize_citation_track(q_compact)

    return info

def match_case_abbreviation(parsed_info: dict, case_record: dict) -> bool:
    """判斷一筆裁判/解釋字典是否符合縮寫解析條件（嚴格防禦案號部分字串重疊與字軌混淆）"""
    cid = case_record.get("case_id", "") or case_record.get("id", "") or case_record.get("interpret_id", "")
    level = case_record.get("level", "")
    court = case_record.get("court", "")
    title = case_record.get("title", "")
    full_str = f"{cid} {court} {level} {title}"
    full_norm = normalize_court_case_citation(full_str)

    # 提取候選標的之精確案號結構
    cand_comp = extract_case_components(cid)
    if not cand_comp or not cand_comp.get("no"):
        cand_comp = extract_case_components(title) or cand_comp

    # 0. 法院比對 (若 query 明確指定法院或法院簡稱)
    if parsed_info.get("court"):
        expected_court = parsed_info["court"]
        # 最高行政法院 vs 最高法院 嚴格防護
        if "行政" in expected_court:
            if "行政" not in full_str:
                return False
        elif expected_court == "最高法院":
            if "行政" in full_str:
                return False
        else:
            court_match = False
            if expected_court in full_str or expected_court in court:
                court_match = True
            elif parsed_info.get("court_abbr") and parsed_info["court_abbr"] in full_str:
                court_match = True
            else:
                court_core = expected_court.replace("臺灣", "").replace("福建", "").replace("高等行政法院", "高行")
                if court_core in full_str or court_core in court:
                    court_match = True
            if not court_match:
                return False

    # 1. 號數精準比對 (嚴格防止 15 命中 4015、151、2150 等)
    if parsed_info.get("no"):
        req_no = str(parsed_info["no"]).strip()
        cand_no = cand_comp.get("no")
        if cand_no:
            if cand_no != req_no:
                return False
        else:
            strict_no_pat = rf'(?<!\d){re.escape(req_no)}(?!\d)'
            if not re.search(strict_no_pat, cid) and not re.search(strict_no_pat, title):
                return False

    # 2. 年度精準比對
    if parsed_info.get("year"):
        req_yr = str(parsed_info["year"]).strip()
        cand_yr = cand_comp.get("year")
        if cand_yr:
            if cand_yr != req_yr:
                return False
        else:
            strict_yr_pat = rf'(?<!\d){re.escape(req_yr)}(?!\d)\s*(?:年|年度)'
            if not re.search(strict_yr_pat, cid) and not re.search(strict_yr_pat, title):
                return False

    # 3. 字軌嚴格比對 (防範 上 誤命中 台上、台上大、重上 等)
    if parsed_info.get("track"):
        req_tr = normalize_citation_track(parsed_info["track"])
        cand_tr = normalize_citation_track(cand_comp.get("track") or "") if cand_comp.get("track") else ""
        
        # 共同別名映射 (釋/釋字、院/院字、院解/院解字、憲判/憲判字)
        alias_groups = [
            {'釋', '釋字'},
            {'院', '院字'},
            {'院解', '院解字'},
            {'憲判', '憲判字'},
            {'大', '大裁', '大法庭'},
            {'家上', '加上'},
            {'台上大', '上大'},
            {'台抗大', '抗大'},
        ]
        def are_tracks_compatible(t1, t2):
            if t1 == t2:
                return True
            for g in alias_groups:
                if t1 in g and t2 in g:
                    return True
            return False

        if cand_tr:
            if not are_tracks_compatible(req_tr, cand_tr):
                return False
        else:
            # 特殊邊界防護：當 req_tr 為 '上' 時，候選字串不可是 '台上'、'重上'、'上訴'、'上易' 等
            if req_tr == '上':
                if re.search(r'(?<![台重勞家加])上(?!大|訴|易)', full_str) is None:
                    return False
            elif req_tr == '抗':
                if re.search(r'(?<![台])抗(?!大)', full_str) is None:
                    return False
            else:
                track_norm = normalize_court_case_citation(req_tr)
                if track_norm not in full_norm:
                    if '家' in track_norm and track_norm.replace('家', '加') in full_norm:
                        pass
                    else:
                        return False

    # 4. 性質比對 (民/刑/行)
    if parsed_info.get("nature"):
        nat = parsed_info["nature"]
        if nat == "民":
            if not any(k in full_str for k in ["民事", "民", "民著", "民專", "民商", "家"]):
                return False
        elif nat == "刑":
            if not any(k in full_str for k in ["刑事", "刑"]):
                return False
        elif nat == "行":
            if not any(k in full_str for k in ["行政", "高等行政", "最高行政", "行專", "行商"]):
                return False

    # 5. 文書類型比對 (判決/裁定/判例/解釋)
    if parsed_info.get("doc_type"):
        dt = parsed_info["doc_type"]
        if dt == "判例":
            if not any(k in full_str for k in ["判例", "例"]):
                return False
        elif dt == "判決":
            if "判決" not in full_str and "判例" not in full_str and "憲判" not in full_str:
                return False
        elif dt == "裁定":
            if "裁定" not in full_str:
                return False
        elif dt == "解釋":
            if not any(k in full_str for k in ["解釋", "釋字", "院字", "院解"]):
                return False

    return True

def construct_standard_citation_from_parsed(info: dict) -> str:
    """依縮寫解析結果組合標準權威案號字樣"""
    raw_track = info.get("track") or ""
    year = info.get("year")
    no = info.get("no")
    doc_type = info.get("doc_type") or "判決"
    nature = info.get("nature") or ""

    if doc_type == "行政函釋" or any(k in raw_track for k in ['經商', '經企', '經工', '金管', '勞動', '智著', '智專', '智商', '台財', '財政', '函', '令']):
        no_str = f"字第 {no} 號" if no else ""
        return f"{raw_track}{no_str}函釋"
    if raw_track == '院':
        return f"司法院 院字第 {no} 號解釋" if no else "司法院 院字號解釋"
    if raw_track == '院解':
        return f"司法院 院解字第 {no} 號解釋" if no else "司法院 院解字號解釋"
    if raw_track == '釋':
        return f"司法院釋字第 {no} 號解釋" if no else "司法院大法官解釋"
    if raw_track == '憲判':
        y_str = f"{year} 年" if year else ""
        return f"憲法法庭 {y_str}憲判字第 {no} 號判決" if no else "憲法法庭判決"

    # 更審字軌呈現: 更1 -> 更(一)
    display_track = raw_track
    geng_m = re.search(r'更(\d+)', display_track)
    if geng_m:
        digit = geng_m.group(1)
        rev_map = {'1': '一', '2': '二', '3': '三', '4': '四', '5': '五'}
        c_digit = rev_map.get(digit, digit)
        display_track = re.sub(r'更\d+', f"更({c_digit})", display_track)

    # 優先採用 parsed_info 中已解析出的法院全銜
    court = info.get("court")
    if not court:
        for track_key, ct in sorted(TRACK_COURT_TAXONOMY, key=lambda x: len(x[0]), reverse=True):
            if track_key == raw_track or (len(track_key) > 1 and track_key in raw_track):
                court = ct
                break
        if not court:
            court = "最高行政法院" if raw_track in ['上', '抗', '大', '聲', '再'] and not raw_track.startswith('台') else "最高法院"
        if '重上' in raw_track or '更' in raw_track:
            court = "臺灣高等法院"

    # 若為行政法院或智慧財產法院，性質細緻處理
    is_admin_court = "行政" in court
    
    if is_admin_court:
        nat_str = ""  # 行政法院裁判通常直接稱「判決」或「裁定」，不贅述「行政判決」
    else:
        nat_str = "民事" if nature == "民" else ("刑事" if nature == "刑" else ("行政" if nature == "行" else ""))
        if any(k in raw_track for k in ["著", "專", "商"]):
            nat_str = "行政" if "行" in raw_track else "民事"
        elif "家" in raw_track:
            nat_str = "家事"

    if doc_type == "判例":
        year_str = f"{year} 年" if year else ""
        return f"{court} {year_str}{display_track}字第 {no} 號判例"
    elif "大法庭" in display_track or display_track in ["大", "大裁"]:
        year_str = f"{year} 年度" if year else ""
        track_disp = "大" if display_track in ["大", "大裁"] else display_track
        chamber_type = "行政大法庭" if is_admin_court else (f"{nat_str}大法庭" if nat_str else "大法庭")
        return f"{court} {year_str}{track_disp}字第 {no} 號{chamber_type}裁定"
    else:
        year_str = f"{year} 年度" if year else ""
        nat_tail = f"{nat_str}{doc_type}" if nat_str else doc_type
        return f"{court} {year_str}{display_track}字第 {no} 號{nat_tail}"


def lookup_case_by_abbreviation(query: str) -> Dict[str, Any]:
    """
    全方位縮寫檢索器（相容介面，由 find_legal_doc_by_citation 統一提供）：
    1. 解析縮寫 query
    2. 依序搜尋 BUILTIN_LANDMARK_DOCS、precedents_catalog、PRESET_JUDGEMENT_HISTORIES、行政函釋大典
    3. 若命中，回傳完整裁判資訊與全文內容
    4. 若未在本地庫，自動組裝權威標準名稱與官方公報檢索直連
    """
    res = find_legal_doc_by_citation(query)
    if res:
        return res
    return {"matched": False, "found": False, "query": "", "message": "請輸入案號縮寫"}


# ==============================================================================
# 模組 2：一鍵 AI 裁判與長篇函釋核心要旨自動精鍊 (AI Legal Summarizer)
# ==============================================================================

BUILTIN_LANDMARK_DOCS: List[Dict[str, Any]] = [
    {
        "id": "DOC_1_SUPREME_COURT_1719",
        "doc_type": "🏛️ 最高法院民事大法庭裁定",
        "title": "最高法院 108 年度台上大字第 1719 號裁定（借名登記出名人處分效力案）",
        "text": """最高法院 108 年度台上大字第 1719 號民事裁定
【主文】
不動產借名登記契約之出名人，未經借名人同意，將該不動產所有權移轉登記予第三人，無論第三人為善意或惡意，均屬有權處分，借名人不得主張該移轉行為無效或準用無權處分之規定。

【理由要旨】
一、提案爭點：
不動產借名登記契約之出名人，未經借名人同意，將該不動產所有權移轉登記予第三人，其處分之效力為何？實務上有「有權處分說」與「無權處分說」之嚴重分歧。
二、本院大法庭統一見解：
（一）物權公示原則與實質歸屬之權衡：
民法第758條第1項規定：「不動產物權，依法律行為而取得、設定、喪失及變更者，非經登記，不生效力。」此為我國物權變動之登記生效主義與公示原則。
借名登記契約，出名人既已依法律行為登記為不動產之所有權人，對外即為該不動產之合法所有人。借名人僅享有請求返還不動產之內部債權請求權，並無直接對抗第三人之物權效力。
（二）有權處分說之立論依據：
出名人就登記於自己名下之不動產為移轉登記，係本於其物權登記名義人所具備之法律上處分權能而為，性質上屬有權處分。第三人無論知情與否（不論善意或惡意），均得有效取得該不動產之所有權。借名人不得以其內部契約關係對抗第三人，亦無民法第118條無權處分規定之適用。
（三）救濟途徑：
出名人擅自處分該不動產，致借名人受有損害，借名人得依債務不履行（不完全給付、給付不能）、侵權行為（民法第184條）或不當得利（民法第179條），向出名人請求損害賠償或返還處分之代價，以資救濟。"""
    },
    {
        "id": "DOC_2_CONSTITUTION_COURT_1",
        "doc_type": "📜 憲法法庭判決",
        "title": "憲法法庭 111 年憲判字第 1 號判決（肇事逃逸強制抽血檢測人身自由案）",
        "text": """憲法法庭 111 年憲判字第 1 號判決
【案由】
聲請人認道路交通管理處罰條例第35條第5項及刑事訴訟法第205條之2規定，關於警察對肇事駕駛人得強制移送醫療機構採取血液檢驗酒精濃度之程序，有牴觸憲法第8條正當法律程序及第22條身體不受侵害權與資訊隱私權之疑義。

【判決主文】
一、道路交通管理處罰條例第35條第5項規定，受檢測人如拒絕接受酒精濃度測試之檢定，交通勤務警察得違反其意願強制移送醫療機構實施抽血檢測部分，牴觸憲法第8條保障人身自由與第22條保障身體權、資訊隱私權之意旨，應自本判決公告之日起，至遲於屆滿二年時，失其效力。
二、刑事訴訟法第205條之2規定，司法警察（官）因調查犯罪嫌疑，對非附隨於逮捕拘提之嫌疑人強制抽血檢測，亦牴觸法官保留原則與正當法律程序原則。

【核心理由】
一、強制抽血檢驗涉及人身自由、身體不受侵犯權及基因資訊隱私權之嚴重干預：
強制將人帶往醫療院所，以針筒刺穿皮膚抽取血液，侵害人身自由與身體完整性甚鉅；且血液樣本含有個人去氧核糖核酸（DNA）等高度敏感之個人生理健康與遺傳基因資訊，受憲法第22條隱私權之最高度保護。
二、違反法官保留原則與比例原則：
採取血液檢驗酒精濃度，性質上屬於干預基本權之侵入性身體檢查，原則上應由中立客觀之法官核發鑑定許可書（法官保留原則）；即便情況急迫，亦應設有嚴格之急迫要件，並由檢察官事前許可或於事後一定時限內（例如24小時內）報請法院實施事後司法審查。現行法未設任何令狀要求與救濟機制，純由警察逕行決定發動，顯已逾越必要比例。"""
    },
    {
        "id": "DOC_3_FIRE_BURDEN_OF_PROOF_2843",
        "doc_type": "🏛️ 最高法院民事判決",
        "title": "最高法院 109 年度台上字第 2843 號民事判決（倉庫大火舉證責任分配案）",
        "text": """最高法院 109 年度台上字第 2843 號民事判決
【主文】
原判決關於駁回上訴人請求被上訴人損害賠償之訴部分廢棄，發回臺灣高等法院。

【理由要旨】
一、爭點核心：
出租倉庫因不明起火點引發火災，導致承租人寄放之數億元高科技貨物全毀。承租人依民法第227條不完全給付及第432條租賃物保管義務請求賠償，其火災起因不可歸責於出租人之舉證責任應如何分配？
二、民事訴訟法第277條但書之精確適用（危險領域說與舉證責任轉換）：
（一）按民事訴訟法第277條本文規定：「當事人主張有利於己之事實者，就其事實有舉證之責任。」
（二）惟同條但書明定：「但法律別有規定，或依其情形顯失公平者，不在此限。」在現代高度專業化、設備封閉性之倉儲租賃契約中，倉庫之結構安全、電器配線、消防滅火設備及定期安全巡檢，完全處於出租人所得掌控支配之「危險領域」範圍內。
（三）反觀承租人，僅享有貨物進出擺放之權限，對倉庫牆垣內部管線是否有電氣火花、是否有老舊短路之危險源，客觀上處於無從知悉、無法介入蒐證之結構性舉證困境。
（四）若仍苛求承租人必須就「火災之具體起火原因係出租人疏於維護電線所致」負舉證責任，顯然違反武器平等原則，依其情形顯失公平。法院應依民事訴訟法第277條但書規定，倒置舉證責任，命處於危險掌控領域內之出租人，就其已盡善良管理人注意義務、火災之發生不可歸責於己之免責事實負舉證責任。"""
    },
    {
        "id": "DOC_4_MOEA_COMPANY_LAW_173_1",
        "doc_type": "📑 經濟部行政函釋",
        "title": "經濟部 107 年經商字第 10702425020 號函（公司法第173條之1過半數股東召集股東會函釋）",
        "text": """經濟部 107 年 11 月 8 日經商字第 10702425020 號函
【要旨】
有關公司法第173條之1規定繼續三個月以上持有已發行股份總數過半數之股東，得自行召集股東臨時會之持股計算基準日與召集程序疑義。

【內容】
一、按民國107年11月1日修正施行之公司法第173條之1第1項規定：「繼續三個月以上持有已發行股份總數過半數股份之股東，得自行召集股東臨時會。」其立法目的係為解決過往董事會不作為、拒不召開股東會，導致公司治理僵局之弊端，賦予大股東跨過董事會直接訴諸全體股東之正當自力召集權。
二、持股期間與持股成數之認定基準：
（一）「繼續三個月以上」之起算點：係以股東會「停止過戶日前一日」往前推算連續三個月，其持股均不得低於已發行股份總數之過半數。
（二）數股東共同召集之認定：數股東得共同合併計算其持股期間與股份總數。但共同召集之發起股東名冊一經申報公告，不得於中途任意增減替換其他股東，否則其召集權之正當性即告欠缺。
三、與董事會召集權之競合：
若董事會與過半數股東同時訂於同一日或相近日期召集股東臨時會，討論相同之議案（如全面改選董事），因二者均具備法定召集權，應由先合法踐行公告及寄發召集通知者為有效召集；後召集者之股東會，其決議可能構成公司法第189條決議方法違反法令之撤銷事由。"""
    },
    {
        "id": "DOC_5_FSC_INSURANCE_LAW_64",
        "doc_type": "📑 金管會保險局行政令函",
        "title": "金管會保險局金管保產字第 1090494553 號令（保險法第64條據實說明義務實務認定）",
        "text": """金融監督管理委員會 109 年 12 月 18 日金管保產字第 1090494553 號令
【要旨】
訂定「保險人依保險法第64條第2項規定行使契約解除權之因果關係審查標準與招攬核保自律原則」。

【法理與實務指示】
一、保險法第64條據實說明義務之核心立法本旨：
要保人於訂立保險契約時，對於保險人之書面詢問，應據實說明。要保人如有隱匿、遺漏或為不實說明，足以變更或減少保險人對於危險之估計者，保險人得解除契約；其危險發生後亦同。
二、保險人解除權之實質限制（因果關係抗辯）：
保險法第64條第2項但書明定：「要保人證明危險之發生未基於其說明或未說明之事實時，不在此限。」
實務上保險人不得僅憑要保人填寫要保書時遺漏說明過往輕微就診病史（如感冒、胃食道逆流），即於發生重大車禍失能事故時主張解除全部契約。
三、金管會嚴格要求保險業踐行下列審查要件：
（一）書面詢問之具體性：書面詢問事項必須具體明確，不得使用「概括性無限制詢問條款」。
（二）客觀因果關係：保險人主張解除契約，必須就「未說明之事項與嗣後出險事故之發生具有直接因果關係或相當因果關係」負舉證責任。
（三）除斥期間之恪遵：保險人自知有解除原因時起，一個月內不行使而消滅；契約訂立後經過二年，即有可以解除之原因，亦不得解除契約。"""
    },
    {
        "id": "DOC_6_MONEY_LAUNDERING_2530",
        "doc_type": "🏛️ 最高法院刑事判決",
        "title": "最高法院 110 年度台上字第 2530 號刑事判決（人頭帳戶洗錢罪主觀犯意案）",
        "text": """最高法院 110 年度台上字第 2530 號刑事判決
【主文】
上訴駁回。

【理由要旨】
一、爭點：
提供自己金融帳戶提款卡與密碼予詐欺集團成員之「人頭帳戶提供者」，究成立刑法第30條第1項、第339條第1項之詐欺幫助犯，抑或該當洗錢防制法第14條第1項之一般洗錢罪正犯？
二、最高法院統一刑罰論理：
（一）洗錢防制法第2條第2款規定，洗錢行為包括「掩飾或隱匿特定犯罪所得來源、去向、所在，或以任何方式使他人隱匿特定犯罪所得」之行為。
（二）提供金融帳戶金融卡及密碼予非親非故之他人，使犯罪集團得以利用該帳戶作為向被害人詐欺取財匯款之中繼站，該帳戶即產生遮斷資金金流追查、掩飾犯罪所得去向之功能。
（三）提供者如依其智識經驗，能預見金融帳戶可能被用於掩飾重大犯罪所得，竟仍容任其發生而交出卡片密碼者，主觀上已具備洗錢之「不確定故意（間接故意）」，應成立洗錢防制法第14條第1項之一般洗錢罪，不因其未實際經手提款而免除正犯罪責。"""
    },
    {
        "id": "DOC_7_SUPREME_COURT_40_86",
        "doc_type": "🏛️ 最高法院判例",
        "title": "最高法院 40 年台上字第 86 號判例（無權代理之效力與善意相對人保護）",
        "text": """最高法院 40 年台上字第 86 號民事判例
【裁判字號】：最高法院 40 年台上字第 86 號
【裁判類別】：民事判例
【裁判要旨】：
無權代理人以本人名義所為之法律行為，非經本人承認，對於本人不生效力，民法第170條第1項定有明文。
是以無代理權人以本人名義與相對人訂立買賣契約，在本人承認之前，該契約係處於效力未定之狀態。
相對人得定相當期限，催告本人確答是否承認，本人逾期未為確答者，視為拒絕承認；相對人於本人未承認前，亦得行使撤回權。
若本人拒絕承認，除符合表見代理（民法第169條）應負授權人之責任外，本人對該法律行為自始不負任何履約或移轉責任，善意相對人僅得本於民法第110條規定，向無權代理人請求損害賠償。"""
    },
    {
        "id": "DOC_8_SUPREME_COURT_30_482",
        "doc_type": "🏛️ 最高法院判例",
        "title": "最高法院 30 年上字第 482 號判例（契約合意解除與法定解除權之競合）",
        "text": """最高法院 30 年上字第 482 號民事判例
【裁判字號】：最高法院 30 年上字第 482 號
【裁判類別】：民事判例
【裁判要旨】：
契約之合意解除（協議解除），係由契約當事人以第二次契約消滅第一次契約之權利義務關係，其本質為互為要約與承諾之契約行為；
與當事人一方本於民法法定解除權（如給付遲延、給付不能）或契約約定解除權行使之單方形成權，其性質截然有別。
合意解除成立後，當事人之間應如何清算、返還已交付之給付或賠償損失，應悉依雙方合意解除之契約約定內容為準。
民法第259條關於法定解除權行使後回復原狀之規定，在合意解除之場合，並非當然予以準用。當事人若未特別約定返還已受領之價金或約定沒收充作違約金，法院應探求當事人之真意，不得逕行命依民法第259條回復原狀。"""
    },
    {
        "id": "DOC_9_JUDICIAL_YUAN_2949",
        "doc_type": "📜 司法院院字解釋",
        "title": "司法院 33 年院字第 2949 號解釋（土地法所有權登記之絕對效力與真實權利人對抗）",
        "text": """司法院 33 年 4 月 29 日院字第 2949 號解釋
【裁判字號】：司法院院字第 2949 號解釋
【解釋機關】：司法院
【要旨】：
土地法第43條（舊土地法第36條）所謂依本法所為之登記，有絕對效力，其立法本旨係為保護信賴登記之善意第三人而設。
將不知情之第三人排除於實質權利爭端之外，以維護不動產交易之安全與土地登記之公信力。
惟在當事人間，若登記名義人取得登記原因具有重大瑕疵、出於偽造、偽作買賣或屬無實質權源者，真實權利人自得本於所有權排除侵害請求權（民法第767條第1項中段）訴請塗銷該虛偽登記。
土地法第43條之絕對效力，不得作為登記名義人於內部關係對抗實質所有權人之防護傘。真實權利人在第三人取得權利前，其塗銷登記請求權不受土地法登記絕對效力之阻卻。"""
    },
    {
        "id": "DOC_10_JUDICIAL_YUAN_3001",
        "doc_type": "📜 司法院院解字解釋",
        "title": "司法院 34 年院解字第 3001 號解釋（動產善意取得與佔有輔助人擅自處分）",
        "text": """司法院 34 年 11 月 16 日院解字第 3001 號解釋
【裁判字號】：司法院院解字第 3001 號解釋
【解釋機關】：司法院
【要旨】：
受僱人、學徒或基於其他類似關係受本人指示而支配物者，為占有輔助人（民法第942條），僅本人為占有人。
占有輔助人擅自將本人交付其管領之動產，出賣並交付於善意第三人時，因本人已將該物交付於占有輔助人管領，其支配地位係出於本人之自願託付。
此項情事與民法第949條盜贓或遺失物之非自願喪失占有截然不同。
善意第三人信賴占有之外觀而為受讓，得依民法第801條及第948條即時取得其所有權。本人不得以占有輔助人欠缺實質處分權為由，對善意受讓之第三人請求返還該物。"""
    },
    {
        "id": "DOC_11_HIGH_COURT_GENG_1_15",
        "doc_type": "🏛️ 臺灣高等法院判決",
        "title": "臺灣高等法院 108 年度重上更(一)字第 15 號民事判決（重大工程契約與情事變更增加給付案）",
        "text": """臺灣高等法院 108 年度重上更(一)字第 15 號民事判決
【案由】：給付工程款等
【主文】：原判決關於駁回上訴人後開第二項之訴部分廢棄。被上訴人應給付上訴人新臺幣貳仟陸佰捌拾萬元及自起訴狀繕本送達翌日起算之利息。
【理由要旨】：
一、爭點核心：
營造工程承攬契約簽訂後，突遭國際原物料劇烈波動、鋼筋及預拌混凝土價格暴漲逾50%，承租/承攬人依民法第227條之2情事變更原則，請求法院判命增加給付工程款，應如何衡量「顯失公平」與「不可歸責」之舉證責任？
二、高等法院法律心證：
（一）按契約成立後，情事變更，非當時所得預料，而依其原有效果顯失公平者，當事人得聲請法院增、減其給付或變更其他原有之效果，民法第227條之2第1項定有明文。
（二）營建工程之原物料價格於契約簽訂後發生超過一般物價總指數異常暴漲，該項原物料漲幅已遠逾投標當時客觀理性營造廠商所得合理預估之物價風險波動範圍。
（三）若仍硬性拘泥於契約原約定之總價承攬條款，命承攬人獨自吸收全額暴漲成本，將導致承攬人陷入嚴重虧損破產，顯失實質公平正義。法院應本於誠信原則，重新調整分擔比例，判命定作人核實增加給付。"""
    },
    {
        "id": "DOC_12_IP_COURT_109_12",
        "doc_type": "🏢 智慧財產法院判決",
        "title": "智慧財產及商業法院 109 年度民著上字第 12 號民事判決（軟體著作權實質近似與合理使用抗辯案）",
        "text": """智慧財產及商業法院 109 年度民著上字第 12 號民事判決
【案由】：侵害著作權有關財產權爭議等
【裁判要旨】：
一、爭點：
電腦軟體原始碼著作權之侵權判定標準為何？當被告接觸原告軟體原始碼後，開發出功能類似之系統，如何判定構成「實質相似」（Substantial Similarity）？
二、智慧財產法院判斷標準：
（一）抽象/過濾/比較三步驟檢驗法（AFC Test）：
判定電腦軟體著作是否構成侵權，應循「抽象化」、「過濾」、「比較」三階段進行：首先將電腦程式依構想、模組架構、流程、副程式至原始碼逐層抽象化；次將欠缺原創性、公有領域程式碼、效率唯一表現（合併原則）予以過濾；最後就剩餘具原創性之實質部分進行比較。
（二）合理使用之抗辯要件：
被告主張符合著作權法第65條第2項之合理使用，應審酌利用之目的及性質、著作之性質、所利用之質量與在整個著作所占之比例、利用結果對著作潛在市場與現在價值之影響。商業性之直接重製，難以主張合理使用。"""
    },
    {
        "id": "DOC_13_IP_ADMIN_COURT_110_5",
        "doc_type": "🏢 智慧財產法院判決",
        "title": "智慧財產及商業法院 110 年度行專上字第 5 號行政判決（專利進步性判斷與教示動機案）",
        "text": """智慧財產及商業法院 110 年度行專上字第 5 號行政判決
【案由】：發明專利申請核駁審定
【主文】：上訴駁回。
【裁判要旨】：
一、發明專利進步性審查原則（專利法第22條第2項）：
發明專利雖具備新穎性，但為所屬技術領域中具有通常知識者依申請前之先前技術顯能輕易完成時，仍不得取得發明專利。
二、結合多份引證案之「教示或動機」（Teaching, Suggestion, or Motivation）：
審查進步性若結合複數引證先前技術，審查機關必須具體釋明該所屬技術領域通常知識者，在客觀上有何動機或技術教示，促使其將引證一之技術特徵與引證二之結構相互結合。
不得事後對照本件專利說明書之完成態樣，反向倒果為因推論該結合乃屬簡易可成（嚴格禁止「後見之明」/ Hindsight Bias）。
在本案中，引證一與引證二同屬高頻半導體封裝散熱技術領域，其所欲解決之熱應力問題具有共通關聯性，客觀上存在顯著之組合動機，自難認具備進步性。"""
    },
    {
        "id": "DOC_14_FAMILY_COURT_109_12",
        "doc_type": "🏛️ 臺灣高等法院家事判決",
        "title": "臺灣高等法院 109 年度家上字第 12 號民事判決（民法第1030條之1剩餘財產分配顯失公平調整案）",
        "text": """臺灣高等法院 109 年度家上字第 12 號民事家事判決
【案由】：剩餘財產分配等
【主文】：原判決關於命上訴人給付超過新臺幣肆佰貳拾萬元本息部分廢棄。
【理由要旨】：
一、民法第1030條之1第2項立法意旨與實務裁量：
法定財產制關係消滅時，夫或妻現存之婚後財產，扣除婚姻關係存續所負債務後，如有剩餘，其雙方剩餘財產之差額，應平均分配。
惟夫妻之一方對於婚姻生活無貢獻或協力，或有其他情事，致平均分配顯失公平者，法院得調整或免除其分配額。
二、法院心證：
剩餘財產分配請求權之制度本旨，在於肯定配偶於婚姻存續期間，操持家務、育幼或精神支持對於他方積累財產具有實質協力貢獻。
若一方在客觀上長年離家不歸、酗酒揮霍、對家庭生活費用未有分文負擔，亦未協力操持家務，純由他方一人兼職撫育子女並積累財產，若仍准其享有剩餘財產半數之分配，顯悖於婚姻忠實與協力本質，依其情形顯失公平，法院應依法酌減其受分配額度。"""
    },
    {
        "id": "DOC_15_SUPREME_COURT_108_908",
        "doc_type": "🏛️ 最高法院民事判決",
        "title": "最高法院 108 年度台上字第 908 號民事判決（純粹經濟上損失與民法第184條侵權責任保護客體案）",
        "text": """最高法院 108 年度台上字第 908 號民事判決
【主文】：原判決廢棄，發回臺灣高等法院。
【理由要旨】：
一、爭點：
原告因被告挖損公用地下電纜導致工廠停工三日所受之「營業利潤損失」，究屬民法第184條第1項前段之權利侵害，抑或純粹經濟上損失（Pure Economic Loss）？
二、最高法院確立之侵權行為體系分工：
（一）民法第184條第1項前段規定：「因故意或過失，不法侵害他人之權利者，負損害賠償責任。」其保護客體嚴格限於固有之「權利」（包括人格權、身分權、物權、智慧財產權等絕對權）。
（二）純粹經濟上損失，係指非因被害人之人身或所有權遭受實體損害而衍生之純粹財產上利益減損。此項純粹經濟上損失並非民法第184條第1項前段之保護客體。
（三）如欲就純粹經濟上損失請求損害賠償，被害人必須依民法第184條第1項後段「故意以背於善良風俗之方法加損害於他人」，或第2項「違反保護他人之法律」之要件，始得主張救濟。原審未辨明權利侵害與純粹財產損失之區別，逕依第184條第1項前段命被告賠償營業停工利潤，其適用法律顯有違誤。"""
    },
    {
        "id": "DOC_16_SUPREME_ADMIN_110_15",
        "doc_type": "🏛️ 最高行政法院判決",
        "title": "最高行政法院 110 年度上字第 15 號判決（地方議會議員停權處分與司法審查界線案）",
        "text": """最高行政法院 110 年度上字第 15 號行政判決
【案由】：有關地方自治事務事件
【上訴人】：新竹縣議會
【被上訴人】：余筱菁（時任新竹縣議員）
【原審判決】：臺北高等行政法院 109 年度訴字第 774 號判決
【主文】：
原判決廢棄，發回臺北高等行政法院。

【裁判核心法律爭點】：
一、地方議會依其內部自律規則對個別民選議員作成「停止出席會議（停權）」之懲戒決議，其法律性質為何？受停權處分之議員得否循行政訴訟程序尋求司法救濟？
二、議會自律原則（內部自律高權）與司法審查權（憲法第16條訴訟權保障、無漏洞權利保護原則）之界線應如何劃分？
三、限制民意代表出席議會行使憲法及地方制度法賦予之提案、質詢、審議預算法案與表決權，是否受法律保留原則與比例原則之拘束？

【最高行政法院判決理由要旨】：
一、議員受停權決議干預其公法上法定職權，具備行政訴訟權利保護必要：
（一）地方議會由全體議員依法選舉組成，以合議制形式行使地方自治團體之立法、預算審查及監督施政等公法上權限。議員個人基於公法上民意代表職能，享有出席各項大會與臨時會、審議提案、發言與表決之法定權能（法律上之力）。
（二）地方議會所為禁止特定議員出席會議之懲戒（停權）處分，實質剝奪並限制該民意代表在特定會期內行使憲法與法律保障之公法上權限，直接干預其民選公職身分之正常行使，對其憲政法益與公法上權利構成實質侵害。
（三）按憲法第16條保障人民訴訟權，宣示「有權利即有救濟」之核心法理，並參酌司法院釋字第381號、第499號解釋意旨，議員自得本於公法上權利受直接侵害之地位，向行政法院提起行政訴訟尋求救濟，具備訴訟權能與實質權利保護必要。

二、議會內部紀律處分之定性與行政訴訟類型選擇：
（一）地方議會對議員施以紀律懲戒，本質上係地方民意代表機關本於維持議事秩序、維護議會尊嚴所行使之自治內部管理事項，於地方自治團體機關單元間創設並變更公法上法律效果。
（二）受懲戒議員若認停權決議違法侵害其權利，於停權會期經過後，因停權規制已執行完畢，原告得依法轉換或提起行政訴訟法第6條第1項後段之「確認公法上法律關係成立/不成立」或「確認行政處分違法」之確認訴訟，以洗刷名譽並回復其民主民意代表之合法地位。

三、原判決違背法令與發回更審之關鍵：
（一）地方制度法第31條雖授權地方議會自訂自律規則，惟剝奪民選代表出席權與審議權之嚴厲懲戒手段，關涉地方民主正當性核心，必須具備明確法令授權，並恪遵正當法律程序（如陳述意見、迴避原則）與比例原則。
（二）原審法院對於新竹縣議會紀律委員會設置辦法之授權位階、議會自律權與司法審查界線之具體限度，以及事實認定之完備性尚有未盡，爰將原判決廢棄，發回原審臺北高等行政法院更為審理。

【司律二試國考作答 IRAC 實戰提示】：
1. Issue：地方議會議員停權處分之法律性質？議員得否提起行政訴訟尋求司法審查？
2. Rule：憲法第16條有權利即有救濟、地方制度法第31條、司法院釋字第381號、第499號、最高行政法院110年度上字第15號判決。
3. Application：
   - 傳統特別權力關係與議會自律原則認為內部紀律事項不許司法審查；
   - 最高行政法院新近定錨見解揚棄絕對自律說，肯定停權決議直接侵害議員之法定出席與表決權，具有重大外部法律效果，肯定其行政訴訟之訴訟權能；
   - 審查密度上，行政法院應本於法律保留與比例原則進行實質審查，不得藉由議會自律為由全盤放任侵權。"""
    }
]


try:
    from legal_query_engine import EXTENDED_JUDICIAL_AUTHORITIES
    _existing_b_titles = {b.get("title", "") for b in BUILTIN_LANDMARK_DOCS}
    for auth in EXTENDED_JUDICIAL_AUTHORITIES:
        if auth.get("case_id") not in _existing_b_titles:
            lines = [
                "【權威字號】：" + auth.get("case_id", ""),
                "【機關與位階】：" + auth.get("court", "") + "（" + auth.get("level", "") + "）",
                "【案由與主題】：" + auth.get("title", ""),
                "【涉及法條】：" + "、".join(auth.get("laws_cited", [])),
                "",
                "【核心法律爭點】：",
                auth.get("issue", ""),
                "",
                "【判例／決議／座談會核心要旨】：",
                auth.get("holding", ""),
                "",
                "【學說與實務對照】：",
                auth.get("scholarly_views", ""),
                "",
                "【司律二試國考作答指引】：",
                auth.get("exam_application_hint", "")
            ]
            BUILTIN_LANDMARK_DOCS.append({
                "id": "AUTH_" + re.sub(r"[^0-9a-zA-Z]", "_", auth.get("case_id", "")),
                "doc_type": auth.get("level", ""),
                "title": auth.get("case_id", ""),
                "text": "\n".join(lines)
            })
            _existing_b_titles.add(auth.get("case_id"))
except Exception:
    pass


def find_legal_doc_by_citation(citation: str) -> Optional[Dict[str, Any]]:
    """
    全方位法學字號檢索引擎（裁判字號・大法官解釋・憲判字・中央主管機關長篇函釋）：
    支援縮寫、案號全名、機關公文字號、純字軌數字與發文字號：
    1. 優先比對內建指標法學判解全文庫 (BUILTIN_LANDMARK_DOCS)
    2. 比對中央部會 628+ 則行政函釋與令釋大典 (含經濟部、金管會、智慧財產局、法務部、勞動部)
    3. 比對全國 1,256+ 裁判大典目錄庫 (含最高法院民刑大法庭、憲法法庭判決與歷審脈絡鏈)

    回傳字典：
    - 若命中：{"found": True, "matched": True, "title": ..., "doc_type": ..., "text": ..., "holding_snippet": ..., "court_or_agency": ..., "laws_cited": [...], "search_urls": ..., "source_type": ...}
    - 若未命中：{"found": False, "matched": False, "citation": citation, "standard_title": ..., "search_urls": ...}
    - 若輸入為空：None
    """
    if not citation or not citation.strip():
        return None
    raw = citation.strip()
    parsed = parse_case_abbreviation_query(raw)
    std_title = construct_standard_citation_from_parsed(parsed)
    norm = re.sub(r'[\s\-_，,。號字第（）()]+', '', raw).lower()
    digits = re.findall(r'\d+', raw)
    search_urls = generate_judicial_search_urls(std_title or raw)

    has_abbreviation = bool(parsed.get('track') or parsed.get('no') or parsed.get('doc_type'))
    is_admin_query = (
        parsed.get('doc_type') == "行政函釋" or
        any(k in raw for k in ['經商', '經企', '經工', '金管', '勞動', '智著', '智專', '智商', '台財', '財政', '內授', '內政', '衛部', '法檢', '保訓', '函', '令']) or
        any(len(d) >= 6 for d in digits)
    )

    # 1. 內建指標判解 (BUILTIN_LANDMARK_DOCS)
    for b in BUILTIN_LANDMARK_DOCS:
        b_title = b.get('title', '')
        b_norm = re.sub(r'[\s\-_，,。號字第（）()]+', '', b_title).lower()
        matched = False
        if match_case_abbreviation(parsed, {"case_id": b_title, "title": b_title}):
            matched = True
        elif not has_abbreviation:
            if norm and len(norm) >= 3 and (norm in b_norm or b_norm in norm):
                matched = True
            elif digits:
                if any(len(d) >= 5 and re.search(rf'(?<!\d){re.escape(d)}(?!\d)', b_title) for d in digits):
                    matched = True
                elif len(digits) >= 2 and all(re.search(rf'(?<!\d){re.escape(d)}(?!\d)', b_norm) for d in digits):
                    matched = True

        if matched:
            return {
                'found': True,
                'matched': True,
                'source': 'builtin',
                'source_type': 'builtin_landmark',
                'title': b_title,
                'doc_type': b.get('doc_type', '🏛️ 最高法院權威裁判書'),
                'citation': raw,
                'court_or_agency': b.get('doc_type', '').replace('🏛️', '').replace('📜', '').replace('📑', '').replace('🏢', '').strip(),
                'laws_cited': [],
                'holding_snippet': b.get('text', '')[:280].strip(),
                'text': b.get('text', ''),
                'summary': b_title,
                'search_urls': generate_judicial_search_urls(b_title),
                'raw_doc': b
            }

    # 2. 行政函釋大典 (admin_rulings)
    try:
        if is_admin_query or (not has_abbreviation and parsed.get('doc_type') not in ['判決', '裁定', '判例', '解釋']):
            from admin_rulings_engine import get_all_administrative_rulings
            all_r = get_all_administrative_rulings()
            for r in all_r:
                r_no = r.get('doc_number', '')
                r_norm = re.sub(r'[\s\-_，,。號字第（）()]+', '', r_no).lower()
                matched = False
                if norm and len(norm) >= 3 and (norm in r_norm or r_norm in norm):
                    matched = True
                elif digits and any(len(d) >= 6 and d in r_no for d in digits):
                    matched = True
                elif parsed.get('no') and len(parsed['no']) >= 5 and parsed['no'] in r_no:
                    matched = True

                if matched:
                    doc_text = f"""【發文字號】：{r.get('doc_number')}
【主管機關】：{r.get('agency', '中央主管機關')}
【發文日期】：{r.get('date', '')}
【規範法典與關聯條號】：{r.get('law_name', '')} {r.get('article_target', '')}
【主旨/案由】：{r.get('title', '')}

【行政函釋核心要旨】：
{r.get('holding', '')}

【主管機關實務認定標準與法理分析】：
{r.get('content_analysis', '')}

【司律二試考點提示】：
{r.get('exam_point_hint', '')}
"""
                    full_title = f"{r.get('agency', '中央部會')} {r.get('doc_number', '')}（{r.get('title', '')}）"
                    return {
                        'found': True,
                        'matched': True,
                        'source': 'admin_ruling',
                        'source_type': 'admin_ruling',
                        'title': full_title,
                        'doc_type': '📑 中央部會行政函釋',
                        'citation': r.get('doc_number', raw),
                        'court_or_agency': r.get('agency', '行政主管機關'),
                        'laws_cited': [f"{r.get('law_name', '')} {r.get('article_target', '')}".strip()] if r.get('law_name') else [],
                        'holding_snippet': (r.get('holding') or r.get('title') or '')[:280].strip(),
                        'text': doc_text,
                        'summary': full_title,
                        'search_urls': generate_judicial_search_urls(f"{r.get('agency', '')} {r.get('doc_number', '')}"),
                        'raw_doc': r
                    }
    except Exception:
        pass

    # 3. 全國裁判大典 (precedents_catalog)
    try:
        cat = get_precedents_catalog()
        best = None
        matched_cat = [item for item in cat if match_case_abbreviation(parsed, item)]
        if matched_cat:
            best = matched_cat[0]
        elif not has_abbreviation:
            p_by_id = get_precedent_by_id(raw)
            if p_by_id:
                best = p_by_id
            else:
                for c in cat:
                    cid = c.get('case_id', '')
                    cid_norm = re.sub(r'[\s\-_，,。號字第（）()]+', '', cid).lower()
                    if norm and len(norm) >= 3 and (norm in cid_norm or cid_norm in norm):
                        best = c
                        break
                    if digits and len(digits) >= 2 and all(re.search(rf'(?<!\d){re.escape(d)}(?!\d)', cid) for d in digits):
                        best = c
                        break

        if best:
            cid = best.get("case_id", "")
            tit = best.get("title", "")
            hold = best.get("holding", "")
            iss = best.get("issue", "")
            sch = best.get("scholarly_views", "") or best.get("scholarly", "")
            hint = best.get("exam_application_hint", "")
            laws = best.get("laws_cited", [])

            chain = get_precedent_history_chain(cid) or get_precedent_history_chain(raw)
            hist_text = ""
            if chain and chain.get('timeline_stages'):
                hist_text = "\n【裁判歷審與審級脈絡更迭】：\n"
                for st in chain['timeline_stages']:
                    hist_text += f"- [{st.get('stage', '')}] {st.get('court', '')} ({st.get('case_no', '')}): {st.get('ruling', '')}\n  理由: {st.get('holding_summary', '')}\n"
                if chain.get('distinguishing_insight'):
                    hist_text += f"\n【歷審心證歧異與上位關鍵分析】：\n{chain['distinguishing_insight']}\n"
                if chain.get('exam_strategy'):
                    hist_text += f"\n【司律二試解題與考場鋪陳戰略】：\n{chain['exam_strategy']}\n"

            text_parts = [
                f"【案號與裁判】：{cid}",
                f"【裁判主文與爭點主題】：{tit}",
                f"【審理法院/位階】：{best.get('court', '')} ({best.get('level', '')})",
                f"【涉及關聯法條】：{'、'.join(laws)}" if laws else "",
                f"\n【案件核心法律爭點 (Legal Issue)】：\n{iss}" if iss else "",
                f"\n【法院核心論理與判決要旨 (Holding & Rationale)】：\n{hold}" if hold else "",
                f"\n【權威學說論著評析與肯否二說】：\n{sch}" if sch else "",
                f"\n【司律二試上位卷 IRAC 作答策略指南】：\n{hint}" if hint else "",
                hist_text
            ]
            full_doc_text = "\n".join([p for p in text_parts if p])

            doc_type_label = "🏛️ 最高法院/高等法院裁判書"
            if "釋字" in cid or "憲判" in cid:
                doc_type_label = "📜 憲法法庭判決/釋字"
            elif "大法庭" in cid:
                doc_type_label = "🏛️ 最高法院大法庭裁定"
            elif "判例" in cid or "例" in cid:
                doc_type_label = "🏛️ 最高法院判例"

            return {
                'found': True,
                'matched': True,
                'source': 'precedents_catalog',
                'source_type': 'precedents_catalog',
                'title': cid,
                'doc_type': doc_type_label,
                'citation': cid,
                'court_or_agency': best.get('court', '最高法院'),
                'laws_cited': laws,
                'holding_snippet': (hold or tit or '')[:280].strip(),
                'text': full_doc_text,
                'summary': cid,
                'search_urls': generate_judicial_search_urls(cid),
                'raw_doc': best
            }
    except Exception:
        pass

    # 4. 百萬裁判 SQLite 資料庫 (MillionJudgmentsSQLiteEngine)
    try:
        from build_million_judgments_db import get_million_db_engine
        db_doc = get_million_db_engine().find_by_citation(raw)
        if db_doc and db_doc.get("found"):
            return {
                'found': True,
                'matched': True,
                'source': 'million_db',
                'source_type': 'million_db',
                'title': db_doc.get('title', raw),
                'doc_type': db_doc.get('doc_type', '🏛️ 司法裁判書'),
                'citation': raw,
                'court_or_agency': db_doc.get('court_or_agency', '法院'),
                'laws_cited': db_doc.get('laws_cited', []),
                'holding_snippet': db_doc.get('holding_snippet', '')[:280].strip(),
                'text': db_doc.get('text', ''),
                'summary': db_doc.get('title', raw),
                'search_urls': generate_judicial_search_urls(db_doc.get('title', raw)),
                'raw_doc': db_doc
            }
    except Exception:
        pass

    return {
        'found': False,
        'matched': False,
        'source': 'constructed',
        'citation': raw,
        'parsed_info': parsed,
        'standard_title': std_title or raw,
        'doc_type': "🏛️ 最高法院/高等法院裁判書" if "憲" not in (std_title or raw) and "釋" not in (std_title or raw) and not any(k in (std_title or raw) for k in ["經商", "智", "金管", "函", "令"]) else ("📑 中央部會行政函釋" if any(k in (std_title or raw) for k in ["經商", "智", "金管", "函", "令"]) else "📜 憲法法庭判決/釋字"),
        'text': f"【案件案號】：{std_title or raw}\n【系統提示】：本案已完成案號縮寫標準化解析！請點選下方官方裁判書開放系統直連，查閱全文後複製貼上於此，即可立即啟動 AI 核心要旨深度精鍊。",
        'search_urls': search_urls
    }


class AILegalSummarizer:
    """
    一鍵 AI 裁判與長篇函釋核心要旨自動精鍊引擎
    """
    def __init__(self):
        self.api_key = get_gemini_api_key()

    def _call_model(self, prompt: str) -> str:
        models_to_try = get_gemini_models_to_try()
        last_error = None

        if USE_MODERN_GENAI:
            client = genai.Client(api_key=self.api_key) if self.api_key else genai.Client()
            for model_name in models_to_try:
                try:
                    resp = client.models.generate_content(
                        model=model_name,
                        contents=prompt
                    )
                    if resp and resp.text:
                        return resp.text
                except Exception as e:
                    last_error = e
                    continue
        else:
            if self.api_key:
                legacy_genai.configure(api_key=self.api_key)
            for model_name in models_to_try:
                try:
                    m = legacy_genai.GenerativeModel(model_name)
                    resp = m.generate_content(prompt)
                    if resp and resp.text:
                        return resp.text
                except Exception as e:
                    last_error = e
                    continue

        raise RuntimeError(f"AI 法學摘要引擎調用失敗: {last_error}")

    def summarize(
        self,
        doc_text: str,
        doc_type: str = "裁判書",
        title: str = "",
        subject: str = "法學專業領域"
    ) -> Dict[str, Any]:
        # 1. 執行裁判爭點實質性檢驗與歷審裁判萃取 (貫徹指示：排除欠缺法律爭點之裁判，並高度注重歷審裁判)
        substance_info = evaluate_judgment_substance(doc_text, title=title, doc_type=doc_type)
        has_issue = substance_info.get("has_legal_issue", True)
        history_instances = substance_info.get("extracted_history_instances", [])
        substantive_prior = substance_info.get("substantive_prior_instance")
        discard_reason = substance_info.get("discard_reason", "")
        evolution_md = format_instance_evolution_markdown(history_instances, current_case_id=title)

        # 2. 若欠缺實體法律爭點 (純程序駁回、未繳費、程式不合、例行量刑)：
        #    排除實體 IRAC 深度分析，改為輸出程序診斷並高度聚焦於其【歷審裁判 (原審實體判決)】！
        if not has_issue:
            prior_link_hint = ""
            if substantive_prior:
                prior_link_hint = f"""
> 💡 **【關鍵歷審導引】**：本件裁判本身為無實體爭鳴之程序裁定，但本案兩造實質攻防與爭點事實完整記載於【**{substantive_prior.get('case_id')}**】中。
> 系統已自內文中自動定位該原審裁判，建議直接調閱或貼入該原審判決全文，AI 將為您進行實體法學要旨與 IRAC 深度精鍊！
"""

            res_md = f"""### ⚠️ 【爭點實質性檢驗：無實質法律爭點・已排除實體分析】
本案經系統「爭點實質性評鑑核心」嚴格檢驗，屬於**欠缺實體法學爭點之裁判**：
- **實質排除原因**：{discard_reason}
- **裁判審查性質**：形式合法性審查（如程式欠缺、未繳納訴訟費用、逾期上訴或例行量刑處分），通篇無實體法條構成要件之爭鳴與事實涵攝。
- **處理原則**：依司律國考與權威法學「實質法律爭點原則」，系統已**自動自實體要旨深度萃取中排除本裁定**，避免在無爭點裁定上產出無效或虛構之 IRAC 內容。

---

{evolution_md}

{prior_link_hint}

---

### 📋 【本程序裁定之基本案情與主文摘要】
- **承審法院與字號**：【{title or '程序裁定'}】
- **主文結論**：{doc_text[:350].strip()}...
- **程序法規**：{', '.join(substance_info.get('legal_citations_detected', [])) or '民事訴訟法 / 刑事訴訟法相關程序規定'}
"""
            return {
                "title": title,
                "doc_type": doc_type,
                "subject": subject,
                "markdown_result": res_md,
                "has_legal_issue": False,
                "is_procedural_dismissal": substance_info.get("is_procedural_dismissal", True),
                "discard_reason": discard_reason,
                "history_instances": history_instances,
                "substantive_prior_instance": substantive_prior
            }

        # 3. 若具備實體法律爭點：將歷審脈絡鏈注入 Prompt，並嚴格指令模型深化「歷審見解更迭與心證翻轉」！
        prompt = f"""
你是一位台灣「司法院大法官書記處法官」兼「律師司法官高等考試權威名師」，精通裁判解構與長篇公報釋令精萃。
現在使用者輸入了一篇動輒數萬字之【{doc_type}】全文或核心摘錄，請立即執行極致精練、結構嚴謹之【AI 專業級核心要旨深度摘要】：

文書名稱/案號：【{title or '法學文書'}】
文書類型：【{doc_type}】
法學科目領域：【{subject}】

------------------------
【法學文書原始全文/摘錄】：
{doc_text.strip()[:10000]}

------------------------
【已偵測之歷審裁判審級脈絡】：
{evolution_md}

------------------------

請嚴格遵循標準專業規範，依序產出以下六大核心標題（請務必高度注重「歷審裁判」之審級更迭與心證見解翻轉）：

### 📌 一、基本案情與案件程序審級歷程 (特別剖析歷審更迭)
- **當事人背景與紛爭起因**：當事人身分、客觀爭端發生經過、行政處分作成或契約簽訂背景。
- **審級與訴訟/救濟歷程（詳析歷審裁判）**：
  - 第一審事實審（地院）：案號、原告訴求與一審判決結論。
  - 第二審事實/上訴審（高院）：案號、上訴理由、高院是否逆轉或變更一審心證。
  - 第三審法律審（最高法院）或大法庭/憲法法庭：上訴第三審之違背法令指摘與終局法律爭端。

### ⚖️ 二、核心法律爭執焦點 (Legal Issues)
- 提煉 1~3 個最關鍵之實體法或程序法法律爭執點（以標題化明確呈現，例如：【爭點一】借名登記出名人擅自移轉是否構成無權處分？【爭點二】惡意第三人是否受善意受讓之保護？）。
- 爭執背後之法律規範漏洞或學說實務衝突所在。

### 🏛️ 三、裁判要旨與主文核心論理 (Holding & Ratio Decidendi - 對比歷審見解)
- **主文結論**：本院最終諭知之主文結果（如：原判決廢棄發回、上訴駁回、原判決廢棄改判、法規定期失效等）。
- **法院/部會核心裁判理由**：本院統一見解之立論基礎，包括文義解釋、體系解釋、歷史立法意旨與客觀目的衡量。
- **與歷審裁判（原審）之心證翻轉對比**：明確指出本裁判與原審裁判見解是否存在歧異？本審係維持抑或推翻原審？其關鍵法理轉折點為何。

### 💡 四、關鍵法理金句與援引法規/先例 (Key Legal Rationale)
- **法規依據**：引用之核心條文與條項（例如：民法第184條、公司法第173條之1、刑訴第300條）。
- **裁判關鍵金句摘錄**：直接摘錄判決書中最具代表性、最足資引述之經典原文判旨法理句（以引號呈現）。
- **對照之判例/決議/大法庭先例**：本判決所繼承、變更或突破之既有實務見解。

### 📝 五、司律二試上位卷 IRAC 考場引註精華 (300字考場必備金句)
- 專門為國家考試二試考生設計：若考卷出現此爭點，考生可直接背誦或寫入試卷之精準文字：
  - **大前提法理確立（100字）**
  - **開標示範（50字）**
  - **事實涵攝模板（150字）**

### 🎓 六、學說評價與肯否爭議 (Scholar Commentary & Critiques)
- **學界通說與有力學者評價**：國內權威法學教授（如王澤鑑、姜世明、林山田、黃榮堅、陳敏、葉啟洲教授等）對本案裁判/函釋之贊同或批評意見。
- **肯否兩說比較**：
  - **肯定說立論**：...
  - **否定說/批判說立論**：...
- **未來實務發展與修法展望**。

請直接以格式清晰、排版優美、專業嚴謹之繁體中文 Markdown 文本輸出！
"""
        res_md = self._call_model(prompt)
        full_res_md = res_md.strip() + "\n\n---\n\n" + evolution_md
        return {
            "title": title,
            "doc_type": doc_type,
            "subject": subject,
            "markdown_result": full_res_md,
            "has_legal_issue": True,
            "is_procedural_dismissal": False,
            "discard_reason": "",
            "history_instances": history_instances,
            "substantive_prior_instance": substantive_prior
        }
