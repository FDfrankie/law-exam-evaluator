"""
法源法律網 (LawBank) 旗艦功能延伸模組：
1. 功能 2：法源式專業布林邏輯搜尋語法引擎 (Boolean Precision Engine: ＆, ＋, －, ( ))
2. 功能 5：地檢署起訴書 vs 法院判決書「事實認定與論理比對」引擎 (Indictment vs Judgment Comparative Engine)
3. 功能 6：一鍵 AI 裁判與長篇函釋核心要旨自動精鍊 (AI Legal Summarizer - 對標法源 AI 摘要)
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
from legal_query_engine import get_precedents_catalog, get_precedent_by_id, generate_judicial_search_urls

# ==============================================================================
# 模組 1：法源式專業布林邏輯搜尋語法引擎 (Boolean Precision Engine)
# ==============================================================================

class BooleanQueryParser:
    """
    法源式布林邏輯解析器：
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
        # 檢查是否含有布林運算符
        s = query.strip()
        if any(c in s for c in ['＆', '&', '＋', '+', '－']):
            return True
        # 檢查是否含有帶負號的排除詞，如 "-善意受讓" 或 " - 善意"
        if re.search(r'(?:^|\s)[-－][^\s\d]', s):
            return True
        # 檢查是否含有括號運算
        if ('(' in s and ')' in s) or ('（' in s and '）' in s):
            return True
        # 檢查英文字詞 AND / OR / NOT
        if re.search(r'\b(AND|OR|NOT)\b', s, re.IGNORECASE):
            return True
        return False

    def __init__(self, query: str):
        self.raw_query = query
        self.tokens = self._tokenize(query)
        self.pos = 0

    def _tokenize(self, s: str) -> List[Tuple[str, str]]:
        # 統一替換全形運算符
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
                # 隱式 AND
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
    
    # 針對含有數字之判決案號或法條進行泛化匹配（例如「108台上大1719」對照「108年度台上大字第1719號」）
    if re.search(r'\d+', term_lower):
        norm_t = normalize_legal_search_text(text)
        norm_term = normalize_legal_search_text(term)
        # 去除年度/年/第/號/字虛字
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
    """對任意文字串求值法源式布林查詢"""
    if not query.strip():
        return True
    try:
        parser = BooleanQueryParser(query)
        ast = parser.parse()
        if ast is None:
            return True
        return evaluate_boolean_ast(ast, text)
    except Exception:
        # 若語法有特殊嵌套問題，退回標準關鍵字包含檢查
        raw_words = [w.strip() for w in re.split(r'[\s&+\-＆＋－()（）]+', query) if len(w.strip()) >= 2]
        if not raw_words:
            return True
        return all(w in text for w in raw_words)


def extract_boolean_positive_terms(node: Any) -> List[str]:
    """提取布林樹中正向應包含的關鍵字列表（用於權重加分與高亮）"""
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
# 模組 2：地檢署起訴書 vs 法院判決書「事實認定與論理比對」引擎
# ==============================================================================

BUILTIN_INDICTMENT_CASES: List[Dict[str, Any]] = [
    {
        "id": "CASE_1_FRAUD_MONEY_LAUNDERING",
        "title": "詐欺車手提領案：加重詐欺正犯起訴 vs 變更為洗錢罪與幫助犯判決",
        "charge": "三人以上共同詐欺取財罪 (刑法第339條之4第1項第2款)",
        "court_judgment_charge": "普通詐欺罪幫助犯 (刑法第339條第1項、第30條) ＋ 一般洗錢罪 (洗錢防制法第14條第1項)",
        "indictment_summary": """【臺灣臺北地方檢察署檢察官起訴書（節錄）】
案由：詐欺等案件
被告：張某某

犯罪事實：
被告張某某明知近年詐欺集團猖獗，竟與通訊軟體 Telegram 暱稱「戰神」之不詳成年人所屬詐欺集團成員三人以上，共同意圖為自己不法之所有，基於三人以上共同詐欺取財及洗錢之犯意聯絡與行為分擔。由該集團不詳成員於民國112年3月1日撥打電話予被害人陳某，佯稱健保卡遭盜用涉及洗錢云云，致被害人陷於錯誤，於同日將新臺幣（下同）150萬元匯入指定之人頭帳戶。嗣該集團成員旋指示被告張某某持該人頭帳戶之金融卡，前往臺北市大安區某超商ATM提款機，接續分次提領贓款共計150萬元，並將提領之現金放置於指定置物櫃交由集團收水人員，以此方式掩飾、隱匿詐欺犯罪所得之去向。案經被害人報警循線查獲。

所犯法條：
核被告張某某所為，係犯刑法第339條之4第1項第2款之三人以上共同犯詐欺取財罪，及洗錢防制法第14條第1項之一般洗錢罪嫌。被告與「戰神」及其所屬詐欺集團成員間，有犯意聯絡與行為分擔，請依共同正犯論處，並請從一重處斷。""",
        "judgment_summary": """【臺灣臺北地方法院刑事判決（節錄）】
案由：詐欺等
主文：張某某幫助犯詐欺取財罪，處有期徒刑肆月；又犯洗錢防制法第十四條第一項之一般洗錢罪，處有期徒刑陸月，併科罰金新臺幣參萬元。應執行有期徒刑捌月。

犯罪事實及理由（節錄）：
一、公訴意旨認被告張某某涉犯刑法第339條之4第1項第2款三人以上共同詐欺取財罪嫌。訊據被告堅決否認有何三人以上共同詐欺之犯意，辯稱：伊係因缺錢應徵求職，對方自稱是虛擬貨幣幣商，請伊代為提領客戶交割款項，伊僅是聽從指令提款，並不知道電話詐騙之細節，更不知道對方有幾個人等語。
二、經查：公訴人所提出之卷證，僅能證明被害人遭詐騙之匯款紀錄、監視器翻拍照片及被告持卡提款之客觀事實。惟按共同正犯之成立，須有共同犯罪之意思聯絡與行為分擔；而加重詐欺三人以上之要件，亦須行為人主觀上明知並有意促成三人以上共同實行。本案依卷內通訊軟體對話紀錄，與被告接洽者僅有「戰神」一人，卷內並無其他積極證據證明被告於提款之際，明知或預見該詐欺集團在整體謀議或分工上已達三人以上之規模。公訴人認被告構成「三人以上」共同正犯，尚乏積極佐證。
三、惟被告身心健全且具社會經驗，其依未曾謀面之陌生人指示提領鉅款，並放置於隱蔽置物櫃，客觀上顯足以預見所提領者可能為財產犯罪所得，竟仍執意為之，其主觀上具有容認詐欺取財之幫助故意及洗錢之不確定故意甚明。
四、起訴法條之變更與程序告知：
本院審理中，審判長已依刑事訴訟法第95條第1款規定，當庭向被告及其選任辯護人諭知可能變更起訴法條為刑法第30條第1項、第339條第1項之普通詐欺幫助犯，充分保障被告與辯護人之防禦權。公訴意旨認被告成立刑法第339條之4之正犯，容有未洽，惟起訴之社會基礎事實同一，爰依刑事訴訟法第300條規定，變更公訴人所引應適用之法條。"""
    },
    {
        "id": "CASE_2_BORROWED_NAME_EMBEZZLE_BREACH_OF_TRUST",
        "title": "借名登記處分案：侵占罪起訴 vs 最高法院大法庭變更為背信罪判決",
        "charge": "侵占罪 (刑法第335條第1項)",
        "court_judgment_charge": "背信罪 (刑法第342條第1項)",
        "indictment_summary": """【臺灣臺中地方檢察署檢察官起訴書（節錄）】
案由：侵占
被告：李某某

犯罪事實：
告訴人王某某於民國105年間出資購買坐落臺中市西屯區之A土地，因稅制及貸款考量，乃與被告李某某成立不動產借名登記契約，將A土地登記於被告名下，實質所有權及管理收益權仍歸告訴人享有，被告僅為受託登記名義人，為告訴人持有該土地。詎被告於民國110年間因個人財務困窘，竟意圖為自己不法之所有，變易持有為所有之意思，未經告訴人同意，擅自委託不知情之房仲業者將A土地以新臺幣2,500萬元出售並移轉登記予不知情之買受人陳某，並將售地價款全數挪為私用償還個人賭債。案經告訴人發覺提出告訴。

所犯法條：
核被告李某某所為，係犯刑法第335條第1項之普通侵占罪嫌。""",
        "judgment_summary": """【最高法院 108 年度台上大字第 1719 號裁定暨高等法院更審判決（節錄）】
主文：原判決撤銷。李某某為他人處理事務，意圖為自己不法之利益，而為違背其任務之行為，致生損害於本人之財產，處有期徒刑壹年陸月。

理由（節錄）：
一、法律爭點與本院大法庭定錨見解：
不動產借名登記之出名人，未經借名人同意，將該不動產所有權移轉登記予第三人，究應論以刑法第335條第1項之侵占罪，抑或刑法第342條第1項之背信罪？
按不動產物權依法律行為而取得、設定、喪失及變更者，非經登記，不生效力，民法第758條第1項定有明文。不動產借名登記契約，出名人既已依登記取得不動產之法律上所有權，其對外即為該不動產之合法所有權人。出名人處分該不動產，係處分自己名義之財產，在實體法律上自難認係侵占「他人之物」，不合於刑法第335條第1項侵占罪之構成要件。
二、惟出名人基於借名登記契約之內部約定，負有為借名人保管該不動產，並於契約終止時返還登記之任務，屬「為他人處理事務之人」。出名人違背其任務擅自將不動產處分移轉第三人，致借名人喪失不動產權利而受損害，自該當刑法第342條第1項背信罪之構成要件。
三、起訴法條變更：
公訴意旨起訴被告涉犯刑法第335條第1項侵占罪嫌，尚有誤會。然因二者之基礎社會犯罪事實同一，合議庭於審判期日已踐行刑事訴訟法第95條第1款罪名告知義務，被告及辯護人亦已就背信要件實施充分辯護，爰依刑事訴訟法第300條規定，變更起訴法條為背信罪論處。"""
    },
    {
        "id": "CASE_3_TECH_INVESTIGATION_GPS",
        "title": "科技偵查 GPS 案：走私運輸毒品起訴 vs 違法取證排除判決無罪",
        "charge": "運輸第三級毒品罪 (毒品危害防制條例第4條第3項)",
        "court_judgment_charge": "無罪 (刑事訴訟法第301條第1項，依第158條之4排除違法GPS證據)",
        "indictment_summary": """【臺灣高等檢察署高雄檢察分署起訴書（節錄）】
案由：違反毒品危害防制條例
被告：林某某

犯罪事實：
被告林某某基於運輸第三級毒品之犯意，於民國109年8月間受託自屏東恆春海岸接駁毒品愷他命（Ketamine）共計50公斤，藏放於其駕駛之自用小客車後車廂。司法警察接獲情資，旋在被告小客車底盤秘密裝設GPS衛星定位追蹤器，連續追蹤被告行車軌跡長達14日，終在高雄市旗津區攔截被告車輛，當場於後車廂扣得毒品愷他命毛重50,200公克。

所犯法條：
核被告林某某所為，係犯毒品危害防制條例第4條第3項之運輸第三級毒品罪嫌。扣案之毒品請宣告沒收銷燬。""",
        "judgment_summary": """【臺灣高等法院高雄分院刑事判決（節錄）】
主文：林某某無罪。

理由（節錄）：
一、公訴意旨以扣案之毒品愷他命50公斤、警製GPS軌跡報告及搜索扣押筆錄，認被告涉犯運輸毒品重罪。
二、證據能力之嚴格審查（GPS 科技偵查之合法性）：
（一）按個人隱私權乃受憲法第22條保障之基本權利，包括對個人資訊自主掌控之隱私，以及不受公權力無端全天候監控之私領域秘密自由。
（二）司法警察未經檢察官許可，更未向法院法官聲請令狀（法官保留原則），即擅自在人民私有車輛底盤私設 GPS 追蹤器，全天候 24 小時連續 14 天記錄被告所有移動路徑與社交停頓點，侵害人民受憲法保障之隱私權情節極為重大，且欠缺法律明確授權。
（三）依刑事訴訟法第158條之4規定，審酌人權保障與公共利益之均衡維護：執法人員主觀上違背令狀主義之重大違法、侵害隱私權之深遠持續性，若容許此種欠缺法官保留之違法監控作為證據，無異掏空正當法律程序之憲政防線。本院權衡後，裁定排除該 GPS 軌跡紀錄之證據能力；而警方因該違法 GPS 鎖定而發動之附帶搜索扣得之毒品，亦受「毒樹果實原則」之實質波及，同無證據能力。
三、結論：
扣除上述違法取得之證物後，公訴人所舉其餘事證，均不足以證明被告客觀上有運輸毒品之犯行。不能證明被告犯罪，依法應諭知無罪之判決。"""
    },
    {
        "id": "CASE_4_ROBBERY_VS_EXTORTION",
        "title": "持玩具槍搶超商：加重強盜起訴 vs 「至使不能抗拒」欠缺變更為恐嚇取財判決",
        "charge": "加重強盜罪 (刑法第330條、第328條第1項)",
        "court_judgment_charge": "恐嚇取財罪 (刑法第346條第1項)",
        "indictment_summary": """【臺灣新北地方檢察署檢察官起訴書（節錄）】
案由：強盜案件
被告：陳某某

犯罪事實：
被告陳某某因積欠地下錢莊債務，竟意圖為自己不法之所有，於民國111年12月20日深夜，攜帶客觀上具有金屬重量之仿真玩具手槍1支，進入新北市板橋區某超商。被告持槍直指大夜班店員黃某之胸口，並厲聲喝斥：「把收銀機所有千元鈔票拿出來，不然開槍打死你！」店員黃某見狀受迫，遂自收銀機取出新臺幣23,000元交付。被告得手後隨即逃逸。檢察官認被告持客觀上足以使人感受生命威脅之玩具槍，足使常人「至使不能抗拒」，該當強盜罪要件。

所犯法條：
核被告陳某某所為，係犯刑法第330條第1項之攜帶兇器加重強盜罪嫌。""",
        "judgment_summary": """【臺灣新北地方法院刑事判決（節錄）】
主文：陳某某意圖為自己不法之所有，以恐嚇使人將本人之物交付，處有期徒刑壹年貳月。扣案之玩具手槍壹支沒收。

理由（節錄）：
一、強盜罪與恐嚇取財罪之界限：
按強盜罪之強暴、脅迫，以「至使不能抗拒」為要件，即其手段客觀上已抑制被害人之意思自由，達到不能抗拒或無可奈何之程度；若僅使用脅迫手段，使被害人心生畏懼而交付財物，其意思決定自由尚未完全被壓制者，則僅成立刑法第346條之恐嚇取財罪。
二、法院調查事實與心證：
質之被害店員黃某於本院審理時具結證稱：「被告拿槍指著我時，我從槍管接縫和重量看出很像是塑膠玩具槍，我當時雖然害怕他萬一拿出其他真刀，但主要是不想和他發生衝突，店規也交代安全第一，我才決定把收銀機的錢給他打發他走」等語。參以監視器錄影畫面，被害人交付現金時神態冷靜，並無癱軟、哀求或遭完全壓制身體意思之舉動。客觀上被告之脅迫手段固足使被害人心生畏怖，然尚未達致「至使不能抗拒」之強盜程度。
三、起訴法條變更：
公訴意旨論以刑法第330條第1項之加重強盜罪，容有未洽。惟二者基本犯罪事實同一，本院已依法踐行刑訴第95條罪名告知程序，爰依刑事訴訟法第300條變更起訴法條，改論以刑法第346條第1項之恐嚇取財罪。"""
    }
]


class IndictmentJudgmentComparator:
    """
    地檢署起訴書 vs 法院判決書「事實認定與論理比對」核心推理引擎
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

        raise RuntimeError(f"起訴書判決書比對引擎調用失敗: {last_error}")

    def compare(
        self,
        indictment_text: str,
        judgment_text: str,
        case_title: str = "",
        subject: str = "刑事訴訟法與刑法實務"
    ) -> Dict[str, Any]:
        prompt = f"""
你是一位台灣「司法院前最高法院刑庭法官」兼「律師司法官二試刑事法命題閱卷召集人」。
現在請針對以下【檢察官起訴書】與【法院裁判書】之真實實務文稿進行極度精闢、穿透力十足的【起訴事實 vs 判決論理橫向比對剖析】：

案件名稱/主題：【{case_title or '刑事起訴與審判實務比對'}】
所屬法學領域：【{subject}】

------------------------
【地檢署檢察官起訴書全文/節錄】：
{indictment_text.strip()[:6000]}

------------------------
【法院刑事判決書全文/節錄】：
{judgment_text.strip()[:6000]}

------------------------

請嚴格產出具備頂級實務水準與二試上位卷踩分指引之 Markdown 報告，務必包含以下六大核心標題：

### ⚖️ 一、起訴罪名 vs 判決主文 核心對照矩陣
請使用 Markdown 表格，對照以下維度：
| 比對維度 | 🏛️ 地檢署檢察官起訴書主張 | ⚖️ 法院合議庭最終判決認定 | 關鍵落差原因剖析 |
| :--- | :--- | :--- | :--- |
| **訴追/判決罪名** | ... | ... | ... |
| **適用法條依據** | ... | ... | ... |
| **犯意認定 (主觀要件)** | （如：直接故意 / 共同正犯謀議） | （如：不確定故意 / 幫助犯 / 欠缺故意） | ... |
| **客觀行為該當** | ... | ... | ... |
| **證據採擇心證** | ... | （如：部分證據排除 / 補強不足） | ... |

### 二、🔍 要件事實認定之核心落差與檢辯攻防
- 檢察官在起訴書中認定的「犯罪要件事實」關鍵所在。
- 法院合議庭在審判期日調查後，為何不採納檢方的事實建構？（例如：認定無共同正犯意思聯絡、客觀手段未達至使不能抗拒、欠缺持有他人之物前提等）。
- 辯護人成功打擊檢方起訴論證的關鍵辯護攻防點。

### 三、⚖️ 刑事訴訟法第300條「變更起訴法條」適法性深度檢驗
- **起訴效力所及範圍與不告不理原則（刑訴第268條）**：檢察官起訴之事實與法院判決之事實是否具備「基本社會事實同一性」？
- **罪名告知與防禦權保障（刑訴第95條第1款）**：法院於審理期日是否已踐行罪名告知程序？若未告知即逕行變更法條判決，將構成何種判決違背法令（刑訴第379條）？
- **重罪改輕罪 vs 輕罪改重罪之程序嚴格度**。

### 四、🛡️ 證據調查、證據能力與心證折衝（刑訴第158-4條、第159條）
- 檢方起訴所引用的證據，在審判中是否有遭遇「違法取證排除（刑訴第158條之4）」或「傳聞法則排除（刑訴第159條）」？
- 法院如何行使自由心證（刑訴第155條）？無罪推定原則與合理懷疑法則在該案中如何發揮定錨作用？

### 五、🎯 司律二試與檢察實務題高分作答核心指引
- 若考選部出題以此種「檢方起訴某罪，法院審理發現不該當，改判另一罪」為案例事實，考生應如何以頂尖上位卷 IRAC 作答：
  1. **俐落開標示範**：（示範刑訴第300條合法性與實體法罪名認定之標準二標）
  2. **大前提法理定錨**：必備之最高法院大法庭裁定、重要判例字號或判決名言。
  3. **涵攝技巧**：如何精確對比檢方起訴要件與法院心證。

### 六、⚔️ 檢辯攻防實戰論理示範（公訴論告意旨 vs 辯護人辯護意旨）
- **公訴檢察官法庭論告示範**（檢察官如何從間接證據、經驗法則主張被告具有正犯之故意）。
- **辯護律師爭點辯護意旨示範**（辯護人如何精準引用罪疑唯輕與欠缺組織犯意，爭取變更法條或無罪）。

請以繁體中文專業法學語言，產出極具深度之分析報告！
"""
        res_md = self._call_model(prompt)
        return {
            "case_title": case_title,
            "subject": subject,
            "markdown_result": res_md
        }


# ==============================================================================
# 模組 3：一鍵 AI 裁判與長篇函釋核心要旨自動精鍊 (AI Legal Summarizer)
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
    }
]


class AILegalSummarizer:
    """
    一鍵 AI 裁判與長篇函釋核心要旨自動精鍊引擎 (對標法源 2025/2026 AI 摘要旗艦功能)
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
        prompt = f"""
你是一位台灣「司法院大法官書記處法官」兼「律師司法官高等考試權威名師」，精通裁判解構與長篇公報釋令精萃。
現在使用者輸入了一篇動輒數萬字之【{doc_type}】全文或核心摘錄，請立即執行極致精練、結構嚴謹之【AI 法源級核心要旨深度摘要】：

文書名稱/案號：【{title or '法學文書'}】
文書類型：【{doc_type}】
法學科目領域：【{subject}】

------------------------
【法學文書原始全文/摘錄】：
{doc_text.strip()[:10000]}

------------------------

請嚴格遵循法源法律網 AI 摘要旗艦規範，依序產出以下六大核心標題：

### 📌 一、基本案情與案件程序審級歷程
- **當事人背景與紛爭起因**：當事人身分、客觀爭端發生經過、行政處分作成或契約簽訂背景。
- **審級與訴訟/救濟歷程**：地院/訴願機關 ➔ 高院/高等行政法院 ➔ 最高法院/憲法法庭之審級轉折。

### ⚖️ 二、核心法律爭執焦點 (Legal Issues)
- 提煉 1~3 個最關鍵之實體法或程序法法律爭執點（以標題化明確呈現，例如：【爭點一】借名登記出名人擅自移轉是否構成無權處分？【爭點二】惡意第三人是否受善意受讓之保護？）。
- 爭執背後之法律規範漏洞或學說實務衝突所在。

### 🏛️ 三、裁判要旨與主文核心論理 (Holding & Ratio Decidendi)
- **主文結論**：本院最終諭知之主文結果（如：原判決廢棄發回、上訴駁回、法規定期失效、處分撤銷等）。
- **法院/部會核心裁判理由**：本院統一見解之立論基礎，包括文義解釋、體系解釋、歷史立法意旨與客觀目的衡量。

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
        return {
            "title": title,
            "doc_type": doc_type,
            "subject": subject,
            "markdown_result": res_md
        }
