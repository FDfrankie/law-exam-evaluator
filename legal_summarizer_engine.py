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
    import google.generativeai as legacy_genai
    USE_MODERN_GENAI = False

from config import get_gemini_api_key, DEFAULT_GEMINI_MODEL, get_gemini_models_to_try
from legal_query_engine import get_precedents_catalog, get_precedent_by_id, generate_judicial_search_urls

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
    }
]


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

請嚴格遵循標準專業規範，依序產出以下六大核心標題：

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
