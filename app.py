"""
司律手寫試卷評分、出題、考古題庫與高分擬答大師 - Web 圖形介面 (Streamlit)
支援功能：
1. 試卷評閱：多模態手寫試卷辨識與四大維度評分
2. 司律出題：一試選擇題（任意題數、答案速查表、逐題解析、實務字號）與二試實例題
3. 筆記出題：支援手寫/掃描筆記 AI 多模態視覺辨識與客製命題
4. 歷年真題庫：涵蓋台大法研所、台大轉學考、考選部司法官律師、司法特考等真題演練
5. 高分擬答：榜首級 IRAC 三段論法擬答生成
"""
import streamlit as st
import os
import sys
import json
import re
import io
import time
import urllib.parse
from pathlib import Path
from PIL import Image

from config import init_directories, GOOGLE_DRIVE_DATA_DIR, get_gemini_api_key, RAW_DATA_DIR, DATA_DIR, DEFAULT_GEMINI_MODEL, GEMINI_FALLBACK_MODELS
from doc_parser import parse_document, ocr_handwritten_images
from evaluator import LawExamEvaluator
from exam_generator import LawExamGenerator
try:
    from exam_bank_crawler import LawExamBankCrawler
except Exception:
    class LawExamBankCrawler:
        def __init__(self):
            import json
            from pathlib import Path
            try:
                base_dir = DATA_DIR
            except NameError:
                base_dir = "data"
            p = Path(base_dir) / "raw_exams" / "exams_catalog.json"
            self.catalog = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        def run_all(self, max_pages=2):
            pass

try:
    from legal_query_engine import (
        LegalIssueQueryEngine,
        search_local_precedents,
        get_all_precedent_options,
        get_precedent_by_id,
        get_precedents_catalog,
        generate_judicial_search_urls,
        search_precedents_advanced,
        COMMON_CASE_WORDS,
        COURTS_TAXONOMY,
        JUDICIAL_TIME_RANGES,
        get_precedent_history_chain,
        PRESET_JUDGEMENT_HISTORIES,
        extract_case_roc_year
    )
except ImportError:
    try:
        import legal_query_engine as _lqe
        LegalIssueQueryEngine = getattr(_lqe, "LegalIssueQueryEngine", None)
        search_local_precedents = getattr(_lqe, "search_local_precedents", None)
        get_all_precedent_options = getattr(_lqe, "get_all_precedent_options", lambda: [])
        get_precedent_by_id = getattr(_lqe, "get_precedent_by_id", lambda cid: None)
        get_precedents_catalog = getattr(_lqe, "get_precedents_catalog", lambda: [])
        generate_judicial_search_urls = getattr(_lqe, "generate_judicial_search_urls", lambda q, s="": {})
        search_precedents_advanced = getattr(_lqe, "search_precedents_advanced", lambda **kw: [])
        COMMON_CASE_WORDS = getattr(_lqe, "COMMON_CASE_WORDS", ["全部字別 (不限)", "台上大", "台上", "憲判"])
        COURTS_TAXONOMY = getattr(_lqe, "COURTS_TAXONOMY", {"全部法院 (全體司法體系)": []})
        JUDICIAL_TIME_RANGES = getattr(_lqe, "JUDICIAL_TIME_RANGES", ["全部時間 (不限年份)"])
        get_precedent_history_chain = getattr(_lqe, "get_precedent_history_chain", lambda cid: None)
        PRESET_JUDGEMENT_HISTORIES = getattr(_lqe, "PRESET_JUDGEMENT_HISTORIES", {})
        extract_case_roc_year = getattr(_lqe, "extract_case_roc_year", lambda item: 0)
    except Exception:
        LegalIssueQueryEngine = None
        search_local_precedents = None
        get_all_precedent_options = lambda: []
        get_precedent_by_id = lambda cid: None
        get_precedents_catalog = lambda: []
        generate_judicial_search_urls = lambda q, s="": {}
        search_precedents_advanced = lambda **kw: []
        COMMON_CASE_WORDS = ["全部字別 (不限)", "台上大", "台上", "憲判"]
        COURTS_TAXONOMY = {"全部法院 (全體司法體系)": []}
        JUDICIAL_TIME_RANGES = ["全部時間 (不限年份)"]
        get_precedent_history_chain = lambda cid: None
        PRESET_JUDGEMENT_HISTORIES = {}
        extract_case_roc_year = lambda item: 0
from six_codes_engine import (
    SIX_CODES_TAXONOMY,
    get_laws_in_branch,
    search_articles,
    get_article_annotations,
    SixCodesDeepAnnotator,
    get_law_legislative_history,
    get_article_legislative_details,
    synthesize_article_legislative_details,
    clear_six_codes_cache
)
from six_codes_updater import update_law_amendments, load_amendments_history
from community_archive_engine import (
    archive_uploaded_question,
    archive_uploaded_note,
    load_community_questions,
    load_community_notes,
    search_community_questions,
    search_community_notes
)
from admin_rulings_engine import (
    get_law_key_regulations,
    get_regulation_full_details,
    get_admin_rulings_for_article,
    get_all_administrative_rulings,
    crawl_and_synthesize_admin_rulings,
    get_chorder_regulations_map,
    LANDMARK_ADMIN_RULINGS,
    load_crawled_admin_rulings
)
try:
    from legal_summarizer_engine import (
        BooleanQueryParser,
        evaluate_boolean_query,
        AILegalSummarizer,
        BUILTIN_LANDMARK_DOCS,
        find_legal_doc_by_citation,
        lookup_case_by_abbreviation,
        parse_case_abbreviation_query,
        construct_standard_citation_from_parsed
    )
except ImportError:
    try:
        import legal_summarizer_engine as _lbe
        BooleanQueryParser = getattr(_lbe, "BooleanQueryParser", None)
        evaluate_boolean_query = getattr(_lbe, "evaluate_boolean_query", lambda q, t: True)
        AILegalSummarizer = getattr(_lbe, "AILegalSummarizer", None)
        BUILTIN_LANDMARK_DOCS = getattr(_lbe, "BUILTIN_LANDMARK_DOCS", [])
        find_legal_doc_by_citation = getattr(_lbe, "find_legal_doc_by_citation", lambda c: None)
        lookup_case_by_abbreviation = getattr(_lbe, "lookup_case_by_abbreviation", lambda q: {"matched": False})
        parse_case_abbreviation_query = getattr(_lbe, "parse_case_abbreviation_query", lambda q: {})
        construct_standard_citation_from_parsed = getattr(_lbe, "construct_standard_citation_from_parsed", lambda i: "")
    except Exception:
        class BooleanQueryParser:
            @classmethod
            def is_boolean_query(cls, q): return False
        def evaluate_boolean_query(q, t): return True
        AILegalSummarizer = None
        BUILTIN_LANDMARK_DOCS = []
        find_legal_doc_by_citation = lambda c: None
        lookup_case_by_abbreviation = lambda q: {"matched": False}
        parse_case_abbreviation_query = lambda q: {}
        construct_standard_citation_from_parsed = lambda i: ""

try:
    from legal_qa_engine import (
        LegalQAEngine,
        LEGAL_CONSULTATION_DOMAINS,
        USER_STANDPOINTS,
        OUTPUT_MODES,
        QUERY_TYPES,
        calculate_vehicle_depreciation,
        calculate_severance_pay,
        calculate_marital_property_division,
        calculate_inheritance_shares,
        calculate_statutory_interest
    )
except Exception:
    class LegalQAEngine:
        def answer_legal_question(self, **kwargs):
            return {"success": True, "content": "法學問答引擎初始化中..."}
        def generate_legal_notice(self, **kwargs):
            return "存證信函生成中..."
        def generate_mediation_summary(self, **kwargs):
            return "調解聲請書生成中..."
        def detect_question_domain(self, text):
            return "🌟 自動偵測 (全領域綜合剖析)"
        def detect_query_intent(self, text):
            return "🌟 智慧綜合判斷 (全自動意圖辨識)"
    LEGAL_CONSULTATION_DOMAINS = ["🌟 自動偵測 (全領域綜合剖析)"]
    USER_STANDPOINTS = ["⚖️ 客觀中立立場 (全面衡平評估法理與雙方勝算)"]
    OUTPUT_MODES = ["📑 完整專業法律諮詢意見書 (定性・條文・權利・證據・流程・時效)"]
    QUERY_TYPES = ["🌟 智慧綜合判斷 (全自動意圖辨識)"]
    def calculate_vehicle_depreciation(**kwargs): return {}
    def calculate_severance_pay(**kwargs): return {}
    def calculate_marital_property_division(**kwargs): return {}
    def calculate_inheritance_shares(**kwargs): return {}
    def calculate_statutory_interest(**kwargs): return {}

try:
    from core_issues_taxonomy import (
        get_taxonomy_chapters_for_subject,
        get_curated_issues_by_chapter,
        get_total_curated_issues_count
    )
except Exception:
    def get_taxonomy_chapters_for_subject(s=""):
        return ["🌟 全部體系章節大庫 (跨領域綜合檢索)"]
    def get_curated_issues_by_chapter(c="", s=""):
        return {}
    def get_total_curated_issues_count():
        return 0

# 設定頁面配置
st.set_page_config(
    page_title="司律考試 AI 評分與命題大師",
    page_icon="⚖️",
    layout="wide"
)

init_directories()

try:
    from ingest_user_notes_to_sft import (
        get_google_drive_notes_list,
        read_note_text,
        sync_all_drive_notes_to_samsung_notes,
        distill_single_note_file
    )
except ImportError:
    try:
        import ingest_user_notes_to_sft as _iun
        get_google_drive_notes_list = getattr(_iun, "get_google_drive_notes_list", lambda: [])
        read_note_text = getattr(_iun, "read_note_text", lambda p, **kw: "")
        sync_all_drive_notes_to_samsung_notes = getattr(_iun, "sync_all_drive_notes_to_samsung_notes", lambda: 0)
        distill_single_note_file = getattr(_iun, "distill_single_note_file", lambda p, **kw: [])
    except Exception:
        get_google_drive_notes_list = lambda: []
        read_note_text = lambda p, **kw: ""
        sync_all_drive_notes_to_samsung_notes = lambda: 0
        distill_single_note_file = lambda p, **kw: []

@st.cache_data(ttl=300)
def load_all_drive_notes():
    try:
        return get_google_drive_notes_list()
    except Exception:
        return []

drive_notes = load_all_drive_notes()

# ==============================================================================
# 系統導航模式常數（徹底避免索引位移錯位）
# ==============================================================================
MODE_HOME = "🏠 首頁與系統導覽 (功能總覽・隱私權政策・法律聲明)"
MODE_EVAL = "📝 試卷評分與手寫辨識 (手寫/PDF/Word)"
MODE_GEN = "🎯 司律模擬出題 (一試/二試 & 手寫筆記客製命題)"
MODE_BANK = "📚 歷年真題庫檢索與模擬演練 (法研所 / 轉學考 / 司法官律師 / 司法特考)"
MODE_ANS = "📖 高分權威擬答生成"
MODE_SEARCH = "🔍 統一法學檢索樞紐與 AI 判決研析 (布林檢索・多庫矩陣・爭點大典)"
MODE_QA = "💬 專屬法學全能問答樞紐 (萬能檢索・條文定位・爭點論辯・金額精算)"
MODE_SUMMARIZER = "📑 一鍵 AI 裁判與長篇函釋要旨自動精鍊 (AI 判解精鍊旗艦)"
MODE_SIX_CODES = "⚖️ 智慧六法與條文判解綜合標註 (法條・沿革・爭點・筆記)"
MODE_SFT = "📥 手寫筆記蒸餾與 SFT 模型微調大庫"

def reset_stage1_exam_state():
    """徹底重設一試選擇題之作答紀錄、批改報告狀態與所有 Radio 按鍵暫存，避免上次答案污染新題目"""
    st.session_state["stage1_graded"] = False
    st.session_state.pop("stage1_user_answers", None)
    st.session_state.pop("cb_peek_stage1_solution", None)
    for k in list(st.session_state.keys()):
        if k.startswith("user_choice_"):
            st.session_state.pop(k, None)

@st.cache_data(ttl=3600)
def load_all_existing_stage1_mcqs() -> list:
    """
    全量載入既有一試全真題庫：
    1. admin_law_300_mcqs.json (行政法 300 題全量題庫)
    2. data/training_data/law_exam_exams_and_mcq_sft.jsonl (SFT 一試題庫)
    3. 內建民法、刑法、憲法、民事訴訟法、刑事訴訟法、商事法全真精選選擇題
    """
    all_questions = []
    seen_hashes = set()

    # 1. 行政法 300 題
    bank_paths = [
        Path(RAW_DATA_DIR) / "admin_law_300_mcqs.json",
        Path(__file__).resolve().parent / "data" / "raw_exams" / "admin_law_300_mcqs.json",
        Path(__file__).resolve().parent.parent / "raw_exams" / "admin_law_300_mcqs.json"
    ]
    for bp in bank_paths:
        if bp.exists():
            try:
                data = json.loads(bp.read_text(encoding="utf-8"))
                for q in data.get("questions", []):
                    q_copy = dict(q)
                    q_copy["subject"] = "行政法"
                    q_copy["major_domain"] = "憲法與行政法"
                    h = f"{q_copy.get('question', '')[:30]}_{q_copy.get('options', {}).get('A', '')[:10]}"
                    if h not in seen_hashes:
                        all_questions.append(q_copy)
                        seen_hashes.add(h)
                break
            except Exception:
                pass

    # 2. 跨科全真模擬題庫 (民法、刑法、憲法、民事訴訟法、刑事訴訟法、商事法 86 題)
    multi_bank_paths = [
        Path(RAW_DATA_DIR) / "stage1_multi_subject_mcq_bank.json",
        Path(__file__).resolve().parent / "data" / "raw_exams" / "stage1_multi_subject_mcq_bank.json",
        Path(__file__).resolve().parent.parent / "raw_exams" / "stage1_multi_subject_mcq_bank.json"
    ]
    for mbp in multi_bank_paths:
        if mbp.exists():
            try:
                mdata = json.loads(mbp.read_text(encoding="utf-8"))
                for q in mdata:
                    q_copy = dict(q)
                    h = f"{q_copy.get('question', '')[:30]}_{q_copy.get('options', {}).get('A', '')[:10]}"
                    if h not in seen_hashes:
                        all_questions.append(q_copy)
                        seen_hashes.add(h)
                break
            except Exception:
                pass

    # 3. SFT 題庫
    sft_paths = [
        Path(DATA_DIR) / "training_data" / "law_exam_exams_and_mcq_sft.jsonl",
        Path(__file__).resolve().parent / "data" / "training_data" / "law_exam_exams_and_mcq_sft.jsonl"
    ]
    for sp in sft_paths:
        if sp.exists():
            try:
                with open(sp, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip(): continue
                        item = json.loads(line)
                        raw_in = item.get("input", "")
                        raw_out = item.get("output", "")
                        if "(A)" in raw_in and ("【正確解答】" in raw_out or "A" in raw_out):
                            sub = item.get("subject", "綜合領域")
                            opts = {}
                            for opt_char in ["A", "B", "C", "D"]:
                                m_opt = re.search(rf'\({opt_char}\)\s*([^\n\(]+)', raw_in)
                                if m_opt:
                                    opts[opt_char] = m_opt.group(1).strip()
                            m_ans = re.search(r'【正確解答】[：:]\s*\(?([A-D])\)?', raw_out)
                            ans_char = m_ans.group(1) if m_ans else "A"
                            q_text_m = re.search(r'【案例事實與題目】[：:]\s*(.*?)(?=\(A\)|$)', raw_in, re.DOTALL)
                            q_text = q_text_m.group(1).strip() if q_text_m else raw_in[:200]
                            if len(opts) == 4:
                                h = f"{q_text[:30]}_{opts.get('A', '')[:10]}"
                                if h not in seen_hashes:
                                    domain = "民法與民事訴訟法" if "民" in sub else (
                                        "刑法與刑事訴訟法" if "刑" in sub else (
                                            "憲法與行政法" if ("憲" in sub or "行政" in sub) else "商事法與綜合領域"
                                        )
                                    )
                                    all_questions.append({
                                        "question_no": len(all_questions) + 1,
                                        "subject": sub,
                                        "major_domain": domain,
                                        "category": item.get("category", "法學核心爭點"),
                                        "question": q_text,
                                        "options": opts,
                                        "answer": ans_char,
                                        "explanation": raw_out
                                    })
                                    seen_hashes.add(h)
                break
            except Exception:
                pass

    # 3. 內建跨科全真精選題庫
    curated_mcqs = [
        {
            "question_no": len(all_questions) + 1,
            "subject": "民法",
            "major_domain": "民法與民事訴訟法",
            "category": "物權與借名登記處分",
            "question": "甲將其所有之A房地借名登記於乙名下，約定乙未得甲同意不得處分。後乙未經同意將A房地出賣並移轉登記於知情之惡意第三人丙。依最高法院108年度台上大字第1719號民事大法庭裁定見解，下列敘述何者最正確？",
            "options": {
                "A": "乙之移轉行為屬無權處分，因丙為惡意，故效力未定",
                "B": "乙本於物權登記名義人之處分權能而為移轉，無論丙善意或惡意均屬有權處分，丙有效取得所有權",
                "C": "甲得依民法第767條第1項前段規定，直接請求丙塗銷登記",
                "D": "乙之處分行為效力未定，俟甲承認後始生效力"
            },
            "answer": "B",
            "explanation": "【解析】：依最高法院108年度台上大字第1719號裁定，出名人擅自處分借名登記不動產，無論第三人善意或惡意均為有權處分，第三人有效取得所有權。故選 (B)。"
        },
        {
            "question_no": len(all_questions) + 2,
            "subject": "刑法",
            "major_domain": "刑法與刑事訴訟法",
            "category": "毒品販賣既遂與未遂",
            "question": "甲意圖營利，與便衣員警乙談妥以2萬元購買海洛因5公克，約定於捷運站交付。甲攜毒品赴約，自口袋取出尚未交給乙且未收受價金即遭逮捕。依最高法院108年度台上大字第3594號刑事大法庭裁定，甲應如何論處？",
            "options": {
                "A": "甲成立販賣第一級毒品既遂罪，因買賣意思合致即既遂",
                "B": "甲成立販賣第一級毒品未遂罪，因尚未交付毒品且未取得價金",
                "C": "甲不成立犯罪，因員警係陷害教唆",
                "D": "甲僅成立意圖販賣而持有第一級毒品罪"
            },
            "answer": "B",
            "explanation": "【解析】：最高法院108年度台上大字第3594號刑事大法庭裁定定錨：販賣毒品必須已交付毒品或收受價金移轉占有始成立既遂；僅達成買賣合意尚未交付者僅成立未遂。故選 (B)。"
        },
        {
            "question_no": len(all_questions) + 3,
            "subject": "憲法",
            "major_domain": "憲法與行政法",
            "category": "正當法律程序與身體權",
            "question": "警察攔停涉嫌酒駕之甲，甲拒絕吐氣測試，警遂依道交條例強制將甲移送醫院抽血。依憲法法庭111年憲判字第1號判決意旨，下列敘述何者最正確？",
            "options": {
                "A": "警察強制抽血完全合憲，因公共交通安全法益優先",
                "B": "強制抽血干預人身自由、身體權與隱私權，欠缺事前令狀審查或事後法定救濟程序，牴觸憲法正當法律程序原則",
                "C": "只要經警察分局長書面許可即可強制抽血",
                "D": "強制抽血屬非侵入性處分，毋庸受令狀原則拘束"
            },
            "answer": "B",
            "explanation": "【解析】：111年憲判字第1號判決宣告：道交條例授權警察逕行強制移送抽血檢測規定牴觸憲法第8條、第22條，違反正當法律程序與令狀原則。故選 (B)。"
        },
        {
            "question_no": len(all_questions) + 4,
            "subject": "民事訴訟法",
            "major_domain": "民法與民事訴訟法",
            "category": "爭點效與既判力",
            "question": "甲請求乙給付價金100萬元，法院審理後於理由認定契約有效，但因消滅時效完成而駁回甲之訴確定。嗣後甲請求乙受領標的物，乙再度主張契約無效。下列敘述何者最正確？",
            "options": {
                "A": "前訴理由中契約有效之判斷具備民事訴訟法第400條第1項之既判力",
                "B": "前案理由中之重大爭點判斷經兩造實質攻防，依爭點效理論，當事人不得為相反主張，法院亦不得為矛盾判斷",
                "C": "判決理由中之判斷絕對不生拘束力，乙於後訴可恣意重啟爭辯",
                "D": "時效抗辯之成立表示主文實質確定契約無效"
            },
            "answer": "B",
            "explanation": "【解析】：依最高法院實務通說，理由中判斷雖無既判力，但本於誠信原則適用「爭點效」，兩造充分言詞辯論之主要爭點於後訴具拘束力。故選 (B)。"
        },
        {
            "question_no": len(all_questions) + 5,
            "subject": "刑事訴訟法",
            "major_domain": "刑法與刑事訴訟法",
            "category": "違法取證與證據排除法則",
            "question": "警察無搜索票違法進入甲宅扣得海洛因磚。檢察官起訴提出該扣案毒品為證。依刑事訴訟法第158條之4及實務定錨見解，法院應如何處理？",
            "options": {
                "A": "違法搜索扣押之物證絕對不具證據能力，一律排除",
                "B": "物證具客觀不變性，程序違法不影響證據能力",
                "C": "法院應審酌人權保障與公共利益均衡維護，綜合權衡八大要素決定該物證有無證據能力",
                "D": "只要甲事後自白，違法搜索瑕疵即告補正"
            },
            "answer": "C",
            "explanation": "【解析】：依刑訴第158條之4及93台上664判例，公務員違法取證之證據能力應本於利益均衡原則綜合權衡八大要素決定。故選 (C)。"
        },
        {
            "question_no": len(all_questions) + 6,
            "subject": "商事法",
            "major_domain": "商事法與綜合領域",
            "category": "保險法告知義務與除斥期間",
            "question": "甲投保人壽保險隱匿罹癌事實，承保逾2年後因癌身故，受益人請求理賠。保險人主張依民法第92條撤銷投保意思表示拒賠。依最高法院108年度台上大字第897號裁定，下列敘述何者最正確？",
            "options": {
                "A": "保險人仍得於民法1年除斥期間內撤銷契約",
                "B": "保險法第64條第3項之2年除斥期間具排他性，逾2年後保險人不得再依民法第92條撤銷意思表示",
                "C": "因甲出於詐欺惡意，民法第92條撤銷權無除斥期間之適用",
                "D": "保險契約自始因詐欺而當然無效"
            },
            "answer": "B",
            "explanation": "【解析】：108台上大897裁定終局定錨：保險人解除權應專依保險法第64條第3項，逾2年除斥期間後不得再依民法第92條撤銷。故選 (B)。"
        }
    ]

    for cm in curated_mcqs:
        h = f"{cm['question'][:30]}_{cm['options']['A'][:10]}"
        if h not in seen_hashes:
            all_questions.append(cm)
            seen_hashes.add(h)

    for idx, q in enumerate(all_questions, 1):
        q["global_index"] = idx

    return all_questions



# 司律考科學門體系完整分類表（涵蓋一試、二試、法研所、司法特考全領域 38+ 考科）
LAW_DOMAIN_TAXONOMY = {
    "🌟 全部學門 (跨領域綜合檢索與全考科自選)": [
        "全部科目 (跨學門全領域綜合檢索)",
        "民法 (總則/債編/物權/身分全編)",
        "民法總則 (權利主體/客體/法律行為/時效)",
        "民法債編 (契約總論/個別契約/侵權/不當得利)",
        "民法物權編 (所有權/抵押權/用益物權/占有)",
        "民法親屬與繼承編 (剩餘財產/代位繼承/特留分)",
        "民事訴訟法 (訴訟主體/訴訟標的/既判力/舉證責任)",
        "家事事件法 (婚姻事件/親子關係/保全與暫時處分)",
        "強制執行法 (金錢債權/拍賣程序/除去租賃/參與分配)",
        "仲裁法與非訟事件法",
        "刑法 (總則與分則全編)",
        "刑法總則 (構成要件/違法性/未遂犯/共犯/競合)",
        "刑法分則 (個人法益/財產犯罪/國家社會法益)",
        "特別刑法 (貪污治罪條例/洗錢防制法/毒品槍砲條例)",
        "刑事訴訟法 (強制處分/搜索羈押/科技偵查/防禦權)",
        "刑事訴訟法 (證據法則/傳聞法則/證據排除/自白)",
        "刑事訴訟法 (通常審判/上訴審/再審與非常上訴)",
        "國民法官法 (國民參與審判/卷證不併送/終局評議)",
        "憲法與人權保障 (基本權違憲審查/雙軌雙階理論)",
        "憲法訴訟法 (憲法法庭判決/裁判憲法審查/暫時處分)",
        "行政法總論 (法律保留/信賴保護/裁量瑕疵與判斷餘地)",
        "行政程序法 (行政處分附款/行政契約/法規命令)",
        "行政罰法與行政執行法 (一事不二罰/管收與即時強制)",
        "行政爭訟法 (訴願法/撤銷訴訟/課予義務訴訟/一般給付)",
        "國家賠償法與損失補償 (怠於執行職務/公共設施設置欠缺)",
        "公司法 (董事注意義務/忠實義務/股東會決議瑕疵/關係企業)",
        "證券交易法 (證券詐欺/財報不實/內線交易/操縱股價)",
        "保險法 (告知義務/複保險/保險代位/人身保險防範道德危險)",
        "票據法 (票據無因性/人之抗辯/惡意取得/空白授權)",
        "海商法與海洋法 (海上運送/船舶碰撞/共同海損/海難救助)",
        "金融消費者保護法與銀行法",
        "智慧財產權法 (專利法/商標法/著作權法/侵害救濟)",
        "營業秘密法 (合理保密措施/秘密性/惡意侵害救濟)",
        "勞動基準法與勞動契約 (勞動契約/解僱保護/離職競業禁止)",
        "集體勞工法與勞資爭議 (工會法/團體協約法/爭議行為合法性)",
        "社會保障法與社會保險法 (勞工保險/職業災害補償與保險)",
        "財稅法與納稅者權利保護 (租稅法定主義/實質課稅/推計課稅)",
        "公平交易法 (獨占/結合申報/聯合行為/不公平競爭行為)",
        "國際私法 (涉外民事法律適用法/準據法之決定/公序良俗)",
        "國際公法 (條約法/國家豁免/國際人權法/領土與管轄)",
        "土地法規與土地登記 (土地法第34條之1優先購買權/公寓大廈)",
        "其他自訂學門"
    ],
    "📜 民事實體法學門": [
        "民法 (總則/債編/物權/身分全編)",
        "民法總則 (權利主體/客體/法律行為/時效)",
        "民法債編 (契約總論/個別契約/侵權/不當得利)",
        "民法物權編 (所有權/抵押權/用益物權/占有)",
        "民法親屬與繼承編 (剩餘財產/代位繼承/特留分)",
        "消費者保護法 (定型化契約/商品責任/消保訴訟)",
        "土地法規與土地登記 (土地法第34條之1優先購買權/公寓大廈)"
    ],
    "⚖️ 民事程序法學門": [
        "民事訴訟法 (訴訟主體/訴訟標的/既判力/舉證責任)",
        "民事訴訟法 (通常審判/簡易程序/上訴審救濟)",
        "家事事件法 (婚姻事件/親子關係/保全與暫時處分)",
        "強制執行法 (金錢債權/拍賣程序/除去租賃/參與分配)",
        "仲裁法與非訟事件法"
    ],
    "⚔️ 刑事實體與程序法學門": [
        "刑法 (總則與分則全編)",
        "刑法總則 (構成要件/違法性/未遂犯/共犯/競合)",
        "刑法分則 (個人法益/財產犯罪/國家社會法益)",
        "特別刑法 (貪污治罪條例/洗錢防制法/毒品槍砲條例)",
        "刑事訴訟法 (強制處分/搜索羈押/科技偵查/防禦權)",
        "刑事訴訟法 (證據法則/傳聞法則/證據排除/自白)",
        "刑事訴訟法 (通常審判/上訴審/再審與非常上訴)",
        "國民法官法 (國民參與審判/卷證不併送/終局評議)"
    ],
    "🏛️ 公法與憲政行政法學門": [
        "憲法與人權保障 (基本權違憲審查/雙軌雙階理論)",
        "憲法訴訟法 (憲法法庭判決/裁判憲法審查/暫時處分)",
        "行政法總論 (法律保留/信賴保護/裁量瑕疵與判斷餘地)",
        "行政程序法 (行政處分附款/行政契約/法規命令)",
        "行政罰法與行政執行法 (一事不二罰/管收與即時強制)",
        "行政爭訟法 (訴願法/撤銷訴訟/課予義務訴訟/一般給付)",
        "國家賠償法與損失補償 (怠於執行職務/公共設施設置欠缺)"
    ],
    "💼 商事法與財經法學門": [
        "公司法 (董事注意義務/忠實義務/股東會決議瑕疵/關係企業)",
        "證券交易法 (證券詐欺/財報不實/內線交易/操縱股價)",
        "保險法 (告知義務/複保險/保險代位/人身保險防範道德危險)",
        "票據法 (票據無因性/人之抗辯/惡意取得/空白授權)",
        "海商法與海洋法 (海上運送/船舶碰撞/共同海損/海難救助)",
        "金融消費者保護法與銀行法"
    ],
    "🌐 專業法規與二試選試學門": [
        "智慧財產權法 (專利法/商標法/著作權法/侵害救濟)",
        "營業秘密法 (合理保密措施/秘密性/惡意侵害救濟)",
        "勞動基準法與勞動契約 (勞動契約/解僱保護/離職競業禁止)",
        "集體勞工法與勞資爭議 (工會法/團體協約法/爭議行為合法性)",
        "社會保障法與社會保險法 (勞工保險/職業災害補償與保險)",
        "財稅法與納稅者權利保護 (租稅法定主義/實質課稅/推計課稅)",
        "公平交易法 (獨占/結合申報/聯合行為/不公平競爭行為)",
        "國際私法 (涉外民事法律適用法/準據法之決定/公序良俗)",
        "國際公法 (條約法/國家豁免/國際人權法/領土與管轄)",
        "其他自訂學門"
    ]
}

# 司律高頻核心爭點與熱門考點分類表
CORE_ISSUES_TAXONOMY = {
    "民法": {
        "【民法總則・處分權限】借名登記契約性質與出名人無權處分效力（108台上大字1719）": "借名登記契約性質、出名人處分效力與買受人善惡意受讓（108台上大字1719大法庭）",
        "【民法總則・意思表示】意思表示錯誤（第88條）與受詐欺撤銷（第92條）之競合與選擇": "意思表示錯誤要件、無過失要件與受詐欺意思表示撤銷之競合與權利行使",
        "【民法總則・消滅時效】時效完成之抗辯權與民法第144條第2項之自然債務": "消滅時效抗辯權性質、時效完成後之承認、時效抗辯後債權抵銷之容許性",
        "【民法總則・行為能力】限制行為能力人無權處分與第801條善意受讓之適用": "限制行為能力人無權處分他人之物，第三人得否主張善意受讓所有權",
        "【民法債編・不完全給付】物之瑕疵擔保責任與不完全給付之競合（77年第7次決議）": "買受人物之瑕疵擔保與不完全給付加害給付之請求權競合要件與消滅時效",
        "【民法債編・租賃抵押】買賣不破租賃（第425條）於抵押權設定後租賃之除去": "租賃契約成立於抵押權設定後，拍賣程序中執行法院除去租賃權之法定要件",
        "【民法債編・侵權責任】侵權行為第184條第1項前段、後段與純粹經濟損失保護": "民法第184條各項保護客體分際、純粹經濟上損失之保護要件與過失相抵",
        "【民法債編・不當得利】非給付型不當得利之「權益歸屬說」與違法轉租利得": "非給付型不當得利之成立要件、權益歸屬侵害與所受利益之計算標準",
        "【民法債編・違約定金】違約定金之性質與民法第252條違約金酌減之類推適用": "損害賠償預額性違約金與懲罰性違約金之區辨，違約定金過高之酌減",
        "【民法物權・抵押權】抵押權之物上代位性與查封扣押時點之關係": "抵押權物上代位性之行使要件、保險金或補償金扣押時點與實行程序",
        "【民法物權・法定地上權】民法第876條法定地上權之成立要件與房屋所有權變動": "土地與房屋同屬一人後設定抵押權、嗣後轉讓時法定地上權之成立判斷",
        "【民法物權・共有物處分】土地法第34條之1共有人處分與他共有人優先購買權": "多數決處分共有物之程序、通知義務與他共有人優先購買權之債權效力",
        "【民法身分・剩餘財產】剩餘財產分配請求權（第1030條之1）扣除債務與追加": "法定財產制消滅時剩餘財產之計算、慰撫金/贈與物之扣除與追加計算",
        "【民法身分・代位繼承】代位繼承之性質（固有權說）與被代位人欠缺繼承權": "代位繼承之法律性質、代位人得否繼承被代位人喪失繼承權時之應繼分",
        "【民法身分・特留分】特留分扣減權之性質（形成權說）與消滅時效": "特留分扣減之標的、先扣遺贈後扣應繼分之次序與扣減權行使"
    },
    "民事訴訟法": {
        "【程序主體】形式當事人與實質當事人、法定訴訟擔當之主觀效力": "訴訟擔當之類型、當事人適格之判斷與確定判決對實質權利人之既判力主觀範圍",
        "【訴訟標的】舊訴訟標的理論 vs 新訴訟標的理論之實戰辨析": "訴之聲明與原因事實之特定、實體法請求權競合於判決既判力客觀範圍之遮斷",
        "【既判力】既判力客觀範圍、遮斷效（失權效）與爭點效之適用": "既判力客觀範圍限於主文、理由中實質爭點判斷之爭點效要件與前訴遮斷效",
        "【重複起訴】民事訴訟法第253條重複起訴禁止於反訴與後訴之判斷": "同一事件之判斷標準（當事人、訴訟標的、訴之聲明相同或相反）",
        "【舉證責任】舉證責任分配法則（規範說）與危險領域說、消保事件轉換": "權利發生、障礙、消滅事實之舉證責任分配與醫療過失舉證責任減輕",
        "【抗辯爭點】抵銷抗辯之既判力（第400條第2項）與抵銷順位之確定": "被告主張抵銷之成立要件、反對抗辯與抵銷額度之既判力發生時點"
    },
    "家事事件法": {
        "【程序法理】家事事件職權探知主義與處分權主義之交錯適用（第10條）": "家事甲乙丙丁類事件之程序法理交錯、職權調查之範圍與當事人處分自由界限",
        "【合併審理】婚姻無效或撤銷訴訟合併請求損害賠償與剩餘財產分配（第41條）": "家事訴訟事件與家事非訟事件之合併審查、管轄法院與審理程序之調和",
        "【保全程序】暫時處分之核發要件、審理程序與抗告救濟（第85條）": "本案給付前命給付生活費、未成年子女親權暫行處分之急速危險要件與救濟"
    },
    "強制執行法": {
        "【執行名義】公證書給付金錢執行名義之效力與債務人異議之訴（第14條）": "無實質確定力執行名義之救濟、異議事由發生時點與實體權利不存在之審查",
        "【除去負擔】抵押權人聲請拍賣抵押物，執行法院除去租賃權（第98條類推）": "抵押權設定後成立之租賃影響拍賣抵押物受償時，執行法院職權除去之法定程序",
        "【參與分配】參與分配之合法時點與無執行名義債權人參與分配之限制（第32條、第34條）": "優先受償債權人與普通債權人參與分配時點截止、逾期參與分配之法律效果"
    },
    "刑法": {
        "【刑法總則・可罰性】原因自由行為之處罰基礎與主客觀要件（第19條第3項）": "原因自由行為之例外模式與構成要件模式、故意與過失原因自由行為之論處",
        "【刑法總則・未遂犯】中止犯「出於己意」與自動性判斷（Frank公式與客觀悔悟）": "障礙未遂與中止未遂之界限、放棄犯行與積極防止結果發生之真摯努力",
        "【刑法總則・正犯共犯】共同正犯脫離與共犯關係解消（著手前後之區分）": "著手前後脫離之認定標準、物理與心理因果關係之切斷與既遂歸責",
        "【刑法總則・不作為犯】不作為犯之保證人地位與假設因果關係之認定": "作為義務之來源（危險前行為、特定保護關係）、假設因果關係之高度或然性",
        "【刑法分則・財產法益】詐欺罪「陷於錯誤」與民事債務不履行詐欺之界限": "民事債信詐欺與刑事詐欺之區別、傳遞不實資訊與處分財產之因果關係",
        "【刑法分則・財產法益】強盜罪「至使不能抗拒」與恐嚇取財罪之區辨": "客觀至使不能抗拒標準、抑制被害人意思決定自由之程度比較",
        "【刑法分則・加重詐欺】加重詐欺罪（第339條之4）三人以上與冒用公務員名義": "詐欺車手、收簿手與機房成員之共同正犯定性與加重要件該當性",
        "【刑法分則・文書法益】使公務員登載不實罪（第214條）實質審查與形式審查": "公務員實質審查權限之界限（例如戶政、地政、公司設立登記）",
        "【刑法分則・侵害財產】業務侵占罪與背信罪之競合與補充關係": "身分犯侵占持有他人之物與違反善良管理人任務損害本人利益之法條競合"
    },
    "刑事訴訟法": {
        "【強制處分】羈押要件、卷證獲知權與防禦權保障（釋字737、憲判字）": "偵查中羈押審查程序之卷證獲知權、比例原則與替代羈押處分",
        "【強制處分】搜索扣押令狀原則之例外（附帶搜索、急迫搜索、同意搜索）": "附帶搜索之範圍（身體及隨手可及處）、同意搜索之自願性審查",
        "【證據法則】傳聞法則（第159條）之適用範圍與傳聞例外之嚴格審查": "審判外陳述之傳聞定性、第159條之1至之5法定傳聞例外之操作",
        "【證據法則】違法取證之證據排除法則（第158條之4）利益權衡機制": "違反法定程序取得證據之權衡法則（人權侵害程度、違背情節、急迫性）",
        "【審判程序】公訴不可分原則與法院得否變更起訴法條（第300條）": "起訴效力所及範圍、犯罪事實之同一性判斷與罪名變更前之防禦權告知"
    },
    "國民法官法": {
        "【國民法官・選任程序】候選國民法官之消極資格審查與無理由附理由拒恐程序": "候選人隨機抽選、不公正偏頗之排除與檢辯雙方附理由及無理由拒恐之行使",
        "【國民法官・卷證不併送】起訴狀一本主義之落實與預斷排除原則之維護": "檢察官起訴不得將卷宗證物一併送交法院、預斷排除與爭點整理程序",
        "【國民法官・評議規則】終局評議之有罪表決門檻（三分之二以上且包含法官國民法官各一票）": "有罪認定之絕對多數決門檻、量刑之表決順序與不同意見處理機制"
    },
    "行政法": {
        "【核心法理】層級化法律保留原則（釋字第443號）與授權明確性要求": "干涉行政與給付行政之法律保留密度、法規命令授權明確性要件",
        "【公私法性質】公私法區分標準（二階理論、修正規律說）與政府採購爭議": "追繳押標金之定性、公立大學教師聘任契約之法律性質與爭訟途徑",
        "【行政行為】行政處分之附款要件（期限、條件、負擔）與獨立救濟": "附款之容許性與合法性、負擔之獨立撤銷訴訟要件",
        "【行政行為】行政契約與私法契約之辨識、公法給付約定之違約金效力": "行政契約之識別標準（契約標的說、目的說）、行政程序法第149條準用",
        "【行政裁量】行政裁量瑕疵（逾越、濫用、怠惰）與裁量收縮至零": "裁量瑕疵之司法審查密度、不確定法律概念與判斷餘地之審查界限",
        "【撤銷廢止】違法處分撤銷與信賴保護原則（行政程序法第117~120條）": "信賴不值得保護之消極要件、信賴利益補償與授益處分廢止（第123條）",
        "【行政救濟】課予義務訴訟與一般給付訴訟之訴訟類型選定": "拒絕處分訴訟與怠為處分訴訟之差別、訴願前置主義之遵守",
        "【行政救濟】行政訴訟停止執行之發動要件與難以回復損害之審查": "行政訴訟法第116條原處分合法性顯有疑義與重大公共利益之權衡",
        "【國家責任】國家賠償法第2條第2項怠於執行職務與公有公共設施責任": "公務員裁量收縮之怠於行使職務國賠責任、設施瑕疵之無過失責任"
    },
    "憲法": {
        "【人身自由】憲法第8條正當法律程序與法官保留原則（釋字384、憲判字）": "限制人身自由處分之法官保留、正當法律程序之實質保障",
        "【言論自由】事前限制之禁止與雙軌理論（內容管制與非內容管制）": "政治性言論與商業性言論之審查基準、違憲審查之比例原則嚴格審查",
        "【隱私權利】資訊自主權與科技偵查、GPS追蹤之憲法審查（憲判字）": "憲法第22條隱私權核心、強制採取DNA與科技偵查之法律保留與法官保留",
        "【權力分立】總統職權、行政院對立法院負責與責任政治運作": "行政院院長之任免、覆議制度之運作與行政立法制衡之界限",
        "【權力分立】國會調查權之邊界與政府官員備詢之義務範圍": "立法院調查權之權限邊界、司法特權與行政特權之保護",
        "【憲法訴訟】裁判憲法審查制度之受理要件與法規範審查分際": "憲法訴訟法第59條人民聲請裁判憲法審查之要件與基本權侵害之具體性"
    },
    "憲法訴訟法": {
        "【裁判憲審】裁判憲法審查之受理要件與基本權侵害重大性（第59條）": "具體裁判適用法規範牴觸憲法、裁判本身侵害憲法基本權之審查密度",
        "【暫時處分】憲法法庭暫時處分之核發要件與急速急迫危險防範（第43條）": "避免不可回復之重大損害、急迫必要性審查與利益衡量",
        "【判決效力】法規範違憲宣告立即失效 vs 定期失效於原因案件之再審效力": "原因案件提起再審之特別救濟、定期失效期間主管機關之過渡因應"
    },
    "公司法": {
        "【董事責任】董事之忠實義務與善良管理人注意義務（第23條第1項）": "董事責任之規範基礎、商業判斷法則（Business Judgment Rule）之適用",
        "【決議瑕疵】股東會決議瑕疵之類型（第189條得撤銷 vs 第191條無效）": "召集程序瑕疵、決議內容違反法令或章程之救濟與提訴期間",
        "【股東協議】表決權拘束契約與表決權信託之效力（第175條之1）": "股東協議之容許性與邊界、閉鎖性公司與非閉鎖性公司之適用差異",
        "【少數股東】少數股東提案權（第172條之1）與董事會實質審查權限之界限": "股東提案之法定期限、董事會剔除提案之法定事由與救濟途徑"
    },
    "證券交易法": {
        "【證券詐欺】證券詐欺（第20條第1項、第20條之1）與交易因果關係": "財報不實之重大性認定、詐欺市場理論與損害賠償計算方法",
        "【內線交易】內線交易（第157條之1）重大消息明確時點與實際知悉判斷": "重大消息成立之明確時點（重大性＋明確性）與主觀知悉之舉證",
        "【操縱股價】連續買賣與相對成交（第155條第1項第3款、第4款）主觀意圖": "抬高或壓低交易價格之誘使意圖認定標準、市場常態交易之區辨"
    },
    "保險法": {
        "【告知義務】保險法第64條據實說明義務與保險事故因果關係之抗辯": "說明義務之主客觀要件、危險估計之影響與因果關係不存在之舉證責任",
        "【複保險】複保險之適用範圍（第35~38條）是否及於人身保險之爭議": "定額給付保險與損害填補保險之區分、釋字第576號解釋意旨",
        "【保險代位】保險代位權（第53條）於人身保險與全民健保代位之適用": "保險人代位求償之標的、再保險與第三人侵權損害賠償之競合"
    },
    "票據法": {
        "【抗辯限制】票據之無因性與原因關係抗辯（票據法第13條人之抗辯）": "直接前後手間之原因關係抗辯、惡意取得票據與重大過失取得之抗辯",
        "【背書連續】背書不連續之效力與實質背書轉讓之證明責任": "執票人行使追索權之形式審查要件、形式連續與實質連續之差異",
        "【空白授權】空白授權票據之補行填載權與超越授權範圍之效力": "空白授權票據成立要件、善意執票人之保護與發票人之票據責任"
    },
    "智慧財產權法": {
        "【專利侵害】專利權均等論（Doctrine of Equivalents）與禁反言原則": "全要件原則、置換容易性判斷與申請歷史禁反言之限制",
        "【著作權利】合理使用之四大判斷基準（第65條第2項）與AI訓練著作權爭議": "利用目的與性質、著作之性質、所利用之質量與對潛在市場之影響",
        "【商標混淆】商標混淆誤認之虞審查基準（第30條第1項第10款）與權利耗盡": "商標近似程度、商品服務類似程度與真品平行輸入（水貨）之合法性",
        "【營業秘密】秘密性、經濟價值性與合理保密措施之舉證要件（第2條）": "保密條款、存取權限控管與離職員工侵害營業秘密之舉證與賠償"
    },
    "勞動法與社會法": {
        "【解僱保護】最後手段性原則與勞基法第11條第5款不能勝任工作之解僱": "考核改善期（PIP）、調職命令之合法性與雇主終止勞動契約之嚴格審查",
        "【競業禁止】離職後競業禁止條款之法定有效要件（第9條之1）與代償措施": "正當營業利益、職務接觸權限、合理限制期間地域與合理補償約定",
        "【派遣責任】要派單位與派遣事業單位之共同雇主責任與違法轉正效果": "派遣勞工之權益保障、職業災害補償責任與勞基法第17條之1",
        "【集體爭議】工會法罷工爭議行為之正當性要件與雇主民刑事責任免除": "爭議行為之發動程序（調解不成立、會員過半數同意）與誠信協商義務"
    },
    "財稅法": {
        "【實質課稅】租稅法定主義與實質課稅原則（納稅者權利保護法第7條）之衡平": "法律形式與經濟實質之落差、租稅規避之法律效果與加計利息罰鍰界限",
        "【推計課稅】推計課稅之法定要件與違章裁處罰鍰之舉證證明度要求": "帳簿憑證不全之推計標準、納稅義務人協力義務與稅捐稽徵機關調查義務",
        "【救濟程序】稅捐爭訟復查前置主義與納稅者權利保護官之介入協助": "行政救濟之復查、訴願與撤銷訴訟範圍、暫緩執行與提供擔保"
    },
    "公平交易法": {
        "【聯合行為】事業間聯合行為之推定與合意意思聯絡之舉證（第14條、第15條）": "價格卡特爾、市場分割、寬恕政策（Leniency Program）之適用",
        "【結合申報】事業結合之申報門檻（銷售金額、市占率）與整體經濟利益衡量": "水平結合與垂直結合之市場界定、結合禁止或附負擔許可之審查",
        "【概括條款】公平交易法第25條足以影響交易秩序之欺罔或顯失公平行為": "概括條款之補充性、與民事民事法不當得利或侵權行為之交錯"
    },
    "國際私法": {
        "【定性問題】涉外民商事法律適用之法規定性標準（法庭地法說 vs 個別說）": "定性之階段、先決問題（Preliminary Question）與反致（Renvoi）之適用",
        "【公序良俗】涉外民事法律適用法第8條外國法牴觸我國公序良俗之排除適用": "外國法之查明義務、適用外國法違反我國憲法基本秩序時之內國法補充",
        "【涉外婚姻】涉外涉民事婚姻之實質要件、形式要件與夫妻財產制之準據法": "第46條婚姻成立要件、反致之排除與收養涉外關係準據法"
    },
    "海商法": {
        "【海上運送】運送人法定免責事由（第69條）與堪航能力之證明義務（第62條）": "船舶堪航能力之注意義務、航行過失與商業過失之劃分",
        "【海損救助】共同海損（General Average）之成立要件與各方分攤比例計算": "共同危險、有意而合理之處分或犧牲、海損理算與救助報酬"
    }
}

def get_subject_topics_taxonomy(subject_name: str) -> dict:
    if "全部" in subject_name:
        all_topics = {}
        for sub, topics in CORE_ISSUES_TAXONOMY.items():
            for t_k, t_v in topics.items():
                all_topics[f"[{sub}] {t_k}"] = t_v
        return all_topics

    for k, v in CORE_ISSUES_TAXONOMY.items():
        if k in subject_name or subject_name in k:
            return v
    # 針對沒有完全精確命中的科目進行語意匹配
    if any(w in subject_name for w in ["民總", "債", "物權", "親屬", "繼承"]):
        return CORE_ISSUES_TAXONOMY.get("民法", {})
    if any(w in subject_name for w in ["刑總", "刑分", "特別刑法", "貪污", "洗錢"]):
        return CORE_ISSUES_TAXONOMY.get("刑法", {})
    if any(w in subject_name for w in ["家事", "婚姻事件"]):
        return CORE_ISSUES_TAXONOMY.get("家事事件法", {})
    if any(w in subject_name for w in ["強制執行", "拍賣"]):
        return CORE_ISSUES_TAXONOMY.get("強制執行法", {})
    if any(w in subject_name for w in ["憲法訴訟", "憲判字"]):
        return CORE_ISSUES_TAXONOMY.get("憲法訴訟法", {})
    if any(w in subject_name for w in ["行政程序", "行政罰", "行政訴訟", "訴願", "國賠", "國家賠償"]):
        return CORE_ISSUES_TAXONOMY.get("行政法", {})
    if any(w in subject_name for w in ["證券", "證交"]):
        return CORE_ISSUES_TAXONOMY.get("證券交易法", {})
    if any(w in subject_name for w in ["公司"]):
        return CORE_ISSUES_TAXONOMY.get("公司法", {})
    if any(w in subject_name for w in ["保險"]):
        return CORE_ISSUES_TAXONOMY.get("保險法", {})
    if any(w in subject_name for w in ["票據"]):
        return CORE_ISSUES_TAXONOMY.get("票據法", {})
    if any(w in subject_name for w in ["智財", "專利", "商標", "著作", "營業秘密"]):
        return CORE_ISSUES_TAXONOMY.get("智慧財產權法", {})
    if any(w in subject_name for w in ["勞動", "勞基", "工會", "社會法"]):
        return CORE_ISSUES_TAXONOMY.get("勞動法與社會法", {})
    if any(w in subject_name for w in ["稅", "納保"]):
        return CORE_ISSUES_TAXONOMY.get("財稅法", {})
    if any(w in subject_name for w in ["公平", "獨占", "結合"]):
        return CORE_ISSUES_TAXONOMY.get("公平交易法", {})
    if any(w in subject_name for w in ["涉外", "國際私法"]):
        return CORE_ISSUES_TAXONOMY.get("國際私法", {})
    if any(w in subject_name for w in ["海商", "海難", "船舶"]):
        return CORE_ISSUES_TAXONOMY.get("海商法", {})
    if any(w in subject_name for w in ["國民法官"]):
        return CORE_ISSUES_TAXONOMY.get("國民法官法", {})

    try:
        raw_issues = get_curated_issues_by_chapter("全部體系章節", subject_name)
        if raw_issues:
            return {title: info.get("query", title) for title, info in raw_issues.items()}
    except Exception:
        pass

    return {
        "【核心法理】實體法構成要件該當性與法律效果分析": "核心法條構成要件之法律涵攝、阻卻違法與阻卻責任事由",
        "【實務爭議】最高法院具體裁判與大法庭裁定爭議要點": "最高司法機關權威判旨、通說與有力學說之見解對立與折衝",
        "【程序救濟】法定救濟途徑、當事人適格與訴訟類型選定": "原告適格、管轄權歸屬、救濟期間與權利保護必要性"
    }


# 側邊欄
with st.sidebar:
    st.title("⚖️ 司律 AI 助手")
    st.markdown(f"**雲端同步位置**:  \n`{GOOGLE_DRIVE_DATA_DIR}`")
    st.divider()
    mode_options = [
        MODE_HOME,
        MODE_EVAL,
        MODE_GEN,
        MODE_BANK,
        MODE_ANS,
        MODE_SEARCH,
        MODE_QA,
        MODE_SUMMARIZER,
        MODE_SIX_CODES,
        MODE_SFT
    ]
    if "app_mode" not in st.session_state:
        st.session_state["app_mode"] = MODE_HOME
    else:
        old_val = st.session_state["app_mode"]
        if "爭點查詢" in old_val or "統一法學檢索" in old_val:
            st.session_state["app_mode"] = mode_options[4]
        elif "法律問題" in old_val or "法律諮詢" in old_val or "生活法律" in old_val or "一般法律" in old_val or "智慧問答" in old_val or "全能法律" in old_val or "專屬法學" in old_val or "萬能檢索" in old_val:
            st.session_state["app_mode"] = mode_options[5]
        elif "AI 裁判" in old_val or "AI 摘要" in old_val or "AI裁判" in old_val or "起訴書" in old_val:
            st.session_state["app_mode"] = mode_options[6]
        elif "智慧六法" in old_val:
            st.session_state["app_mode"] = mode_options[7]
        elif "手寫筆記蒸餾" in old_val:
            st.session_state["app_mode"] = mode_options[8]
        elif old_val not in mode_options:
            st.session_state["app_mode"] = MODE_HOME

    cur_idx = mode_options.index(st.session_state["app_mode"])
    app_mode = st.radio(
        "選擇功能模式：",
        mode_options,
        index=cur_idx,
        key=f"nav_radio_widget_{st.session_state['app_mode']}"
    )
    st.session_state["app_mode"] = app_mode
    api_key = get_gemini_api_key()
    if not api_key:
        st.warning("⚠️ 尚未偵測到 API Key！請在 Streamlit Cloud 的 Secrets 設定 `GEMINI_API_KEY`，或在下方直接輸入：")
        user_key = st.text_input("輸入 Gemini API Key：", type="password")
        if user_key.strip():
            import os
            os.environ["GEMINI_API_KEY"] = user_key.strip()
            st.success("API Key 已套用！")
    else:
        st.success("🟢 AI 核心引擎已就緒 (Gemini 視覺多模態)")
    st.info("💡 支援檔案：手寫/打字 PDF、照片 (JPG/PNG/WEBP)、Word (.docx)")


# ----------------- 模式 0: 首頁與系統導覽 -----------------
if app_mode == MODE_HOME:
    st.title("🏛️ 司律考試 AI 評分、智慧命題與法學裁判樞紐")
    st.markdown("##### 專為中華民國司法官、律師高考、法研所與轉學考打造之全方位法學研習智能平台")
    st.caption("結合最新 Gemini 多模態神經網路、全國 5.2 萬條法規、2,100+ 權威裁判判例決議、628+ 中央部會函釋與一試跨科全真題庫。")
    st.write("")

    # 四大資料庫即時統計指標
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1:
        st.metric(
            label="📜 全國法規條文庫",
            value="52,000+ 條",
            delta="六法全書與立法沿革"
        )
    with m_col2:
        try:
            total_precedents_count = len(get_precedents_catalog() or [])
        except Exception:
            total_precedents_count = 2104
        st.metric(
            label="⚖️ 權威裁判・判例・座談會",
            value=f"{total_precedents_count:,} 筆",
            delta="大法庭/原判例/決議/座談會"
        )
    with m_col3:
        try:
            from admin_rulings_engine import get_all_administrative_rulings
            total_rulings_count = len(get_all_administrative_rulings() or [])
        except Exception:
            total_rulings_count = 628
        st.metric(
            label="🏛️ 中央部會權威函釋",
            value=f"{total_rulings_count:,} 則",
            delta="經商/金管/勞動/智財/法務"
        )
    with m_col4:
        try:
            all_stage1_qs = load_all_existing_stage1_mcqs()
            total_mcqs_count = len(all_stage1_qs)
        except Exception:
            total_mcqs_count = 380
        st.metric(
            label="🎯 一試跨科實戰題庫",
            value=f"{total_mcqs_count:,} 題",
            delta="跨科全真模考與詳解"
        )

    st.divider()

    # 九大核心模組導覽卡片
    st.subheader("🧭 九大核心功能模組導覽與快速進入")
    st.caption("點擊下方對應模組之「🚀 立即前往」按鈕，即可快速跳轉至該功能進行演練與查詢。")

    card_rows = [
        [
            ("📝 試卷評分與手寫辨識", "支援拍照、手寫掃描 PDF、Word 電子稿等多模態視覺辨識，依考選部四大評分指標進行榜首級 IRAC 評閱診斷。", MODE_EVAL),
            ("🎯 司律模擬出題", "支援自選題數一試選擇題（含盲測盲題、答案速查表與考點診斷）及二試申論實例題，搭載垂直爭點累加清單。", MODE_GEN),
            ("📚 歷年真題庫檢索與模擬演練", "涵蓋臺大法研所、臺大轉學考、考選部司法官律師、司法特考歷年真題，支援在線實戰作答與自動批改。", MODE_BANK)
        ],
        [
            ("📖 高分權威擬答生成", "以榜首級 IRAC 三段論法架構，融入最新大法庭裁定、指標判例與權威學者獨門暗器見解，快速產出二試頂級擬答。", MODE_ANS),
            ("🔍 統一法學檢索樞紐與判決研析", "整合布林檢索、法院體系字號精準查詢、爭點大典、案例橫向比對（相同見解 vs 相反見解）與審級脈絡更迭鏈。", MODE_SEARCH),
            ("💬 專屬法學全能問答樞紐", "支援日常法律諮詢、國考爭點論辯、法條精準定位、專業書狀草擬及車禍折舊、資遣費、剩餘財產金額精算工具。", MODE_QA)
        ],
        [
            ("📑 一鍵 AI 判解與長篇函釋精鍊", "深度消化數萬字冗長判決書或部會函釋，一鍵提煉「主文、核心爭點、實務見解、學說評釋與國考作答破題金句」。", MODE_SUMMARIZER),
            ("⚖️ 智慧六法與條文判解標註", "全方位整合全國法規條文、立法院三讀立法理由、沿革修正對照、關聯實務字號、重要行政函釋與筆記關聯。", MODE_SIX_CODES),
            ("📥 手寫筆記蒸餾與大庫管理", "支援多引擎解壓司法院 Open Data RAR/ZIP 打包檔，並將筆記與考卷一鍵蒸餾轉化為百萬筆 SFT 法律微調大庫。", MODE_SFT)
        ]
    ]

    for r_idx, row in enumerate(card_rows):
        cols = st.columns(3)
        for c_idx, (c_title, c_desc, c_mode) in enumerate(row):
            with cols[c_idx]:
                with st.container(border=True):
                    st.markdown(f"##### {c_title}")
                    st.write(c_desc)
                    if st.button("🚀 立即前往", key=f"btn_jump_mode_{r_idx}_{c_idx}", use_container_width=True):
                        st.session_state["app_mode"] = c_mode
                        st.rerun()

    st.divider()

    # 隱私權政策、著作權政策與法律免責聲明
    pol_c1, pol_c2, pol_c3 = st.columns(3)
    with pol_c1:
        with st.container(border=True):
            st.markdown("#### 🔒 隱私權保護政策")
            st.caption("依中華民國《個人資料保護法》及相關法規辦理")
            st.markdown(
                """
1. **資料蒐集與用途**：本平臺使用者所上傳之手寫試卷、自訂筆記、作答紀錄與各類文件，僅限於當次瀏覽器工作階段中進行 AI 辨識、爭點解析、出題與評閱，絕不用於未授權之第三方商業散布。
2. **金鑰與憑證安全**：使用者於本系統設定之 `GEMINI_API_KEY` 及司法院開放平臺帳號密碼，均僅保存在當前瀏覽器 `st.session_state` 暫存記憶體中，絕不寫入公開原始碼、日誌或持久端伺服器資料庫。
3. **資料控制權**：使用者得隨時於側邊欄點擊「清除 Token」或重整瀏覽器以完全銷毀工作階段記憶體中的敏感資訊。
                """
            )
    with pol_c2:
        with st.container(border=True):
            st.markdown("#### 📜 著作權與合理使用政策")
            st.caption("依中華民國《著作權法》第 9 條、第 52 條與第 65 條規範")
            st.markdown(
                """
1. **公務著作公共領域**：本平臺收錄之中華民國憲法、法律、命令、司法院裁判書全文、最高法院裁判、最高行政法院裁判、原判例、庭長法官聯席會議決議、法律座談會研討結論、中央部會行政函釋及考選部歷年公務人員高考與專技國考試題，依《著作權法》第 9 條第 1 項規定，**不得為著作權之標的**，屬全體國民共享之公共領域公有財產。
2. **學說與筆記合理使用**：系統中所引用之學者學說爭點、教科書要旨與個人筆記重點，係為法學學術研析、國考教學與個人學習之必要正當目的，符合《著作權法》第 52 條及第 65 條第 2 項之合理使用範圍。
                """
            )
    with pol_c3:
        with st.container(border=True):
            st.markdown("#### ⚖️ 法律免責聲明")
            st.caption("依中華民國《法院組織法》及法學研習專業指引聲明")
            st.markdown(
                """
1. **非正式法律意見**：本系統所生成之試卷批改、考點建議、IRAC 高分擬答、案例橫向比對分析及金額試算結果，均由大型語言模型及演算法自動生成，僅供法律學術研習、司法官律師高考準備及司法特考演練參考，**不構成任何形式之正式法律意見、訴訟諮詢或委任要約**。
2. **原判例效力說明**：依《法院組織法》第 57 條之 1 規定，最高法院於中華民國 108 年 7 月 4 日前依法選編之判例，若無裁判全文者停止適用；其有裁判全文者，其效力與未經選編為判例之最高法院裁判相同。本平臺收錄之「原判例」均已依法註明裁判全文字號，供考生對照歷史法理脈絡。
3. **個案具體適用**：具體訴訟爭議請洽詢中華民國合格執業律師或尋求法律扶助基金會專業協助。
                """
            )

# ----------------- 模式 1: 試卷評分 -----------------
elif app_mode == MODE_EVAL or app_mode == "📝 試卷評分與手寫辨識 (手寫/PDF/Word)":
    st.header("📝 司律申論試卷 - 多模態 AI 批改與診斷")
    st.write("上傳考生的手寫試卷照片、PDF 檔或 Word 電子稿，系統將自動進行 OCR 辨識、爭點比對與四大維度評分。")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("1. 題目與標準")
        if "question_text_content" not in st.session_state:
            st.session_state.question_text_content = ""
        if "rubric_text_content" not in st.session_state:
            st.session_state.rubric_text_content = ""

        if st.session_state.get("imported_from_bank_label"):
            c_info1, c_info2 = st.columns([4, 1])
            with c_info1:
                st.success(f"🎉 已成功自題庫帶入：**{st.session_state['imported_from_bank_label']}**！\n試題已自動填入下方，請於右側直接上傳考生作答即可開始評閱。")
            with c_info2:
                if st.button("✖️ 清除題目", key="btn_clear_imported_q"):
                    st.session_state.question_text_content = ""
                    st.session_state.rubric_text_content = ""
                    st.session_state.imported_from_bank_label = ""
                    st.rerun()

        q_input_mode = st.radio(
            "題目提供方式：",
            ["✍️ 手動輸入題目文字", "📷 拍照 / 圖片上傳試題 (AI 自動 OCR)", "🎯 從雲端實戰試題與百題演練挑選 (含民法百題/考古題)", "👥 從社群考生共享題庫挑選題目"],
            horizontal=True
        )

        new_extracted_q = None
        if q_input_mode == "🎯 從雲端實戰試題與百題演練挑選 (含民法百題/考古題)":
            drive_questions = [x for x in drive_notes if x.get("doc_nature") == "question"]
            if drive_questions:
                q_subs = ["全部考科"] + sorted(list(set(x["subject"] for x in drive_questions)))
                c_dq1, c_dq2 = st.columns([1, 2])
                with c_dq1:
                    sel_dq_sub = st.selectbox("題目考科篩選：", q_subs, key="sel_drive_q_sub")
                filtered_dqs = [x for x in drive_questions if sel_dq_sub == "全部考科" or x["subject"] == sel_dq_sub]
                with c_dq2:
                    q_labels = [f"{q.get('tag', '【實戰試題】')} 【{q['subject']}】{q['filename']}" for q in filtered_dqs]
                    sel_dq_idx = st.selectbox("選擇實戰試題或百題檔案：", range(len(filtered_dqs)), format_func=lambda i: q_labels[i], key="sel_drive_q_file")
                
                chosen_dq = filtered_dqs[sel_dq_idx]
                if st.button("📥 一鍵帶入此試題進行作答與評分", type="primary", key="btn_apply_drive_q"):
                    with st.spinner(f"正在自雲端試題庫載入《{chosen_dq['filename']}》..."):
                        q_extracted_text = read_note_text(chosen_dq["path"], max_pages=10, auto_ocr=True)
                        st.session_state.question_text_content = q_extracted_text if q_extracted_text else f"【實戰試題】：{chosen_dq['filename']}"
                        st.session_state.imported_from_bank_label = f"{chosen_dq.get('tag', '【實戰試題】')}《{chosen_dq['filename']}》"
                        st.rerun()
            else:
                st.info("💡 目前雲端硬碟中暫未偵測到實戰試題或百題檔案。")

        elif q_input_mode == "👥 從社群考生共享題庫挑選題目":
            comm_questions = load_community_questions()
            if comm_questions:
                q_titles = [f"【{q.get('subject', '綜合')}】{q.get('title', '題目')} ({q.get('created_at', '')[:10]})" for q in comm_questions]
                sel_comm_q_idx = st.selectbox("選擇社群考生共享試題：", range(len(comm_questions)), format_func=lambda i: q_titles[i], key="sel_comm_q_m1")
                if st.button("📥 帶入此題進行評分", key="btn_apply_comm_q"):
                    chosen_q = comm_questions[sel_comm_q_idx]
                    st.session_state.question_text_content = chosen_q.get("content", "")
                    st.session_state.rubric_text_content = chosen_q.get("rubric", "")
                    st.rerun()
            else:
                st.info("💡 目前社群共享庫中暫無試題，您所輸入或上傳之試題評分後將自動典藏共享！")

        elif q_input_mode == "📷 拍照 / 圖片上傳試題 (AI 自動 OCR)":
            q_tab_cam, q_tab_file = st.tabs(["📸 即時拍照", "📁 上傳照片 / PDF"])
            with q_tab_cam:
                cam_pic = st.camera_input("使用相機拍攝試題：", key="camera_question_input")
                if cam_pic is not None:
                    try:
                        pil_cam = Image.open(cam_pic)
                        with st.spinner("🔍 正在使用 Gemini 多模態神經網路辨識試題照片..."):
                            new_extracted_q = ocr_handwritten_images(
                                [pil_cam],
                                prompt_hint="這是一份國家考試或法學考試之試題題幹，請精準辨識並謄錄其案件事實、當事人主張與問題子題。"
                            )
                    except Exception as ce:
                        st.error(f"相機照片辨識失敗: {ce}")
            with q_tab_file:
                q_up = st.file_uploader(
                    "選取試題照片或 PDF 檔：",
                    type=["jpg", "jpeg", "png", "webp", "pdf", "docx"],
                    key="uploader_question_input"
                )
                if q_up is not None:
                    try:
                        with st.spinner("🔍 正在解析試題檔案與執行 OCR 辨識..."):
                            txt_q, imgs_q = parse_document(q_up.read(), q_up.name, auto_ocr_handwriting=True)
                            if txt_q and len(txt_q.strip()) > 20:
                                new_extracted_q = txt_q.strip()
                            elif imgs_q:
                                new_extracted_q = ocr_handwritten_images(
                                    imgs_q,
                                    prompt_hint="這是一份法學考試試卷題目，請精確謄錄案件事實、問題與子題配分。"
                                )
                    except Exception as qfe:
                        st.error(f"試題檔案解析失敗: {qfe}")

            if new_extracted_q:
                if new_extracted_q != st.session_state.get("last_extracted_q"):
                    st.session_state.question_text_content = new_extracted_q
                    st.session_state.last_extracted_q = new_extracted_q
                    st.success("✅ 題目已成功辨識！內容已自動填入下方，您可直接檢視或微調：")

        question_text = st.text_area(
            "請輸入或確認考試題目內容：",
            value=st.session_state.question_text_content,
            height=180,
            placeholder="例如：甲向乙借款新臺幣1000萬元，並將其所有之A屋設定普通抵押權予乙以供擔保..."
        )
        st.session_state.question_text_content = question_text

        rubric_text = st.text_area(
            "評分標準 / 參考擬答 (選填，留空則由 AI 自律法學知識庫推導)：",
            value=st.session_state.get("rubric_text_content", ""),
            height=110,
            placeholder="可貼入補習班爭點、評分大綱或最高法院判決字號..."
        )
        st.session_state.rubric_text_content = rubric_text

    with col2:
        st.subheader("2. 上傳考生作答")
        uploaded_files = st.file_uploader(
            "拖曳或選取檔案 (支援 JPG, PNG, PDF, Word docx，可多選)：",
            type=["jpg", "jpeg", "png", "webp", "pdf", "docx"],
            accept_multiple_files=True
        )

        all_images = []
        all_texts = []

        if uploaded_files:
            for f in uploaded_files:
                txt, imgs = parse_document(f.read(), f.name)
                if txt:
                    all_texts.append(txt)
                if imgs:
                    all_images.extend(imgs)

            st.success(f"已成功解析：{len(all_images)} 頁影像/試卷圖，以及 {len(all_texts)} 份文字稿。")
            if all_images:
                with st.expander("預覽已上傳試卷頁面 (第一頁)"):
                    st.image(all_images[0], use_container_width=True)

    start_eval = st.button("🚀 開始評閱試卷", type="primary", use_container_width=True)

    if start_eval:
        if not question_text.strip():
            st.error("請先輸入【考試題目內容】！")
        elif not all_images and not all_texts:
            st.error("請至少上傳一張手寫試卷圖、PDF 或 Word 檔案！")
        else:
            # 自動新建獨立檔案典藏使用者上傳試卷題目至社群共享庫
            try:
                archive_uploaded_question(
                    title=st.session_state.get("imported_from_bank_label", "") or "二試實例實戰題",
                    content=question_text,
                    subject="司律二試申論題",
                    rubric=rubric_text
                )
            except Exception:
                pass

            with st.spinner("⚖️ 正在運用 Gemini 視覺多模態神經網路進行手寫辨識、三段論法邏輯檢驗與爭點比對..."):
                try:
                    evaluator = LawExamEvaluator()
                    combined_text = "\n\n".join(all_texts) if all_texts else None
                    result = evaluator.evaluate_submission(
                        images=all_images if all_images else None,
                        submission_text=combined_text,
                        question_text=question_text,
                        standard_rubric=rubric_text if rubric_text.strip() else None
                    )

                    st.balloons()
                    st.success("評閱完成！診斷報告已即時同步至 Google Drive！")

                    # 評分結果面板
                    mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
                    mcol1.metric("總得分", f"{result.get('total_score', 0)} / 100")
                    mcol2.metric("等第評級", result.get("grade_level", "未定"))
                    mcol3.metric("爭點意識與開標", f"{result.get('issue_spotting_score', 0)} / 25")
                    mcol4.metric("三段論法與邏輯", f"{result.get('legal_reasoning_score', 0)} / 25")
                    mcol5.metric("實務學說與涵攝", f"{result.get('precedent_scholarship_score', 0) + result.get('subsumption_score', 0)} / 50")

                    st.divider()

                    rcol1, rcol2 = st.columns(2)
                    with rcol1:
                        st.subheader("🎯 核心爭點命中分析")
                        st.write("**✅ 成功命中之爭點：**")
                        for item in result.get("identified_issues", []):
                            st.write(f"- :green[{item}]")
                        st.write("**❌ 漏未論述之核心爭點：**")
                        for item in result.get("missed_issues", []):
                            st.write(f"- :red[{item}]")

                    with rcol2:
                        st.subheader("💡 卷面優劣診斷")
                        st.write("**🌟 試卷亮點：**")
                        for item in result.get("strengths", []):
                            st.write(f"- {item}")
                        st.write("**⚠️ 論述盲點與缺失：**")
                        for item in result.get("weaknesses", []):
                            st.write(f"- {item}")

                    st.subheader("🔍 手寫謄錄內容 (OCR 辨識結果)")
                    st.text_area("考生試卷文字排版還原：", value=result.get("transcription", ""), height=150)

                    st.subheader("✍️ 閱卷委員優化重構建議")
                    st.info(result.get("suggested_revision", ""))

                except Exception as e:
                    st.error(f"評閱失敗: {e}")

# ----------------- 模式 2: 司律出題 -----------------
elif app_mode == MODE_GEN or app_mode == "🎯 司律模擬出題 (一試/二試 & 手寫筆記客製命題)":
    st.header("🎯 司律考試模擬命題系統（一試選擇 / 二試申論實例題）")
    st.write("可放入個人手寫/打字讀書筆記、指定考科與考點，由法學大模型為您量身打造司律一試選擇題或二試實例申論題。")

    stage = st.radio("選擇考試階段：", ["一試 (選擇題 / 單選題)", "二試 (申論實例題)"], horizontal=True)

    col_sub1, col_sub2 = st.columns([1, 1])
    with col_sub1:
        st.markdown("##### 🏛️ 第一步：選擇考試學門與科目")
        domain_choice = st.selectbox(
            "考科學門體系分類篩選：",
            list(LAW_DOMAIN_TAXONOMY.keys()),
            key="sel_exam_domain_filter"
        )
        subjects_list = LAW_DOMAIN_TAXONOMY[domain_choice]
        subject_choice = st.selectbox("考試科目：", subjects_list, key="sel_exam_subject_choice")
        if subject_choice == "其他自訂學門":
            subject = st.text_input("請輸入自訂科目名稱：", value="民事法學")
        else:
            subject = subject_choice.split(" ")[0]

    with col_sub2:
        st.markdown("##### 🎯 第二步：設定核心考點爭點與客製化出題範圍")
        list_key = f"exam_vertical_items_list_{subject}"
        if list_key not in st.session_state:
            st.session_state[list_key] = []

        available_topics_map = get_subject_topics_taxonomy(subject)
        topic_options = ["-- 💡 點此下拉挑選核心考點加入命題列表 --"] + list(available_topics_map.keys())
        selected_topic_choice = st.selectbox(
            f"依【{subject}】點選核心考點爭點（選取後自動累加至下方列表）：",
            options=topic_options,
            key=f"sel_topic_dropdown_{subject}"
        )
        if selected_topic_choice != topic_options[0]:
            t_desc = available_topics_map.get(selected_topic_choice, selected_topic_choice)
            full_item_str = f"{selected_topic_choice}（{t_desc}）"
            if full_item_str not in st.session_state[list_key]:
                st.session_state[list_key].append(full_item_str)
            st.rerun()

        with st.expander("🛠️ 客製化命題範圍設定與自訂考點新增（章節・法條・專案主題）", expanded=False):
            col_sc1, col_sc2, col_sc3 = st.columns([1.2, 1.8, 1])
            with col_sc1:
                scope_mode = st.selectbox(
                    "命題範圍類型：",
                    ["📜 特定法條/條文區間", "📚 特定編次/章節專題", "🏛️ 實務見解專題", "✏️ 自訂命題範圍"],
                    key=f"sel_scope_type_{subject}"
                )
            with col_sc2:
                custom_scope_in = st.text_input(
                    "指定客製化範圍明細：",
                    placeholder="例如：民法第179~198條債各、刑法第12~31條犯罪論...",
                    key=f"inp_custom_scope_{subject}"
                )
            with col_sc3:
                st.write("")
                if st.button("➕ 加入列表", use_container_width=True, key=f"btn_add_scope_{subject}"):
                    if custom_scope_in.strip():
                        item_s = f"【{scope_mode}】：{custom_scope_in.strip()}"
                        if item_s not in st.session_state[list_key]:
                            st.session_state[list_key].append(item_s)
                        st.rerun()

            col_adhoc_in, col_adhoc_btn = st.columns([3, 1])
            with col_adhoc_in:
                adhoc_in = st.text_input(
                    "自訂考點關鍵字：",
                    placeholder="例如：108台上大1719、不純正不作為犯保證人地位、違約定金酌減...",
                    key=f"inp_adhoc_{subject}"
                )
            with col_adhoc_btn:
                st.write("")
                if st.button("➕ 新增考點", use_container_width=True, key=f"btn_add_adhoc_{subject}"):
                    if adhoc_in.strip():
                        item_a = f"【自訂考點】：{adhoc_in.strip()}"
                        if item_a not in st.session_state[list_key]:
                            st.session_state[list_key].append(item_a)
                        st.rerun()

        # 垂直向下累加列表渲染 (有框容器)
        current_items = st.session_state[list_key]
        st.markdown(f"**📋 目前已設定命題爭點與範圍列表（共 {len(current_items)} 項）：**")
        with st.container(border=True):
            if not current_items:
                st.caption("（尚未加入任何考點，請從上方下拉選單選取，或自訂新增；若留空系統將進行全科目綜合出題）")
            else:
                for idx, it in enumerate(current_items):
                    r_col_text, r_col_del = st.columns([5, 1])
                    with r_col_text:
                        st.markdown(f"**{idx + 1}.** {it}")
                    with r_col_del:
                        if st.button("🗑️ 刪除", key=f"btn_del_topic_{subject}_{idx}", use_container_width=True):
                            st.session_state[list_key].pop(idx)
                            st.rerun()

                st.write("")
                if st.button("🗑️ 清空全部列表項目", key=f"btn_clear_all_topics_{subject}"):
                    st.session_state[list_key] = []
                    st.rerun()

    # 自動組合 topic 傳入出題引擎（移除筆記區塊）
    if current_items:
        topic = "、".join([re.sub(r'^[【].*?[】]：?', '', it).split('（')[0] for it in current_items])
    else:
        topic = f"{subject}核心實務爭點與法規構成要件"
    final_notes = None

    if stage == "一試 (選擇題 / 單選題)":
        stage1_tab_ai, stage1_tab_300 = st.tabs([
            "🎲 AI 智慧命題模式（任意題數 & 支援手寫筆記 OCR 客製出題）",
            "📖 司律一試 300+ 題全真跨科模擬題庫（民・刑・公・商跨科即時測驗）"
        ])

        with stage1_tab_ai:
            st.markdown("#### ⚙️ AI 一試出題參數設定（比照 300 題模擬題庫規格）")
            qcol1, qcol2 = st.columns(2)
            with qcol1:
                q_mode = st.selectbox(
                    "題型結構模式：",
                    ["標準單選題 (案例情境盲測)", "綜合案例實事實務題組題 (跨子題)", "全真綜合模考卷 (混合題型)"]
                )
            with qcol2:
                q_count_option = st.selectbox(
                    "出題題數：",
                    ["5 題 (隨堂測驗)", "10 題 (標準單元測)", "15 題 (強化題組)", "20 題 (大型模考卷)", "30 題 (全真模擬題庫)", "50 題 (半套模考卷)", "100 題 (全真一試大卷)", "自訂題數"],
                    key="ai_q_count_select"
                )
                if q_count_option == "自訂題數":
                    q_count = st.number_input("請輸入自訂題數 (1~100 題)：", min_value=1, max_value=100, value=10, key="ai_custom_q_count")
                else:
                    q_count = int(q_count_option.split(" ")[0])

            if st.button("🎲 開始生成一試全真模擬測驗題卷", type="primary", use_container_width=True):
                target_topic = topic.strip() if topic.strip() else "核心實務爭點與法規構成要件"

                progress_bar = st.progress(0)
                status_text = st.empty()
                status_text.text(f"正在以司律一試命題規格批次生成 {q_count} 題，每批 5 題穩定出題中...")

                def update_progress(curr, tot):
                    progress_bar.progress(min(1.0, curr / tot))
                    status_text.text(f"已完成 {curr} / {tot} 題...")

                try:
                    gen = LawExamGenerator()
                    exam_res = gen.generate_stage1_exam(
                        subject=subject,
                        topic=target_topic,
                        count=q_count,
                        question_mode=q_mode,
                        notes_content=final_notes if final_notes else None,
                        progress_callback=update_progress
                    )
                    progress_bar.progress(1.0)
                    reset_stage1_exam_state()
                    st.session_state["stage1_exam_data"] = exam_res
                    status_text.success(f"🎉 成功生成【{subject}】共 {len(exam_res.get('questions', []))} 題司律一試測驗卷！")
                    st.rerun()

                except Exception as e:
                    st.error(f"出題失敗: {e}")

        with stage1_tab_300:
            st.markdown("#### 📖 司律一試 300+ 題全真跨科模擬題庫（涵蓋民法・刑法・憲法・行政法・民訴・刑訴・商事法）")
            st.write("全面收錄**行政法 300 題完整題庫**與**民法、刑法、憲法、民事訴訟法、刑事訴訟法、商事法 86 題跨科全真題目**，題題具備情境案例事實、四大嚴謹選項與 IRAC 權威實務見解解析（憲法判決、最高法院大法庭裁定、指標性重大原判例）。支援單科專精衝刺或全科跨領域大模考！")

            all_bank_mcqs = load_all_existing_stage1_mcqs()

            c300_col1, c300_col2, c300_col3 = st.columns([1.2, 1.2, 1])
            with c300_col1:
                sel_domain_filter = st.selectbox(
                    "1. 選擇測驗科目範圍：",
                    [
                        "🌟 全部既有題庫跨科隨機抽考",
                        "🏛️ 民法 (總則・債編・物權・親屬繼承)",
                        "⚖️ 刑法 (總則犯罪論・刑罰論・分則財產與生命法益)",
                        "📜 憲法 (基本權利違憲審查・正當法律程序・權力分立)",
                        "📑 行政法 (300 題模擬題庫・行政處分・行政契約・行政爭訟)",
                        "💼 民事訴訟法 (當事人適格・訴訟標的・爭點效・既判力)",
                        "🔍 刑事訴訟法 (強制處分令狀・科技偵查・證據排除・傳聞法則)",
                        "🏢 商事法 (公司負責人義務・內線交易・保險告知義務)"
                    ],
                    key="sel_stage1_bank_domain"
                )

            # 依科目精準過濾試題池
            if sel_domain_filter == "🌟 全部既有題庫跨科隨機抽考":
                subject_pool = all_bank_mcqs
            elif "民法" in sel_domain_filter and "民事訴訟法" not in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "民法"]
            elif "刑法" in sel_domain_filter and "刑事訴訟法" not in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "刑法"]
            elif "憲法" in sel_domain_filter and "行政法" not in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "憲法"]
            elif "行政法" in sel_domain_filter and "憲法" not in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if "行政" in q.get("subject", "")]
            elif "民事訴訟法" in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "民事訴訟法"]
            elif "刑事訴訟法" in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "刑事訴訟法"]
            elif "商事法" in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "商事法"]
            else:
                subject_pool = [q for q in all_bank_mcqs if sel_domain_filter in q.get("subject", "") or sel_domain_filter in q.get("major_domain", "")]

            # 動態彙整該科目下所屬的考點分類
            raw_pool_cats = sorted(list({q.get("category", "").strip() for q in subject_pool if q.get("category")}))
            cat_options = [f"全部考點分類 (不限，此科目共 {len(subject_pool)} 題)"] + raw_pool_cats

            with c300_col2:
                cat_300_choice = st.selectbox(
                    "2. 考點分類專題篩選：",
                    cat_options,
                    key=f"sel_cat_300_choice_{sel_domain_filter[:4]}"
                )

            with c300_col3:
                count_300_choice = st.selectbox(
                    "3. 抽題題數：",
                    ["5 題 (快速隨測)", "10 題 (標準測驗)", "15 題 (綜合考卷)", "20 題 (大模考)", "30 題 (全卷實戰)", "50 題 (高強度特訓)", "自訂題數"],
                    key="count_300_select"
                )
                if count_300_choice == "自訂題數":
                    take_count = st.number_input("請輸入抽取題數 (1~100 題)：", min_value=1, max_value=100, value=10, key="custom_300_count")
                else:
                    take_count = int(count_300_choice.split(" ")[0])

            if st.button("🚀 從全真題庫抽取試題開始測驗", type="primary", use_container_width=True):
                import random
                if not subject_pool:
                    st.error("目前該科目題庫為空或載入失敗。")
                else:
                    pool = list(subject_pool)

                    # 考點分類過濾
                    if not cat_300_choice.startswith("全部考點分類"):
                        cat_filtered = [q for q in pool if q.get("category", "").strip() == cat_300_choice]
                        if cat_filtered:
                            pool = cat_filtered

                    actual_take = min(take_count, len(pool))
                    selected_qs = random.sample(pool, actual_take)
                    reindexed_qs = []
                    new_answer_key = {}
                    for i, q in enumerate(selected_qs, 1):
                        q_copy = dict(q)
                        q_copy["original_no"] = q_copy.get("question_no", i)
                        q_copy["question_no"] = i
                        ans = q_copy.get("answer", "A")
                        new_answer_key[str(i)] = ans
                        reindexed_qs.append(q_copy)

                    exam_id = f"bank_{int(time.time()*1000)}"
                    reset_stage1_exam_state()
                    st.session_state["stage1_exam_data"] = {
                        "exam_id": exam_id,
                        "subject": sel_domain_filter,
                        "topic": f"全真模擬抽考（{sel_domain_filter}・{len(reindexed_qs)}題）",
                        "total_count": len(reindexed_qs),
                        "questions": reindexed_qs,
                        "answer_key": new_answer_key
                    }
                    st.success(f"🎉 已成功自【{sel_domain_filter}】題庫中隨機抽取 {len(reindexed_qs)} 題（符合條件試題池共 {len(pool)} 題），請於下方開始作答！")
                    st.rerun()

        # 若 session 中有一試試題，展示作答、速查表與詳解
        if "stage1_exam_data" in st.session_state:
            exam_data = st.session_state["stage1_exam_data"]
            cur_exam_id = exam_data.get("exam_id", "curr")
            questions = exam_data.get("questions", [])
            answer_key = exam_data.get("answer_key", {})

            # 統計本卷所有試題考點分類
            raw_cats = [q.get("category", "").strip() for q in questions if q.get("category")]
            clean_cats = sorted(list(set(raw_cats)))

            st.divider()
            col_sec_head, col_sec_cat = st.columns([2, 1])
            with col_sec_head:
                st.subheader(f"📝 【第一部分：全真試題區】（盲測情境實力）")
                st.caption("提示：題幹已全面隱匿法條條號與裁判字號，請直接依具體事實判斷最正確選項。")
            with col_sec_cat:
                if clean_cats:
                    view_cat_filter = st.selectbox(
                        "🏷️ 依試題考點分類過濾瀏覽：",
                        ["🌟 顯示全卷考點試題 (共 %d 題)" % len(questions)] + [f"{c} ({raw_cats.count(c)} 題)" for c in clean_cats],
                        key="stage1_exam_category_filter"
                    )
                else:
                    view_cat_filter = "🌟 顯示全卷考點試題"

            user_answers = {}
            for q in questions:
                q_no = q.get("question_no")
                cat = q.get("category", "")
                cat_display = f" `{cat}`" if cat else ""

                # 若有選定分類過濾，且不符合當前分類，則跳過顯示
                if view_cat_filter != "🌟 顯示全卷考點試題" and not view_cat_filter.startswith("🌟 顯示全卷"):
                    chosen_cat = view_cat_filter.split(" (")[0].strip()
                    if cat.strip() != chosen_cat:
                        continue

                st.markdown(f"#### 第 {q_no} 題{cat_display}")
                if q.get("case_facts"):
                    st.info(f"**【題組共通案件事實】**：\n\n{q.get('case_facts')}")

                st.write(q.get("question"))

                opts = q.get("options", {})
                choice_options = []
                for k in ["A", "B", "C", "D"]:
                    if k in opts:
                        choice_options.append(f"({k}) {opts[k]}")

                user_ans = st.radio(
                    f"請選擇第 {q_no} 題答案：",
                    choice_options,
                    index=None,
                    key=f"user_choice_{cur_exam_id}_{q_no}"
                )
                if user_ans:
                    user_answers[str(q_no)] = user_ans[1] # 提取 'A'

                st.write("")

            col_submit, col_reset, col_export = st.columns([1, 1, 1])
            with col_submit:
                if st.button("🏁 交卷立即線上批改評分", type="primary", use_container_width=True):
                    st.session_state["stage1_graded"] = True
                    st.session_state["stage1_user_answers"] = user_answers
                    st.rerun()

            with col_reset:
                if st.button("🔄 重新作答（清空本卷作答並重新評分）", type="secondary", use_container_width=True):
                    reset_stage1_exam_state()
                    st.rerun()

            with col_export:
                md_content = LawExamGenerator.format_stage1_exam_markdown(exam_data)
                st.download_button(
                    label="💾 一鍵下載完整全真模擬試卷 (Markdown 檔)",
                    data=md_content,
                    file_name=f"司律一試_{exam_data.get('subject')}_{exam_data.get('topic')[:10]}_{len(questions)}題.md",
                    mime="text/markdown",
                    use_container_width=True
                )

            # 批改結果與考點分類實力診斷
            is_graded = st.session_state.get("stage1_graded", False)
            if is_graded:
                u_answers = st.session_state.get("stage1_user_answers", user_answers)
                score = 0
                for q_num_str, correct_ans in answer_key.items():
                    if u_answers.get(q_num_str) == correct_ans:
                        score += 1
                total_q = len(questions)
                pct = int(score / total_q * 100) if total_q > 0 else 0
                st.balloons()
                st.success(f"🎉 測驗批改完成！總成績：{score} / {total_q} 題（得分率：{pct}%）")

                # 考點分類實力診斷與弱點分析報告
                st.markdown("#### 🎯 考點分類實力診斷與弱點分析報告")
                cat_stats = {}
                for q in questions:
                    c = q.get("category", "綜合實務考點").strip()
                    if not c:
                        c = "綜合實務考點"
                    if c not in cat_stats:
                        cat_stats[c] = {"total": 0, "correct": 0, "missed": []}
                    cat_stats[c]["total"] += 1
                    q_no_str = str(q.get("question_no"))
                    if u_answers.get(q_no_str) == answer_key.get(q_no_str):
                        cat_stats[c]["correct"] += 1
                    else:
                        cat_stats[c]["missed"].append(q.get("question_no"))

                diag_cols = st.columns(min(len(cat_stats), 4) if cat_stats else 1)
                for idx_c, (c_name, stats) in enumerate(cat_stats.items()):
                    with diag_cols[idx_c % len(diag_cols)]:
                        c_rate = int(stats["correct"] / stats["total"] * 100) if stats["total"] > 0 else 0
                        if c_rate == 100:
                            badge = "🌟 精熟達標"
                        elif c_rate >= 60:
                            badge = "👍 掌握良好"
                        else:
                            badge = "⚠️ 建議複習加強"
                        st.metric(
                            label=f"{c_name[:14]}",
                            value=f"{stats['correct']}/{stats['total']} 題 ({c_rate}%)",
                            delta=badge
                        )
                        if stats["missed"]:
                            st.caption(f"錯題題號：第 {', '.join(map(str, stats['missed']))} 題")

            # 第二部分：標準答案速查表與詳細解析（交卷批改後解鎖，附提前展開核對選項）
            peek_solution = st.checkbox("👁️ 提早檢視答案速查表與詳細解析 (不鎖定)", value=False, key="cb_peek_stage1_solution")
            show_stage1_sol = is_graded or peek_solution

            if not show_stage1_sol:
                st.info("🔒 **答案速查表與逐題詳解已安全鎖定**：請於上方完成作答後點擊「🏁 交卷立即線上批改評分」自動解鎖，或勾選上方「提早檢視」選項。")
            else:
                st.divider()
                st.subheader(f"📋 【第二部分：標準答案速查表】(共 {len(questions)} 題)")

                u_answers_map = st.session_state.get("stage1_user_answers", user_answers) if is_graded else {}
                cols_per_row = 5
                for row_start in range(1, len(questions) + 1, cols_per_row):
                    key_cols = st.columns(cols_per_row)
                    for c_idx in range(cols_per_row):
                        q_num = row_start + c_idx
                        if q_num <= len(questions):
                            with key_cols[c_idx]:
                                c_ans = answer_key.get(str(q_num), "A")
                                if is_graded:
                                    u_ans = u_answers_map.get(str(q_num))
                                    if u_ans == c_ans:
                                        st.success(f"**第 {q_num} 題**：`({c_ans})` ✅ 正確")
                                    elif u_ans:
                                        st.error(f"**第 {q_num} 題**：`({c_ans})` ❌ (選 {u_ans})")
                                    else:
                                        st.warning(f"**第 {q_num} 題**：`({c_ans})` ⚪ 未作答")
                                else:
                                    st.info(f"**第 {q_num} 題**：`({c_ans})`")

                st.divider()
                st.subheader("💡 【第三部分：逐題詳細解析與實務裁判出處】")
                for q in questions:
                    q_no = q.get("question_no")
                    ans = q.get("answer")
                    with st.expander(f"查看第 {q_no} 題詳細解析 (正確答案：({ans}))"):
                        if q.get("core_issue"):
                            st.markdown(f"**【核心爭點】**：:blue[{q.get('core_issue')}]")
                        if q.get("legal_references"):
                            st.markdown(f"**【規範法條及實務裁判字號】**：:green[{q.get('legal_references')}]")
                        st.markdown("**【逐項解析與盲點辨析】**：")
                        st.write(q.get("explanation", ""))
    else:
        # 二試申論實例題
        if st.button("🎲 生成二試實例申論題", type="primary", use_container_width=True):
            target_topic = topic.strip() if topic.strip() else "年度重大爭議實例與實務大法庭爭點"
            with st.spinner("正在融合最新判例、大法庭與考生筆記，設計二試綜合案例事實..."):
                try:
                    gen = LawExamGenerator()
                    res = gen.generate_stage2_exam(
                        subject=subject,
                        topic=target_topic,
                        notes_content=final_notes if final_notes else None
                    )
                    st.session_state["stage2_exam_data"] = res
                    st.success("二試實例題設計完成！")
                except Exception as e:
                    st.error(f"出題失敗: {e}")

        if "stage2_exam_data" in st.session_state:
            res = st.session_state["stage2_exam_data"]
            st.divider()
            st.subheader(f"【{res.get('subject', subject)}】綜合實例申論題 (總分：{res.get('total_points', 100)} 分)")
            st.markdown("#### 📜 案例事實背景：")
            st.write(res.get("question_facts", ""))

            st.markdown("#### ❓ 請回答下列問題：")
            for sub in res.get("sub_questions", []):
                st.write(f"- **{sub}**")

            with st.expander("🔍 查看命題核心爭點與評分指標"):
                for cr in res.get("core_issues", []):
                    st.write(f"- {cr}")
                st.info(f"**命題要點與得分關鍵：**\n{res.get('scoring_criteria', '')}")

            full_q_text = f"【案例事實】：\n{res.get('question_facts', '')}\n\n【問題】：\n" + "\n".join(res.get("sub_questions", []))

            cq_col1, cq_col2 = st.columns(2)
            with cq_col1:
                if st.button("🏆 生成榜首級示範擬答 (IRAC 三段論法)", type="primary"):
                    with st.spinner("榜首法學講座名師正在撰寫嚴謹三段論法擬答..."):
                        gen = LawExamGenerator()
                        ans = gen.generate_model_answer(question=full_q_text, subject=subject)
                        st.markdown("### 🏆 閱卷高分示範擬答：")
                        st.markdown(ans)
            with cq_col2:
                if st.button("📝 一鍵將此題直接帶入【試卷評分】批改"):
                    st.session_state["question_text_content"] = full_q_text
                    st.session_state["imported_from_bank_label"] = f"【AI 客製模擬考題 - {subject}】"
                    st.session_state["app_mode"] = "📝 試卷評分與手寫辨識 (手寫/PDF/Word)"
                    st.rerun()

# ----------------- 模式 3: 歷年真題庫檢索 -----------------
elif app_mode == MODE_BANK or app_mode == "📚 歷年真題庫檢索與模擬演練 (法研所 / 轉學考 / 司法官律師 / 司法特考)":
    st.header("📚 全台法學歷年真題庫與名師講義精華檢索")

    comm_q_all = load_community_questions()
    drive_questions = [x for x in drive_notes if x.get("doc_nature") == "question"]
    m3_tab1, m3_tab2, m3_tab3, m3_tab4 = st.tabs([
        "🏛️ 考選部與臺大法研/轉學考歷年真題庫",
        "🎓 大學名師講義與課輔爭點知識庫 (190+ 份各科講義與簡報)",
        f"🎯 雲端實戰試題大庫與百題爭點 ({len(drive_questions)} 份・含民法百題/期中考/考古題)",
        f"👥 社群考生共享真題庫與自創模擬試卷 ({len(comm_q_all)} 題)"
    ])

    with m3_tab1:
        st.write("已收錄國立臺灣大學法研所碩士班、臺大轉學考、考選部司法官律師及司法特考等歷年真實試題，支援在線研讀、AI 擬答與變形出題！")

        crawler = LawExamBankCrawler()
        catalog = crawler.catalog

        if not catalog:
            st.warning("題庫中目前尚無試卷，點擊下方按鈕即可立即從臺大與考選部爬取試題！")
            if st.button("🚀 立即爬取國立大學法研所與公職真題"):
                with st.spinner("正在爬取並下載試卷中..."):
                    crawler.run_all(max_pages=2)
                    st.rerun()
        else:
            # 篩選列
            scol1, scol2, scol3, scol4 = st.columns(4)

            all_categories = ["全部類別"] + sorted(list(set(x.get("category", "") for x in catalog if x.get("category"))))
            all_schools = ["全部學校/機構"] + sorted(list(set(x.get("school", "") for x in catalog if x.get("school"))))
            all_years = ["全部年度"] + sorted(list(set(str(x.get("year", "")) for x in catalog if x.get("year"))), reverse=True)

            with scol1:
                sel_cat = st.selectbox("考試類別：", all_categories)
            with scol2:
                sel_school = st.selectbox("學校 / 機構：", all_schools)
            with scol3:
                sel_year = st.selectbox("考試年度：", all_years)
            with scol4:
                search_kw = st.text_input("搜尋科目/關鍵字：", placeholder="例如：民法、刑法、憲法、行政法...")

            # 篩選邏輯
            filtered = catalog
            if sel_cat != "全部類別":
                filtered = [x for x in filtered if x.get("category") == sel_cat]
            if sel_school != "全部學校/機構":
                filtered = [x for x in filtered if x.get("school") == sel_school]
            if sel_year != "全部年度":
                filtered = [x for x in filtered if str(x.get("year")) == sel_year]
            if search_kw.strip():
                kw = search_kw.strip().lower()
                filtered = [x for x in filtered if kw in x.get("subject", "").lower() or kw in x.get("department", "").lower() or kw in x.get("exam_text", "").lower()]

            st.caption(f"共檢索到 **{len(filtered)}** 份試卷（題庫總計收錄 {len(catalog)} 份）：")

            for idx, item in enumerate(filtered[:30], 1): # 每次顯示前 30 筆
                e_id = item.get("exam_id", f"exam_{idx}")
                yr = item.get("year", "")
                sch = item.get("school", "")
                cat = item.get("category", "")
                dept = item.get("department", "")
                subj = item.get("subject", "")
                text = item.get("exam_text", "")
                pdf_url = item.get("pdf_url", "")

                with st.expander(f"📄 [{yr}年] {sch} - {dept} ｜ 【{subj}】 ({cat})"):
                    st.markdown(f"**考試科目**：{subj} ｜ **系所組別**：{dept} ｜ **年度**：{yr} ｜ **官方連結**：[點此檢視原始試卷]({pdf_url})")
                    st.divider()

                    # 試題內容
                    st.markdown("#### 試題內容：")
                    st.write(text)

                    # 若文字較短（如掃描影像），提供 OCR 按鈕
                    if "[試題掃描檔" in text or len(text) < 100:
                        if st.button(f"🔍 啟動 Gemini 視覺神經網路轉錄試題文字", key=f"ocr_btn_{e_id}"):
                            with st.spinner("正在使用 Gemini 多模態模型進行試卷高精確辨識..."):
                                ocr_res = crawler.ocr_exam_by_id(e_id)
                                if ocr_res:
                                    st.success("辨識謄錄成功！")
                                    st.write(ocr_res)
                                    text = ocr_res

                    # 操作按鈕列：一鍵帶入試卷評分、生成擬答、變形出題
                    bcol1, bcol2, bcol3 = st.columns([1.5, 1.3, 1.2])
                    with bcol1:
                        if st.button(f"📝 一鍵將此題直接帶入【試卷評分】批改", type="primary", key=f"send_eval_btn_{e_id}"):
                            final_q = text
                            if "[試題掃描檔" in final_q or len(final_q.strip()) < 100:
                                with st.spinner("正在自動轉錄試卷完整題目文字..."):
                                    ocr_text = crawler.ocr_exam_by_id(e_id)
                                    if ocr_text:
                                        final_q = ocr_text

                            st.session_state["question_text_content"] = final_q.strip()
                            st.session_state["imported_from_bank_label"] = f"[{yr}年] {sch} - {dept} ｜ 【{subj}】"
                            st.session_state["app_mode"] = "📝 試卷評分與手寫辨識 (手寫/PDF/Word)"
                            st.rerun()

                    with bcol2:
                        if st.button(f"💡 榜首示範擬答 (IRAC)", key=f"ans_btn_{e_id}"):
                            with st.spinner("法學大模型正在為本真題撰寫上位卷完美擬答..."):
                                gen = LawExamGenerator()
                                model_ans = gen.generate_model_answer(question=text, subject=subj)
                                st.markdown("### 🏆 示範擬答全文：")
                                st.markdown(model_ans)

                    with bcol3:
                        if st.button(f"🎯 變形出題演練", key=f"remake_btn_{e_id}"):
                            with st.spinner("正在將本題核心法理演繹為司律一試測驗題..."):
                                gen = LawExamGenerator()
                                remake_res = gen.generate_stage1_exam(
                                    subject=subj,
                                    topic=f"改編自{yr}年{sch}{dept}真題",
                                    count=3,
                                    notes_content=text
                                )
                                st.success("已成功由真題衍生出 3 題模擬選擇題！")
                                st.json(remake_res.get("questions"))

    with m3_tab2:
        st.write("已收錄各名校法學教授與課輔名師之完整體系講義（民總、債總、債各、身分法、刑總、刑分、憲法、民事訴訟法、商事法、保險法、專利法、法理學、國民法官法等），支援全文關鍵字檢索、主題研讀與客製命題！")

        cw_file = Path(RAW_DATA_DIR) / "academic_coursework_index.json"
        if not cw_file.exists():
            st.info("💡 名師講義索引庫建置中，稍候即會自動呈現。")
        else:
            try:
                with open(cw_file, "r", encoding="utf-8") as f_cw_idx:
                    cw_items = json.load(f_cw_idx)

                cw_col1, cw_col2 = st.columns([1, 2])
                with cw_col1:
                    all_cw_subs = ["全部考科"] + sorted(list(set(c.get("subject", "") for c in cw_items if c.get("subject"))))
                    sel_cw_sub = st.selectbox("學門考科：", all_cw_subs, key="m3_cw_sub")
                with cw_col2:
                    cw_kw = st.text_input("搜尋講義名稱或爭點關鍵字：", placeholder="例如：許恒達、意思表示、錯誤論、王皇玉、保險利益...", key="m3_cw_kw")

                filtered_cw = cw_items
                if sel_cw_sub != "全部考科":
                    filtered_cw = [c for c in filtered_cw if c.get("subject") == sel_cw_sub]
                if cw_kw.strip():
                    kw_lower = cw_kw.strip().lower()
                    filtered_cw = [c for c in filtered_cw if kw_lower in c.get("filename", "").lower() or kw_lower in c.get("summary_preview", "").lower()]

                st.caption(f"共檢索到 **{len(filtered_cw)}** 份名師講義（講義庫收錄總計 {len(cw_items)} 份）：")

                for c_idx, cw in enumerate(filtered_cw[:30], 1):
                    fname = cw.get("filename", "")
                    fsub = cw.get("subject", "")
                    fchars = cw.get("char_count", 0)
                    fprev = cw.get("summary_preview", "")
                    frel = cw.get("relative_path", "")

                    with st.expander(f"📖 【{fsub}】{fname} ｜ (收錄 {fchars:,} 字)"):
                        st.markdown(f"**考科領域**：{fsub} ｜ **相對路徑**：`{frel}` ｜ **字元數**：{fchars:,}")
                        st.divider()
                        st.markdown("#### 講義核心重點與爭點摘要：")
                        st.write(fprev)

                        cwb1, cwb2, cwb3 = st.columns([1.5, 1.2, 1.2])
                        with cwb1:
                            if st.button(f"📝 一鍵將此講義案例帶入【試卷評分】批改", type="primary", key=f"cw_btn_eval_{c_idx}"):
                                st.session_state["question_text_content"] = fprev.strip()
                                st.session_state["imported_from_bank_label"] = f"名師講義爭點案例：【{fsub}】{fname}"
                                st.session_state["app_mode"] = "📝 試卷評分與手寫辨識 (手寫/PDF/Word)"
                                st.rerun()
                        with cwb2:
                            if st.button(f"🎲 依此爭點生成一試測驗 (3 題)", key=f"cw_btn_mcq_{c_idx}"):
                                with st.spinner("正在基於名師講義核心爭點出題中..."):
                                    gen = LawExamGenerator()
                                    mcq_res = gen.generate_stage1_exam(
                                        subject=fsub,
                                        topic=f"名師講義演練：{fname[:30]}",
                                        count=3,
                                        notes_content=fprev
                                    )
                                    reset_stage1_exam_state()
                                    st.session_state["stage1_exam_data"] = mcq_res
                                    st.success("一試測驗題生成成功！可至「🎯 司律模擬出題」模式開始作答。")
                        with cwb3:
                            if st.button(f"✍️ 命題二試申論題", key=f"cw_btn_essay_{c_idx}"):
                                with st.spinner("正在基於名師講義爭點設計實例題..."):
                                    gen = LawExamGenerator()
                                    essay_res = gen.generate_stage2_exam(
                                        subject=fsub,
                                        topic=f"名師講義案例：{fname[:30]}",
                                        notes_content=fprev
                                    )
                                    st.session_state["stage2_exam_data"] = essay_res
                                    st.success("二試實例題生成成功！可至「🎯 司律模擬出題」模式查看或生成擬答。")
            except Exception as cwe:
                st.error(f"講義庫讀取異常: {cwe}")

    with m3_tab3:
        st.markdown(f"#### 🎯 雲端實戰試題大庫與百題爭點演練庫（共收錄 {len(drive_questions)} 份試題檔案）")
        st.caption("此處收錄法學資料庫中完整的各科實例試題（包含民法總則百題爭點系列、大學期中/期末考模擬題、課輔實例演練題），已與個人筆記嚴格區隔：")

        q_subs_m3 = ["全部考科"] + sorted(list(set(x["subject"] for x in drive_questions)))
        c_m3_s1, c_m3_s2 = st.columns([1, 2])
        with c_m3_s1:
            sel_m3_q_sub = st.selectbox("試題考科篩選：", q_subs_m3, key="sel_m3_drive_q_sub")
        with c_m3_s2:
            m3_q_kw = st.text_input("搜尋試題檔名或關鍵字（如：百題、期中、模擬試題、身分法）：", key="inp_m3_q_kw")

        filtered_m3_qs = [x for x in drive_questions if (sel_m3_q_sub == "全部考科" or x["subject"] == sel_m3_q_sub) and (not m3_q_kw or m3_q_kw.lower() in x["filename"].lower())]
        st.caption(f"共篩選出 **{len(filtered_m3_qs)}** 份實戰試題：")

        for m3_q_idx, m3_q in enumerate(filtered_m3_qs):
            m3_q_tag = m3_q.get("tag", "【實戰試題】")
            m3_q_fn = m3_q["filename"]
            with st.expander(f"🎯 `{m3_q_tag}` 【{m3_q['subject']}】{m3_q_fn} ({m3_q.get('size_mb', 0)} MB)"):
                st.caption(f"檔案路徑：`{m3_q['path']}`")
                c_m3_b1, c_m3_b2, c_m3_b3 = st.columns(3)
                with c_m3_b1:
                    if st.button(f"📝 帶入【試卷評分】作答", key=f"btn_m3_eval_{m3_q_idx}", use_container_width=True):
                        with st.spinner("正在提取試題文字..."):
                            q_txt = read_note_text(m3_q["path"], max_pages=10, auto_ocr=True)
                            st.session_state["question_text_content"] = q_txt if q_txt else f"【實戰試題】：{m3_q_fn}"
                            st.session_state["imported_from_bank_label"] = f"{m3_q_tag}《{m3_q_fn}》"
                            st.session_state["app_mode"] = "📝 試卷評分與手寫辨識 (手寫/PDF/Word)"
                            st.rerun()
                with c_m3_b2:
                    if st.button(f"🏆 一鍵生成高分示範擬答", key=f"btn_m3_ans_{m3_q_idx}", use_container_width=True):
                        with st.spinner("正在讀取試題並生成二試上位卷 IRAC 示範擬答..."):
                            q_txt = read_note_text(m3_q["path"], max_pages=10, auto_ocr=True)
                            gen = LawExamGenerator()
                            model_ans = gen.generate_model_answer(question=q_txt or m3_q_fn, subject=m3_q["subject"])
                            st.markdown("##### 🏆 閱卷高分示範擬答：")
                            st.markdown(model_ans)
                with c_m3_b3:
                    if st.button(f"🔍 帶入法學檢索樞紐剖析爭點", key=f"btn_m3_query_{m3_q_idx}", use_container_width=True):
                        target_query = f"{m3_q['subject']} {m3_q_fn} 實戰考點與實務見解"
                        st.session_state["lp_search_query"] = target_query
                        st.session_state["lp_exec_search"] = True
                        st.session_state["ai_query_input_text"] = target_query
                        st.session_state["m5_sub_mode_idx"] = 1
                        st.session_state["app_mode"] = mode_options[4]
                        st.rerun()

    with m3_tab4:
        st.markdown(f"#### 👥 全民社群考生共享真題與自創模擬題庫（共收錄 {len(comm_q_all)} 份獨立檔案）")
        st.caption("所有考生在【試卷評分】或【出題系統】中上傳、產出之實戰題目，均即時獨立存檔並自動匯聚於此，供所有考生共同切磋與演練！")

        cq_top1, cq_top2 = st.columns([3, 1])
        with cq_top1:
            cq_kw = st.text_input("搜尋社群題目關鍵字、考科或爭點：", placeholder="例如：侵權行為、抵押權、原因自由行為、董事責任...", key="cq_search_kw")
        with cq_top2:
            st.write("")
            st.write("")
            add_new_q_exp = st.checkbox("➕ 手動新增共享題目", key="chk_add_comm_q")

        if add_new_q_exp:
            with st.container():
                st.markdown("##### ➕ 貢獻一道新題目至社群共享庫")
                n_title = st.text_input("試卷標題 / 考點摘要：", placeholder="例如：112年司律二試民法第一題改編")
                n_subj = st.selectbox("所屬科目：", ["民法", "民事訴訟法", "刑法", "刑事訴訟法", "行政法", "憲法", "公司法", "證券交易法", "保險法", "智慧財產權法", "勞動與社會法", "跨領域綜合"], key="n_subj_select")
                n_content = st.text_area("題目事實與子題內容：", height=120, placeholder="案例事實與問題...")
                n_rubric = st.text_area("參考答案 / 評分標準（選填）：", height=70)
                if st.button("📤 立即上傳並建立獨立題庫檔案", key="btn_save_new_comm_q"):
                    if n_content.strip():
                        new_q_rec = archive_uploaded_question(title=n_title, content=n_content, subject=n_subj, rubric=n_rubric, uploader="熱心考生")
                        st.success(f"🎉 成功存檔並建立試題：`{new_q_rec.get('question_id')}.json`！已同步匯入社群題庫！")
                        st.rerun()
                    else:
                        st.error("請填寫題目內容！")

        comm_filtered = comm_q_all
        if cq_kw:
            comm_filtered = search_community_questions(cq_kw)

        if not comm_filtered:
            st.info("💡 目前社群題庫暫無符合條件之試卷。在【試卷評分】模式評分題目後，系統將實時為您獨立存檔入庫！")
        else:
            st.caption(f"共顯示 **{len(comm_filtered)}** 道社群共享試題：")
            for cq_idx, q_item in enumerate(comm_filtered):
                q_id = q_item.get("question_id", f"comm_q_{cq_idx}")
                q_title = q_item.get("title", "未命名題目")
                q_subj = q_item.get("subject", "跨領域")
                q_uploader = q_item.get("uploader", "社群考生")
                q_time = q_item.get("created_at", "")
                q_text = q_item.get("content", "")
                q_rubric = q_item.get("rubric", "")

                with st.expander(f"📝 【{q_subj}】{q_title} ｜ 👤 {q_uploader} ｜ 📅 {q_time}"):
                    st.caption(f"題目獨立編號：`{q_id}.json` ｜ 字數：{len(q_text)} 字")
                    st.markdown("#### 📜 試題內容：")
                    st.write(q_text)
                    if q_rubric:
                        with st.expander("🔍 檢視出題者提供之評分要點/參考答案"):
                            st.info(q_rubric)

                    c_act1, c_act2 = st.columns(2)
                    with c_act1:
                        if st.button(f"📝 帶入【試卷評分】進行批改", key=f"btn_import_eval_{q_id}"):
                            st.session_state["question_text_content"] = q_text
                            st.session_state["rubric_text_content"] = q_rubric
                            st.session_state["imported_from_bank_label"] = f"【社群共享題庫】{q_title}"
                            st.session_state["app_mode"] = "📝 試卷評分與手寫辨識 (手寫/PDF/Word)"
                            st.rerun()
                    with c_act2:
                        if st.button(f"🏆 生成榜首級示範擬答 (IRAC)", key=f"btn_model_ans_{q_id}"):
                            with st.spinner("榜首名師正在撰寫嚴謹三段論法擬答..."):
                                gen = LawExamGenerator()
                                m_ans = gen.generate_model_answer(question=q_text, subject=q_subj)
                                st.markdown("##### 🏆 閱卷高分示範擬答：")
                                st.markdown(m_ans)

# ----------------- 模式 4: 擬答生成 -----------------
elif app_mode == MODE_ANS or app_mode == "📖 高分權威擬答生成":
    st.header("📖 司律二試 - 高分示範擬答生成器")
    st.write("針對二試爭議題目，自動撰寫具備榜首水準的開標、大前提、實務學說對比與事實涵攝完美擬答。支援直接貼入文字，或拍照、上傳試卷 PDF/Word 自動轉錄！")

    m4_input_mode = st.radio(
        "題目提供方式：",
        ["📝 直接貼上文字", "📸 拍照或上傳試卷檔案 (JPG/PNG/PDF/Word)"],
        horizontal=True,
        key="m4_input_mode_radio"
    )

    if "m4_target_question" not in st.session_state:
        st.session_state["m4_target_question"] = ""

    # 若由真題庫帶入，優先使用
    if "question_text_content" in st.session_state and st.session_state["question_text_content"]:
        if not st.session_state["m4_target_question"]:
            st.session_state["m4_target_question"] = st.session_state["question_text_content"]
            st.session_state["m4_text_area_input"] = st.session_state["question_text_content"]
    elif st.session_state.get("m4_target_question") and "m4_text_area_input" not in st.session_state:
        st.session_state["m4_text_area_input"] = st.session_state["m4_target_question"]

    if "📸" in m4_input_mode:
        m4_up_file = st.file_uploader(
            "請上傳二試申論題題目檔案（支援手機拍照圖、PDF 試卷或 Word 題稿）：",
            type=["png", "jpg", "jpeg", "webp", "pdf", "docx"],
            key="m4_question_file_uploader"
        )
        if m4_up_file is not None:
            st.info(f"📄 已選擇檔案：`{m4_up_file.name}` ({len(m4_up_file.getvalue()) / (1024*1024):.2f} MB)")
            if st.button("🔍 辨識並自動帶入題目文字", key="btn_m4_ocr"):
                with st.spinner("正在使用 Gemini Flash 多模態神經網路自動辨識並轉錄題目全文..."):
                    try:
                        ext = m4_up_file.name.split(".")[-1].lower()
                        transcribed = ""
                        if ext in ["png", "jpg", "jpeg", "webp"]:
                            from PIL import Image
                            img = Image.open(m4_up_file)
                            from evaluator import LawExamEvaluator
                            ev = LawExamEvaluator()
                            if hasattr(ev, "client") and ev.client:
                                prompt = "請將此張試卷照片或截圖中的完整題目文字逐字謄錄為繁體中文，保持原本標號、事實情境與子題配分。直接輸出題目文字，勿加入額外寒暄。"
                                from config import get_gemini_models_to_try
                                r = None
                                for m_ocr in get_gemini_models_to_try():
                                    try:
                                        r = ev.client.models.generate_content(
                                            model=m_ocr,
                                            contents=[img, prompt]
                                        )
                                        if r and r.text:
                                            break
                                    except Exception:
                                        continue
                                if r and r.text:
                                    transcribed = r.text.strip()
                                else:
                                    transcribed = "[無法調用視覺模型辨識圖片，請確認 API Key 與模型設定]"
                            else:
                                transcribed = "[無法調用視覺模型，請確認 API Key]"
                        elif ext == "pdf":
                            import pdfplumber, io
                            with pdfplumber.open(io.BytesIO(m4_up_file.getvalue())) as p:
                                p_text = "\n".join([page.extract_text() or "" for page in p.pages]).strip()
                            if len(p_text) >= 50:
                                transcribed = p_text
                            else:
                                from ingest_user_notes_to_sft import read_note_text
                                import tempfile
                                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                                    tf.write(m4_up_file.getvalue())
                                    tf_path = Path(tf.name)
                                transcribed = read_note_text(tf_path, max_pages=5, auto_ocr=True)
                        elif ext == "docx":
                            from docx import Document
                            import io
                            doc = Document(io.BytesIO(m4_up_file.getvalue()))
                            transcribed = "\n".join([p.text for p in doc.paragraphs if p.text.strip()]).strip()

                        if transcribed:
                            st.session_state["m4_target_question"] = transcribed
                            st.session_state["m4_text_area_input"] = transcribed
                            st.success("✅ 題目辨識並謄錄成功！已自動帶入下方編輯框：")
                        else:
                            st.warning("未能從上傳檔案中提取到題目文字。")
                    except Exception as e:
                        st.error(f"題目解析失敗: {e}")

    col_m4_sub, col_m4_clear = st.columns([3, 1])
    with col_m4_sub:
        m4_subject = st.selectbox(
            "考科領域（有助模型精準鎖定最新裁判與實務爭點）：",
            [
                "民法與民事訴訟法 (含家事、強制執行)",
                "民事實體法 (民法總則/債編/物權/身分法)",
                "民事程序法 (民事訴訟法/家事事件法/強制執行法)",
                "刑法與刑事訴訟法 (含特別刑法、國民法官法)",
                "刑法 (總則/分則/貪污洗錢特別刑法)",
                "刑事訴訟法 (強制處分/證據法則/通常審判)",
                "憲法與行政法 (公法全領域綜合實例題)",
                "憲法與憲法訴訟法 (基本權審查/裁判憲法審查)",
                "行政法 (程序法/行政罰法/行政爭訟/國家賠償法)",
                "公司法、保險法與證券交易法 (商事法綜合)",
                "公司法與證券交易法",
                "保險法與票據法",
                "智慧財產權法與營業秘密 (專利/商標/著作權)",
                "勞動基準法與社會法 (勞動契約/解僱/工會/職災)",
                "財稅法與納稅者權利保護法",
                "公平交易法",
                "國際私法與涉外民商事事件",
                "海商法與海洋法",
                "其他法學綜合實例題"
            ],
            key="m4_subject_select"
        )
    with col_m4_clear:
        if st.button("✖️ 清空題目", key="btn_m4_clear"):
            st.session_state["m4_target_question"] = ""
            st.session_state["m4_text_area_input"] = ""
            st.rerun()

    target_q = st.text_area(
        "請確認申論題題目（可直接修改或補充）：",
        value=st.session_state.get("m4_target_question", ""),
        height=200,
        placeholder="請貼入完整的二試題目，或由上方拍照/上傳自動辨識帶入...",
        key="m4_text_area_input"
    )

    if st.button("✨ 生成極致高分擬答", type="primary"):
        if not target_q.strip():
            st.warning("請先輸入或上傳題目！")
        else:
            with st.spinner(f"法學大模型正在為【{m4_subject}】撰寫具備榜首水準的開標、大前提、實務學說對比與事實涵攝完美擬答..."):
                try:
                    gen = LawExamGenerator()
                    ans = gen.generate_model_answer(question=target_q, subject=m4_subject)
                    st.markdown("### 🏆 示範擬答全文 (IRAC)：")
                    st.markdown(ans)
                    st.divider()
                    if st.button("📝 將此題與示範擬答帶入【試卷評分】批改 (自動帶入題目與評分標準)"):
                        st.session_state["question_text_content"] = target_q
                        st.session_state["rubric_text_content"] = ans
                        st.session_state["imported_from_bank_label"] = f"二試申論題【{m4_subject}】（含榜首示範擬答標準）"
                        st.session_state["app_mode"] = "📝 試卷評分與手寫辨識 (手寫/PDF/Word)"
                        st.rerun()
                except Exception as e:
                    st.error(f"出題失敗: {e}")

# ----------------- 模式 5: 統一法學檢索樞紐與 AI 判決研析 (布林檢索・多庫矩陣・爭點大典) -----------------
elif app_mode == MODE_SEARCH or "統一法學檢索" in app_mode or "爭點查詢" in app_mode or "統一法學檢索" in app_mode or "爭點速查" in app_mode:
    st.header("🔍 統一法學檢索樞紐與 AI 判決深度研析中心")
    st.caption("全面整合【專業布林邏輯精準檢索】、【全方位法學統一檢索】、【AI 判決精華深度摘要】與【案例橫向比對 (Case Distinguishing)】，直通審級脈絡、權威法學庫與司法院 30 年判決，支援一站式爭點與判解秒級研析。")

    st.divider()

    m5_sub_modes = [
        "⚖️ 專業級 裁判書多維專業檢索 (支援布林語法)",
        "⚡ 極速全域熱搜 極速熱搜與全國資料庫矩陣",
        "🌿 審級更迭與歷審脈絡鏈 (JudgementChain 審級溯源專區)",
        "🤖 AI 智慧爭點深度剖析與二試上位卷 IRAC 大典",
        "🔄 案例橫向比對與實務分歧研析 (Case Distinguishing)"
    ]

    # 外部跳轉控制預設子功能索引
    sub_default_idx = st.session_state.get("m5_sub_mode_idx", 0)
    if sub_default_idx >= len(m5_sub_modes):
        sub_default_idx = 0

    m5_active_tab = st.radio(
        "選擇法學研析模組：",
        m5_sub_modes,
        index=sub_default_idx,
        horizontal=True,
        key="m5_sub_module_radio"
    )
    st.session_state["m5_sub_mode_idx"] = m5_sub_modes.index(m5_active_tab)

    st.write("")

    # ==================== 子功能 1: ⚖️ 專業級 裁判書多維專業檢索 (LegalDatabase 規格) ====================
    if m5_active_tab == m5_sub_modes[0]:
        st.subheader("⚖️ 權威法學資料庫 規格裁判書多維專業檢索系統")
        st.caption("完整比照「權威法學資料庫」專業裁判書查詢規格，支援布林邏輯運算（＆、＋、－、( )），與法院體系、民國年度 (jud_year)、常用字別 (sel_judword)、裁判案號 (jud_no)、裁判案由 (jt)、主文/心證 (jmain/txtopinion)、案件爭點 (txtargument)、相關法條 (lc1a/lc1b) 全維度交叉篩選。")

        # 專業檢索表單
        col_c1, col_c2 = st.columns([1.5, 1])
        with col_c1:
            court_opts = list(COURTS_TAXONOMY.keys())
            cur_court = st.session_state.get("lb_court_system", court_opts[0])
            cur_court_idx = court_opts.index(cur_court) if cur_court in court_opts else 0
            sel_court = st.selectbox("1. 🏛️ 法院體系與審級選單：", court_opts, index=cur_court_idx, key="lb_court_system")
        with col_c2:
            sel_case_type = st.radio("2. ⚖️ 裁判與實務見解類別：", ["全部", "判決", "裁定", "原判例", "最高院/最高行決議", "高院法律座談會", "憲法裁判/大法官解釋"], horizontal=True, key="lb_case_type")

        # 裁判字號組合器 (jud_year, sel_judword, jud_no)
        st.markdown("**3. 🔖 裁判字號精準組合器（支援案號縮寫，如：108台上908民、108台上大1719裁、院字2949、重上更一15）：**")
        w_c1, w_c2, w_c3, w_c4 = st.columns([1, 1.4, 1.4, 1.2])
        with w_c1:
            val_yr = st.session_state.get("lb_input_year", "")
            lb_year = st.text_input("民國年 (jud_year)：", value=val_yr, placeholder="例：108", key="lb_input_year")
        with w_c2:
            val_wd_sel = st.session_state.get("lb_sel_jword", COMMON_CASE_WORDS[0])
            sel_idx = COMMON_CASE_WORDS.index(val_wd_sel) if val_wd_sel in COMMON_CASE_WORDS else 0
            sel_jword_choice = st.selectbox("常用字別下拉 (sel_judword)：", COMMON_CASE_WORDS, index=sel_idx, key="lb_sel_jword")
        with w_c3:
            default_w = sel_jword_choice if sel_jword_choice != "全部字別 (不限)" else st.session_state.get("lb_input_word", "")
            lb_word = st.text_input("字別文字 (可自訂)：", value=default_w, placeholder="例：台上大、憲判", key="lb_input_word")
        with w_c4:
            val_no = st.session_state.get("lb_input_num", "")
            lb_num = st.text_input("裁判案號 (jud_no)：", value=val_no, placeholder="例：1719", key="lb_input_num")

        # 專業四大實體法學檢索欄位
        st.markdown("**4. ⚖️ 專業四大實體法學檢索欄位：**")
        m_c1, m_c2 = st.columns(2)
        with m_c1:
            val_cs = st.session_state.get("lb_input_cause", "")
            lb_cause = st.text_input("📌 裁判案由 (jt)：", value=val_cs, placeholder="例如：損害賠償、確認借名登記關係存在、違反毒品危害防制條例...", key="lb_input_cause")
            val_op = st.session_state.get("lb_input_opinion", "")
            lb_opinion = st.text_input("⚖️ 裁判主文 / 法院心證 (jmain / txtopinion)：", value=val_op, placeholder="例如：有權處分、純經濟損失、重大過失、注意義務...", key="lb_input_opinion")
        with m_c2:
            val_arg = st.session_state.get("lb_input_arg", "")
            lb_argument = st.text_input("🎯 案件爭點 / 當事人主張 (txtargument)：", value=val_arg, placeholder="例如：借名登記出名人擅自處分、臨檢救濟、特別災難失蹤期間...", key="lb_input_arg")
            val_st = st.session_state.get("lb_input_statute", "")
            lb_statute = st.text_input("📜 相關法條 (lc1a / lc1b)：", value=val_st, placeholder="例如：民法第184條、保險法第64條、憲法第8條...", key="lb_input_statute")

        # 5. 審級脈絡時間軸過濾滑桿 (JudgementChain 考點定位)
        st.markdown("**5. 🌿 審級脈絡時間軸過濾滑桿 (JudgementChain 考點定位)：**")
        lb_time_filter = st.select_slider(
            "依裁判年份深度篩選（鎖定最新考點、大法庭定錨黃金期或全集檢索）：",
            options=JUDICIAL_TIME_RANGES,
            value=st.session_state.get("lb_time_filter", "全部時間 (不限年份)"),
            key="lb_select_time_filter"
        )

        # 檢索與重設按鈕
        col_btn_search, col_btn_clear = st.columns([3, 1])
        with col_btn_search:
            btn_exec_lb = st.button("🚀 執行專業多維度精準檢索", type="primary", use_container_width=True, key="btn_exec_adv_prec_search")
        with col_btn_clear:
            if st.button("✖️ 清除檢索條件", use_container_width=True, key="btn_clear_lb_all"):
                for k in ["lb_court_system", "lb_input_year", "lb_sel_jword", "lb_input_word", "lb_input_num", "lb_input_cause", "lb_input_opinion", "lb_input_arg", "lb_input_statute", "lb_select_time_filter", "lb_time_filter", "adv_prec_search_results", "lb_did_search"]:
                    st.session_state.pop(k, None)
                st.rerun()

        # 觸發檢索
        do_search = btn_exec_lb or st.session_state.pop("lb_did_search", False)
        if do_search:
            with st.spinner("正在以專業規格多維度檢索本機 3,680+ 筆權威判解庫..."):
                try:
                    results = search_precedents_advanced(
                        court_system=sel_court,
                        jud_year=lb_year,
                        jud_word=lb_word,
                        jud_no=lb_num,
                        case_cause=lb_cause,
                        main_holding=lb_opinion,
                        argument_issue=lb_argument,
                        cited_laws=lb_statute,
                        case_type=sel_case_type,
                        time_filter=lb_time_filter,
                        top_k=50
                    )
                    st.session_state["adv_prec_search_results"] = results
                except Exception as e:
                    st.error(f"專業多維檢索失敗: {e}")

        # 檢索結果展示
        if "adv_prec_search_results" in st.session_state:
            lb_results = st.session_state["adv_prec_search_results"]
            st.divider()
            st.markdown(f"### 📋 專業規格檢索結果清單 (共命中 {len(lb_results)} 筆裁判)")

            first_kw = (lb_word + " " + lb_num).strip() or lb_cause.strip() or lb_statute.strip() or "最高法院"
            ext_urls = generate_judicial_search_urls(first_kw)
            with st.expander("🌐 一鍵將當前條件帶入外部司法資料庫全文檢索", expanded=False):
                e_col1, e_col2, e_col3 = st.columns(3)
                url_items = list(ext_urls.items())
                with e_col1:
                    for lbl, lnk in url_items[:3]:
                        st.link_button(lbl, lnk, use_container_width=True)
                with e_col2:
                    for lbl, lnk in url_items[3:6]:
                        st.link_button(lbl, lnk, use_container_width=True)
                with e_col3:
                    for lbl, lnk in url_items[6:]:
                        st.link_button(lbl, lnk, use_container_width=True)

            if not lb_results:
                # 組合使用者於表單填寫的目標裁判全銜 (若未指定特定法院則不預加'各級法院'虛擬字樣)
                target_court_clean = sel_court.replace("🏛️", "").replace("⚖️", "").strip() if "全部法院" not in sel_court else ""
                target_tail = sel_case_type if sel_case_type != "全部" else ""
                if lb_year and lb_num:
                    target_combo_id = f"{target_court_clean} {lb_year} 年度{lb_word}字第 {lb_num} 號{target_tail}".strip()
                else:
                    target_combo_id = (first_kw or "指定條件裁判").strip()
                ext_direct_urls = generate_judicial_search_urls(target_combo_id)

                st.warning(f"🔍 **本機離線庫未收錄此案全文**：已為您精準組裝標的案號【`{target_combo_id}`】！")
                st.markdown("""
> 💡 **為什麼找不到？**  
> 台灣司法裁判每年產出數十萬筆，本機離線庫主要精選收錄重要大法庭、判例及高頻實務爭點。  
> 為了讓您**「一定找得到」**，系統已為您直接對接官方司法院資料庫，並提供 AI 自動法理延伸推論：
""")
                col_nb1, col_nb2 = st.columns([1.8, 1.2])
                with col_nb1:
                    st.markdown("**🌐 點擊官方直通按鈕，秒級查閱並複製司法院官方全文：**")
                    u_cols = st.columns(min(len(ext_direct_urls), 3))
                    for u_i, (u_lbl, u_lnk) in enumerate(list(ext_direct_urls.items())[:3]):
                        with u_cols[u_i]:
                            # 顯示清晰按鈕文字（不截斷 Emoji）
                            btn_text = u_lbl if len(u_lbl) <= 12 else (u_lbl[:10] + "...")
                            st.link_button(btn_text, u_lnk, use_container_width=True)
                with col_nb2:
                    st.markdown("**⚡ 一鍵轉入 AI 裁判要旨深度精鍊：**")
                    if st.button(f"🚀 將【{target_combo_id[:16]}...】帶入 AI 判解精鍊", type="primary", use_container_width=True, key="btn_pass_m5_to_m7"):
                        st.session_state["sum_citation_search"] = target_combo_id
                        st.session_state["citation_rev"] = st.session_state.get("citation_rev", 0) + 1
                        st.session_state["app_mode"] = mode_options[6]  # 切換至 AI 判解精鍊旗艦
                        st.rerun()
            else:
                for idx, r in enumerate(lb_results):
                    c_id = r.get("case_id", "")
                    court = r.get("court", "")
                    lvl = r.get("level", "")
                    tit = r.get("title", "")
                    hold = r.get("holding", "")
                    iss = r.get("issue", "")
                    laws = ", ".join(r.get("laws_cited", []))
                    sch = r.get("scholarly_views", "")
                    hint = r.get("exam_application_hint", "")

                    with st.expander(f"⚖️ 【{lvl or court}】`{c_id}` ｜ {tit[:35]}", expanded=(idx < 3)):
                        st.markdown(f"**🏛️ 管轄法院：** `{court}` ｜ **審級位階：** `{lvl}` ｜ **案件案由：** `{tit}`")
                        if laws:
                            st.caption(f"📜 **涉及法規：** {laws}")
                        st.info(f"**【裁判主文與要旨心證】：**\n{hold}")
                        if iss:
                            st.markdown(f"**🎯 案件核心爭點：** {iss}")
                        if sch:
                            st.caption(f"📚 **學說實務對比：** {sch}")
                        if hint:
                            st.success(f"✍️ **國考作答提示：** {hint}")

                        b_c1, b_c2, b_c3, b_c4, b_c5 = st.columns([1.5, 1.4, 1.4, 1.0, 1.0])
                        with b_c1:
                            if st.button("🌿 審級更迭脈絡", key=f"btn_lb_hist_{idx}", use_container_width=True):
                                st.session_state["target_history_case_id"] = c_id
                                st.session_state["m5_sub_mode_idx"] = 2
                                st.rerun()
                        with b_c2:
                            if st.button("⚡ AI 判解精鍊", key=f"btn_lb_sum_{idx}", use_container_width=True):
                                st.session_state["sum_citation_search"] = c_id
                                st.session_state["citation_rev"] = st.session_state.get("citation_rev", 0) + 1
                                st.session_state["app_mode"] = mode_options[6]
                                st.rerun()
                        with b_c3:
                            if st.button("🔄 案例橫向比對", key=f"btn_lb_cmp_{idx}", use_container_width=True):
                                st.session_state["target_compare_case_a"] = c_id
                                st.session_state["m5_sub_mode_idx"] = 4
                                st.rerun()
                        with b_c4:
                            st.link_button("🏛️ 司法院判決直查", f"https://judgment.judicial.gov.tw/FJUD/default.aspx?k={c_id}", use_container_width=True)
                        with b_c5:
                            st.link_button("⚖️ 司法院法學檢索", "https://jirs.judicial.gov.tw/Index.aspx", use_container_width=True)

    # ==================== 子功能 2: ⚡ 極速全域熱搜 極速熱搜與全國資料庫矩陣 ====================
    elif m5_active_tab == m5_sub_modes[1]:
        st.subheader("⚡ 極速全域熱搜 極速熱搜與全國法學資料庫矩陣")
        st.caption("支援高頻爭點晶片快選、雙向自然語言搜尋、案號縮寫智慧解析、本機 3,680+ 筆裁判與六法法條即時命中，並跨庫直通官方權威司法檢索系統！")

        # 極速全域搜尋列
        cur_lp_val = st.session_state.get("lp_search_query", "")
        lp_query_input = st.text_input(
            "⚡ 極速全域搜尋框（支援法院簡稱如 最高行110上15、北高行109訴567、案號縮寫如 108台上908民、法條或自然語言案例事實）：",
            value=cur_lp_val,
            placeholder="例如：最高行110上15、北高行109訴567、108台上908民、108台上大1719裁、院字2949、重上更一15、民法184、借名登記...",
            key="lp_search_input"
        )

        # 審級脈絡時間軸過濾滑桿 (JudgementChain Time Filter)
        lp_time_filter = st.select_slider(
            "🌿 審級脈絡時間軸過濾（限定近年判決 / 大法庭黃金期）：",
            options=JUDICIAL_TIME_RANGES,
            value=st.session_state.get("lp_time_filter", "全部時間 (不限年份)"),
            key="lp_select_time_filter"
        )

        col_lp_btn1, col_lp_btn2 = st.columns([3, 1])
        with col_lp_btn1:
            btn_lp_search = st.button("⚡ 啟動法學檢索極速跨庫查找", type="primary", use_container_width=True, key="btn_exec_lp_search")
        with col_lp_btn2:
            if st.button("✖️ 清除搜尋", use_container_width=True, key="btn_clear_lp_search"):
                st.session_state.pop("lp_search_query", None)
                st.session_state.pop("lp_search_hits", None)
                st.session_state.pop("lp_select_time_filter", None)
                st.session_state.pop("lp_time_filter", None)
                st.rerun()

        do_lp_search = btn_lp_search or st.session_state.pop("lp_exec_search", False)
        if do_lp_search:
            target_q = lp_query_input.strip()
            if not target_q:
                st.warning("請先輸入欲搜尋之關鍵字或點擊上方熱搜標籤！")
            else:
                with st.spinner(f"正在全域高速檢索【{target_q}】..."):
                    try:
                        engine = LegalIssueQueryEngine()
                        hits = engine.unified_legal_search(query=target_q, time_filter=lp_time_filter)
                        st.session_state["lp_search_hits"] = hits
                        st.session_state["lp_search_query"] = target_q
                    except Exception as e:
                        st.error(f"法學檢索檢索失敗: {e}")

        # 法學檢索搜尋結果與全國資料庫矩陣
        if "lp_search_hits" in st.session_state:
            hits = st.session_state["lp_search_hits"]
            active_q = hits.get("query", "")
            ext_urls = hits.get("external_urls", {})
            precedents = hits.get("precedents", [])
            articles = hits.get("articles", [])

            st.divider()
            st.subheader(f"⚡ 【{active_q}】全域檢索結果與直連矩陣")

            # 全國法學資料庫矩陣卡片
            if ext_urls:
                st.markdown("#### 🌐 全國 8 大權威法學資料庫一鍵直連矩陣")
                st.caption(f"針對搜尋詞「{active_q}」，點選下方任一系統即可直接調閱外部全文：")
                u_c1, u_c2, u_c3 = st.columns(3)
                u_list = list(ext_urls.items())
                with u_c1:
                    for lbl, lnk in u_list[:3]:
                        st.link_button(lbl, lnk, use_container_width=True)
                with u_c2:
                    for lbl, lnk in u_list[3:6]:
                        st.link_button(lbl, lnk, use_container_width=True)
                with u_c3:
                    for lbl, lnk in u_list[6:]:
                        st.link_button(lbl, lnk, use_container_width=True)

            # 本地裁判命中
            if precedents:
                st.markdown(f"#### 🏛️ 本地權威判解庫即時命中 ({len(precedents)} 筆裁判)")
                for p_idx, mc in enumerate(precedents):
                    c_id = mc.get("case_id", "")
                    lvl = mc.get("level", "")
                    tit = mc.get("title", "")
                    laws = ", ".join(mc.get("laws_cited", []))
                    holding = mc.get("holding", "")

                    with st.expander(f"⚖️ 【{lvl}】`{c_id}` ｜ {tit}", expanded=(p_idx == 0)):
                        if laws:
                            st.caption(f"📌 涉及法規：{laws}")
                        st.info(f"**核心主文 / 判決要旨：**\n{holding}")
                        if mc.get("scholarly_views"):
                            st.caption(f"📚 **學說實務對比：** {mc.get('scholarly_views')}")
                        if mc.get("exam_application_hint"):
                            st.success(f"✍️ **國考作答提示：** {mc.get('exam_application_hint')}")

                        btn_c1, btn_c2, btn_c3, btn_c4, btn_c5 = st.columns([1.5, 1.4, 1.4, 1.0, 1.0])
                        with btn_c1:
                            if st.button(f"🌿 審級更迭脈絡", key=f"btn_lp_hist_{p_idx}", use_container_width=True):
                                st.session_state["target_history_case_id"] = c_id
                                st.session_state["m5_sub_mode_idx"] = 2
                                st.rerun()
                        with btn_c2:
                            if st.button(f"⚡ AI 判解精鍊", key=f"btn_lp_sum_{p_idx}", use_container_width=True):
                                st.session_state["sum_citation_search"] = c_id
                                st.session_state["citation_rev"] = st.session_state.get("citation_rev", 0) + 1
                                st.session_state["app_mode"] = mode_options[6]
                                st.rerun()
                        with btn_c3:
                            if st.button(f"🔄 案例橫向比對", key=f"btn_lp_cmp_{p_idx}", use_container_width=True):
                                st.session_state["target_compare_case_a"] = c_id
                                st.session_state["m5_sub_mode_idx"] = 4
                                st.rerun()
                        with btn_c4:
                            st.link_button("🏛️ 司法院裁判全文", f"https://judgment.judicial.gov.tw/FJUD/default.aspx?k={c_id}", use_container_width=True)
                        with btn_c5:
                            st.link_button("⚖️ 司法院法學檢索", "https://jirs.judicial.gov.tw/Index.aspx", use_container_width=True)

            # 本地法條命中
            if articles:
                with st.expander(f"📜 關聯法條命中 ({len(articles)} 條)", expanded=True):
                    for a in articles:
                        st.markdown(f"**📖 【{a.get('law_name')} 第 {a.get('article_no')} 條】**")
                        st.write(a.get("content", ""))
                        st.markdown("---")

            # 跨功能一鍵跳轉
            st.divider()
            col_jmp1, col_jmp2 = st.columns(2)
            with col_jmp1:
                if st.button("🤖 帶入進行【AI 爭點深度剖析與 IRAC 上位卷示範】", use_container_width=True, type="primary"):
                    st.session_state["ai_query_input_text"] = active_q
                    st.session_state["m5_sub_mode_idx"] = 3
                    st.session_state["ai_query_auto_exec"] = True
                    st.rerun()
            with col_jmp2:
                if st.button("⚖️ 帶入進行【專業多維度細緻檢索】", use_container_width=True):
                    st.session_state["lb_input_cause"] = active_q
                    st.session_state["m5_sub_mode_idx"] = 0
                    st.session_state["lb_did_search"] = True
                    st.rerun()

    # ==================== 子功能 3: 🌿 審級更迭與歷審脈絡鏈 (JudgementChain 審級溯源專區) ====================
    elif m5_active_tab == m5_sub_modes[2]:
        st.subheader("🌿 裁判審級更迭與歷審脈絡鏈 (JudgementChain 審級溯源專區)")
        st.caption("完整比照「審級脈絡溯源系統」獨家專利之『歷審裁判鏈 (Judgement History Pipeline)』！自動溯源地方法院事實審 ➔ 高等法院事實/上訴審 ➔ 最高法院法律審 ➔ 大法庭終局定錨 / 憲法法庭，精準剖析各審級裁判見解之翻轉與定錨、法律攻防爭點、區別對比矩陣與司律二試上位卷 IRAC 開標示範！")



        all_precedents_tags = ["-- 📚 從本機 3,680+ 筆權威庫中挑選裁判 --"] + get_all_precedent_options()
        cur_hist_val = st.session_state.get("target_history_case_id", "最高法院 108 年度台上大字第 1719 號民事大法庭裁定")
        def_hist_idx = 0
        if cur_hist_val:
            for opt_idx, opt in enumerate(all_precedents_tags):
                if cur_hist_val in opt:
                    def_hist_idx = opt_idx
                    break

        sel_prec_hist_tag = st.selectbox(
            "從本機權威裁判庫挑選欲溯源之指標裁判（支援 3,680+ 筆裁判/大法庭/憲判字/高院/筆記地院判決）：",
            all_precedents_tags,
            index=def_hist_idx,
            key="sel_prec_for_history"
        )
        if sel_prec_hist_tag and sel_prec_hist_tag != "-- 📚 從本機 3,680+ 筆權威庫中挑選裁判 --":
            cur_hist_val = sel_prec_hist_tag.split(" ｜ ")[0].strip()

        col_h_in1, col_h_in2 = st.columns([3, 1])
        with col_h_in1:
            inp_hist_case_id = st.text_input(
                "欲進行歷審溯源之裁判案號 / 字號：",
                value=cur_hist_val,
                placeholder="例如：最高法院 108 年度台上大字第 1719 號、111憲判16、109台上大908...",
                key="inp_history_case_id"
            )
        with col_h_in2:
            st.write("")
            st.write("")
            btn_clr_hist = st.button("✖️ 清除脈絡鏈", use_container_width=True, key="btn_clr_hist_chain")
            if btn_clr_hist:
                st.session_state.pop("case_history_result", None)
                st.session_state["target_history_case_id"] = ""
                st.rerun()

        with st.expander("📝 自訂裁判書內文或特定段落補充（選填，若為庫外裁判可貼於此以加強分析）：", expanded=False):
            inp_custom_hist_text = st.text_area(
                "裁判書內文或歷審說明：",
                height=120,
                placeholder="貼上裁判書節錄或事實...",
                key="inp_custom_hist_text"
            )

        btn_start_hist = st.button("🚀 啟動歷審審級溯源與脈絡鏈深度研析", type="primary", use_container_width=True, key="btn_exec_hist_chain")

        do_hist_analysis = btn_start_hist or st.session_state.pop("history_auto_exec", False)
        if do_hist_analysis:
            if not inp_hist_case_id.strip() and not inp_custom_hist_text.strip():
                st.warning("請先輸入裁判案號或貼上裁判文字！")
            else:
                target_hid = inp_hist_case_id.strip() or "自訂裁判"
                with st.spinner(f"正在全域調閱【{target_hid}】之歷審脈絡鏈，解構地院、高院、最高法院與大法庭審級更迭..."):
                    try:
                        engine = LegalIssueQueryEngine()
                        h_res = engine.generate_case_history_timeline(
                            case_id=target_hid,
                            case_text=inp_custom_hist_text
                        )
                        st.session_state["case_history_result"] = h_res
                        st.session_state["target_history_case_id"] = target_hid
                    except Exception as he:
                        st.error(f"歷審脈絡研析失敗: {he}")

        if "case_history_result" in st.session_state:
            h_data = st.session_state["case_history_result"]
            h_md = h_data.get("markdown_result", "")
            h_cid = h_data.get("case_id", "")
            p_info = h_data.get("preset_info")

            st.divider()
            st.subheader(f"🌿 【{h_cid}】裁判審級更迭與歷審脈絡鏈報告")

            # 視覺化審級節點卡片流 (Visual Instance Pipeline Flow)
            stages = (p_info.get("timeline_stages") or p_info.get("chain")) if p_info else None
            if p_info and stages:
                st.markdown(f"#### 🏛️ 審級更迭演進軌跡：【{p_info.get('topic') or p_info.get('title')}】")
                for n_idx, node in enumerate(stages):
                    inst = node.get("stage") or node.get("instance", "")
                    court_name = node.get("court", "")
                    c_no = node.get("case_no", "")
                    holding_txt = node.get("holding_summary") or node.get("holding", "")
                    res_txt = node.get("ruling") or node.get("result", "")
                    reversal = "逆轉" in inst or "逆轉" in res_txt or "改判" in res_txt or node.get("reversal", False)

                    reversal_badge = "🚨 【見解逆轉改判！】" if reversal else "✅ 【見解推進 / 定錨】"

                    with st.container():
                        st.markdown(f"""
<div style="border-left: 5px solid {'#e63946' if reversal else '#457b9d'}; padding: 12px 16px; margin: 8px 0; background-color: {'rgba(230,57,70,0.06)' if reversal else 'rgba(69,123,157,0.06)'}; border-radius: 4px;">
    <div style="font-size: 1.05em; font-weight: bold; color: {'#d90429' if reversal else '#1d3557'};">
        {inst} ｜ {court_name} <code>{c_no}</code>
    </div>
    <div style="margin: 6px 0; font-size: 0.95em;">
        <strong>裁判結論：</strong> {res_txt} &nbsp;&nbsp; <span style="font-size: 0.85em; font-weight: bold; color: {'#d90429' if reversal else '#2a9d8f'};">{reversal_badge}</span>
    </div>
    <div style="font-size: 0.9em; color: #333;">
        <strong>核心論理與見解：</strong> {holding_txt}
    </div>
</div>
""", unsafe_allow_html=True)
                    if n_idx < len(stages) - 1:
                        st.markdown("<div style='text-align: center; font-size: 1.3em; color: #888; margin: -2px 0;'>⬇️ <em>上訴審理 / 見解演進轉折</em></div>", unsafe_allow_html=True)

                st.write("")
                st.info(f"💡 **審級更迭分歧核心點**：\n{p_info.get('distinguishing_insight') or p_info.get('distinguishing_points', '')}")
                st.success(f"✍️ **司律上位卷作答策略**：\n{p_info.get('exam_strategy')}")
                st.divider()

            # 外部查閱直連
            ext_urls = h_data.get("external_search_urls", {})
            if ext_urls:
                st.caption("🌐 全國權威法學資料庫歷審全文直連：")
                u1, u2, u3 = st.columns(3)
                with u1:
                    st.link_button("🏛️ 司法院裁判書開放系統", f"https://judgment.judicial.gov.tw/FJUD/default.aspx?k={h_cid}", use_container_width=True)
                with u2:
                    st.link_button("⚖️ 司法院法學資料檢索", "https://jirs.judicial.gov.tw/Index.aspx", use_container_width=True)
                with u3:
                    st.link_button("📜 憲法法庭裁判系統", f"https://cons.judicial.gov.tw/jcc/zh-tw/jep01?q={h_cid}", use_container_width=True)

            # AI 深度報告 Markdown
            st.markdown(h_md)

            st.divider()
            st.markdown("##### 🔗 本案脈絡鏈深度應用與跨模組聯動：")
            ac1, ac2, ac3, ac4 = st.columns(4)
            clean_h_cid = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '_', h_cid)
            with ac1:
                st.download_button(
                    label="💾 下載審級脈絡報告 (.md)",
                    data=h_md,
                    file_name=f"裁判審級更迭脈絡_{clean_h_cid}.md",
                    mime="text/markdown",
                    use_container_width=True
                )
            with ac2:
                if st.button("⚡ 帶入 AI 判解精鍊", use_container_width=True, key="btn_hist_to_sum"):
                    st.session_state["sum_citation_search"] = h_cid
                    st.session_state["citation_rev"] = st.session_state.get("citation_rev", 0) + 1
                    st.session_state["app_mode"] = mode_options[6]
                    st.rerun()
            with ac3:
                if st.button("🔄 帶入案例橫向比對", use_container_width=True, key="btn_hist_to_cmp"):
                    st.session_state["target_compare_case_a"] = h_cid
                    st.session_state["m5_sub_mode_idx"] = 4
                    st.rerun()
            with ac4:
                if st.button("📝 帶入試卷評分標準", use_container_width=True, key="btn_hist_to_eval"):
                    st.session_state["question_text_content"] = f"【二試歷審脈絡實例題目】：\n請針對【{h_cid}】所涉之審級更迭、各級法院之見解分歧與終局裁定法理，進行深度評析與事實涵攝。"
                    st.session_state["rubric_text_content"] = h_md
                    st.session_state["imported_from_bank_label"] = f"歷審脈絡標準【{h_cid[:15]}】"
                    st.session_state["app_mode"] = MODE_HOME
                    st.rerun()

    # ==================== 子功能 4: 🤖 AI 智慧爭點深度剖析與二試上位卷 IRAC 大典 ====================
    elif m5_active_tab == m5_sub_modes[3]:
        st.subheader("🤖 AI 智慧法學爭點剖析與二試上位卷 IRAC 大典")
        st.caption("引領司律考生直通二試上位卷！結合本機 3,680+ 筆權威判解庫與 Gemini 法學推論模型，自動輸出【法條構成要件】、【爭點所在】、【憲法法庭/大法庭/判例實務見解】、【學說肯否二說】及【俐落開標涵攝 IRAC 示範】。")

        # 考科選擇與模式
        col_q_domain, col_q_sub, col_q_mode = st.columns([1.1, 1.8, 1.4])
        with col_q_domain:
            q_domain = st.selectbox(
                "選擇考科學門大類：",
                list(LAW_DOMAIN_TAXONOMY.keys()),
                key="ai_query_domain"
            )
        with col_q_sub:
            domain_subjects = LAW_DOMAIN_TAXONOMY.get(q_domain, LAW_DOMAIN_TAXONOMY["🌟 全部學門 (跨領域綜合檢索與全考科自選)"])
            q_subject = st.selectbox(
                "選擇專屬考科範疇：",
                domain_subjects,
                key="ai_query_subject"
            )
        with col_q_mode:
            q_search_type = st.radio(
                "檢索類型：",
                ["🔍 爭點關鍵字 / 裁判字號", "📜 案件事實法律關係深度剖析"],
                horizontal=True,
                key="ai_query_mode"
            )

        # 雙層法學考點快選系統（選單一：體系章節分類 ➔ 選單二：大量預寫具體法學爭點庫）
        col_topic_c1, col_topic_c2 = st.columns([1.1, 2.2])
        with col_topic_c1:
            taxonomy_chapters = get_taxonomy_chapters_for_subject(q_subject)
            cur_ch_key = f"sel_issue_chapter_{q_subject}"
            sel_chapter = st.selectbox(
                f"1. 📚 爭點體系分類 / 章節專題：",
                taxonomy_chapters,
                key=cur_ch_key
            )

        with col_topic_c2:
            curated_issues_map = get_curated_issues_by_chapter(sel_chapter, q_subject)
            issue_title_list = list(curated_issues_map.keys())
            total_issue_cnt = len(issue_title_list)
            issue_options = [f"-- 💡 從預寫爭點庫快選（共 {total_issue_cnt} 則精選考點，點選自動帶入） --"] + issue_title_list
            cur_issue_key = f"sel_issue_item_{q_subject}_{sel_chapter}"
            sel_preset_issue = st.selectbox(
                f"2. 🎯 預先寫好之具體核心爭點庫（依【{sel_chapter.split('・')[0].replace('🌟', '').strip()[:8]}】）：",
                issue_options,
                key=cur_issue_key
            )

        if sel_preset_issue and not sel_preset_issue.startswith("-- 💡"):
            issue_info = curated_issues_map.get(sel_preset_issue, {})
            issue_query = issue_info.get("query", sel_preset_issue)
            issue_precedent = issue_info.get("precedent", "")
            issue_statute = issue_info.get("statute", "")
            issue_summary = issue_info.get("summary", "")

            st.session_state["ai_query_input_text"] = issue_query
            st.caption(f"📌 **已載入考點**：`{sel_preset_issue}` ｜ 🏛️ **權威指標**：`{issue_precedent or issue_statute}`")
            if issue_summary:
                with st.expander("💡 查看此預寫爭點之法理核心要點與二試作答指引：", expanded=False):
                    st.info(f"**【爭點爭端】**：{sel_preset_issue}\n\n**【核心法理】**：{issue_summary}\n\n**【權威裁判】**：{issue_precedent}\n\n**【關聯法條】**：{issue_statute}")



        current_query_val = st.session_state.get("ai_query_input_text", "")
        query_text = st.text_area(
            "請輸入欲查詢之爭點問題、裁判字號、法條或案件事實（支援布林精密運算與自然語言長句）：",
            value=current_query_val,
            height=100,
            placeholder="例如：(借名登記 ＋ 信託) ＆ (108台上大字1719 － 善意受讓)、民法184純經濟損失、106亡40、111憲判16...",
            key="ai_query_text_area"
        )

        col_btn_search, col_btn_clear = st.columns([3, 1])
        with col_btn_search:
            btn_do_query = st.button("🚀 啟動 AI 爭點深度剖析與 IRAC 示範", type="primary", use_container_width=True, key="btn_do_ai_irac_query")
        with col_btn_clear:
            if st.button("✖️ 清除爭點條件", use_container_width=True, key="btn_clear_ai_query"):
                st.session_state["ai_query_input_text"] = ""
                st.session_state.pop("ai_query_result", None)
                st.rerun()

        auto_exec_ai = st.session_state.pop("ai_query_auto_exec", False)
        if btn_do_query or auto_exec_ai:
            target_q = query_text.strip()
            if not target_q:
                st.warning("請先輸入欲查詢之爭點、判決字號或關鍵字！")
            else:
                with st.spinner("AI 司法典試顧問正在跨庫比對本機 3,680+ 筆裁判並提煉 IRAC 深度法理報告..."):
                    try:
                        engine = LegalIssueQueryEngine()
                        res = engine.query_legal_issue(query=target_q, subject=q_subject)
                        st.session_state["ai_query_result"] = res
                        st.session_state["ai_query_input_text"] = target_q
                    except Exception as qe:
                        st.error(f"爭點剖析失敗: {qe}")

        if "ai_query_result" in st.session_state:
            res = st.session_state["ai_query_result"]
            matched_cases = res.get("matched_local_precedents", [])
            ext_urls = res.get("external_search_urls", {})

            st.divider()
            st.subheader(f"📚 【{res.get('query', '')}】AI 深度爭點剖析報告")

            # 外部直連
            if ext_urls:
                with st.expander("🌐 外部權威資料庫直通", expanded=False):
                    e_col1, e_col2, e_col3 = st.columns(3)
                    url_items = list(ext_urls.items())
                    with e_col1:
                        for lbl, lnk in url_items[:3]:
                            st.link_button(lbl, lnk, use_container_width=True)
                    with e_col2:
                        for lbl, lnk in url_items[3:6]:
                            st.link_button(lbl, lnk, use_container_width=True)
                    with e_col3:
                        for lbl, lnk in url_items[6:]:
                            st.link_button(lbl, lnk, use_container_width=True)

            # 本地裁判
            if matched_cases:
                st.markdown(f"#### 🏛️ 本機命中之權威司法裁判 ({len(matched_cases)} 筆)")
                for m_idx, mc in enumerate(matched_cases):
                    c_id = mc.get("case_id", "")
                    lvl = mc.get("level", "")
                    tit = mc.get("title", "")
                    holding = mc.get("holding", "")

                    with st.expander(f"⚖️ 【{lvl}】`{c_id}` ｜ {tit}", expanded=(m_idx == 0)):
                        st.info(f"**核心主文 / 判決要旨：**\n{holding}")
                        if mc.get("scholarly_views"):
                            st.caption(f"📚 **學說實務對比：** {mc.get('scholarly_views')}")

                        btn_c0, btn_c1, btn_c2 = st.columns([1.5, 1.4, 1.4])
                        with btn_c0:
                            if st.button(f"🌿 審級更迭脈絡", key=f"btn_irac_hist_{m_idx}", use_container_width=True):
                                st.session_state["target_history_case_id"] = c_id
                                st.session_state["m5_sub_mode_idx"] = 2
                                st.rerun()
                        with btn_c1:
                            if st.button(f"⚡ AI 判解精鍊", key=f"btn_irac_sum_{m_idx}", use_container_width=True):
                                st.session_state["sum_citation_search"] = c_id
                                st.session_state["citation_rev"] = st.session_state.get("citation_rev", 0) + 1
                                st.session_state["app_mode"] = mode_options[6]
                                st.rerun()
                        with btn_c2:
                            if st.button(f"🔄 案例橫向比對", key=f"btn_irac_cmp_{m_idx}", use_container_width=True):
                                st.session_state["target_compare_case_a"] = c_id
                                st.session_state["m5_sub_mode_idx"] = 4
                                st.rerun()

            # IRAC 報告內容
            st.markdown("#### 🤖 深度法理爭點剖析與 IRAC 上位卷示範報告")
            st.markdown(res.get("markdown_result", ""))

            st.divider()
            st.subheader("🔗 跨模組一鍵聯動：將此爭點解析轉化為實戰訓練")
            act_col1, act_col2 = st.columns(2)
            with act_col1:
                if st.button("📝 【一鍵帶入試卷評分】作為評分標準與參考答案", use_container_width=True, type="primary", key="btn_imp_eval_m5"):
                    st.session_state["question_text_content"] = f"【爭點研析題目】：\n{res.get('query', '')}"
                    st.session_state["rubric_text_content"] = res.get("markdown_result", "")
                    st.session_state["imported_from_bank_label"] = f"AI 爭點速查標準【{res.get('query', '')[:20]}...】"
                    st.session_state["app_mode"] = MODE_HOME
                    st.rerun()
            with act_col2:
                if st.button("📖 【一鍵帶入高分擬答生成】針對此爭點撰寫申論答題", use_container_width=True, key="btn_imp_ans_m5"):
                    st.session_state["m4_target_question"] = res.get("query", "")
                    st.session_state["app_mode"] = mode_options[3]
                    st.rerun()

    # ==================== 子功能 5: 🔄 案例橫向比對與實務分歧研析 ====================
    elif m5_active_tab == m5_sub_modes[4]:
        st.subheader("🔄 案例橫向比對與實務分歧研析 (Case Distinguishing)")
        st.caption("支援【輸入爭點・找出所有判決採何說】與【兩大裁判橫向精確對比】：深度解構實務學說頻譜（甲說、乙說、折衷說）、所有裁判採何說歸納清單、事實區別關鍵 (Case Distinguishing)、歷審見解變遷與司律二試作答上位心法！")

        distinguish_tab1, distinguish_tab2 = st.tabs([
            "🎯 依爭點歸納「所有判決採何說」矩陣 (Doctrine Spectrum by Issue)",
            "⚖️ 指定兩大裁判橫向精確比對 (Case A vs Case B Distinguishing)"
        ])

        # ----------------- 分頁 1: 輸入爭點・找出所有判決採何說 -----------------
        with distinguish_tab1:
            st.markdown("#### 🎯 依爭點或基準判決找出「相同見解 vs 相反見解」所有判決 (實務各說頻譜與裁判歸納)")
            st.caption("輸入具體爭點或指定基準判決，AI 將深入檢索本機 2,100+ 裁判庫、大法庭裁定、歷審脈絡鏈與行政函釋，自動歸納【甲說、乙說、折衷說】各說核心論理，並精確梳理【哪些具體判決採何說】與【現行終局定錨見解】！")

            # 步驟一（選填）：從本機權威庫挑選基準判決／判例／決議／座談會
            st.markdown("##### 🏛️ 步驟一（選填）：從本機權威庫挑選基準判決／判例／決議／座談會")
            precedent_catalog_items = get_precedents_catalog() or []
            bench_options = ["-- 💡 不指定基準判決（由 AI 自動歸納各說） --"] + [
                f"{item.get('case_id')} ｜ [{item.get('level','')[:10]}] {item.get('title','')[:30]}"
                for item in precedent_catalog_items[:120]
            ]
            sel_bench_choice = st.selectbox(
                "挑選作為對照之權威基準裁判（選填，將據此比對「相同見解」與「相反見解」）：",
                bench_options,
                key="sel_benchmark_case_dropdown"
            )

            col_mb1, col_mb2 = st.columns([3, 1])
            with col_mb1:
                manual_bench_input = st.text_input(
                    "或手動輸入基準裁判字號（選填，例如：最高法院 108 年度台上大字第 1719 號裁定）：",
                    placeholder="例如：最高法院 108 年度台上大字第 1719 號民事裁定",
                    key="txt_manual_benchmark_id"
                )

            bench_case_data = None
            target_bench_id = ""
            if manual_bench_input.strip():
                target_bench_id = manual_bench_input.strip()
            elif sel_bench_choice != bench_options[0]:
                target_bench_id = sel_bench_choice.split(" ｜ ")[0].strip()

            if target_bench_id:
                bench_case_data = get_precedent_by_id(target_bench_id)
                if not bench_case_data:
                    for it in precedent_catalog_items:
                        if target_bench_id in it.get("case_id", ""):
                            bench_case_data = it
                            break

            if bench_case_data:
                with st.container(border=True):
                    st.markdown(f"**📌 目前選定基準裁判**：`{bench_case_data.get('case_id')}`（{bench_case_data.get('level','')}）")
                    if bench_case_data.get("holding"):
                        st.caption(f"**裁判要旨**：{bench_case_data.get('holding')[:220]}...")
                    if bench_case_data.get("issue"):
                        st.info(f"**收錄核心考點**：{bench_case_data.get('issue')}")
                        if st.button("📥 將此基準判決之收錄爭點自動帶入下方爭點欄", key="btn_apply_bench_issue"):
                            st.session_state["distinguish_issue_topic"] = bench_case_data.get("issue")
                            st.rerun()

            st.write("")
            st.markdown("##### 🎯 步驟二：輸入欲研析之法律爭點")

            cur_issue_topic = st.session_state.get("distinguish_issue_topic", "")
            col_iq1, col_iq2 = st.columns([3, 1])
            with col_iq1:
                inp_issue_topic = st.text_input(
                    "請輸入欲研析之法律爭點（例如：借名登記出名人未經同意處分標的物之效力、保險法64條除斥期間...）：",
                    value=cur_issue_topic,
                    placeholder="輸入具體法律爭點，系統將自動歸納各說並找出所有判決採何說...",
                    key="txt_input_issue_doctrine_topic"
                )
                if inp_issue_topic != cur_issue_topic:
                    st.session_state["distinguish_issue_topic"] = inp_issue_topic
            with col_iq2:
                inp_issue_sub = st.selectbox(
                    "所屬考科領域（選填）：",
                    ["民事法 (民總/債/物/身分)", "刑事法 (刑總/刑分/刑訴)", "公法 (憲法/行政法)", "商事法 (公司/證交/保險)", "智慧財產權法", "跨領域綜合實務"],
                    key="sel_issue_doctrine_sub"
                )

            with st.expander("📝 自訂補充事實脈絡或案情背景（選填）", expanded=False):
                inp_custom_issue_ctx = st.text_area(
                    "爭點背景、兩造爭議情境或特定法規補充：",
                    height=100,
                    placeholder="可在此補充具體案例事實（如：善意受讓、已登記但未交付、逾期二年等）...",
                    key="txt_custom_issue_ctx"
                )

            col_btn_doc1, col_btn_doc2 = st.columns([3, 1])
            with col_btn_doc1:
                btn_run_issue_doctrines = st.button("🚀 檢索並歸納所有判決採何說", type="primary", use_container_width=True, key="btn_exec_issue_doctrines")
            with col_btn_doc2:
                if st.button("✖️ 清除爭點分析結果", use_container_width=True, key="btn_clr_issue_doctrines"):
                    st.session_state.pop("issue_doctrine_analysis_res", None)
                    st.session_state["distinguish_issue_topic"] = ""
                    st.rerun()

            if btn_run_issue_doctrines:
                if not inp_issue_topic.strip():
                    st.warning("請先輸入欲研析之法律爭點！")
                else:
                    with st.spinner("AI 司法典試長正在檢索本機 2,100+ 裁判庫與大法庭裁定，歸納各說論理與【所有判決採何說】..."):
                        try:
                            engine = LegalIssueQueryEngine()
                            doc_res = engine.analyze_doctrines_by_issue(
                                issue_topic=inp_issue_topic.strip(),
                                subject=inp_issue_sub,
                                custom_context=inp_custom_issue_ctx,
                                benchmark_case=bench_case_data
                            )
                            st.session_state["issue_doctrine_analysis_res"] = doc_res
                            st.session_state["distinguish_issue_topic"] = inp_issue_topic.strip()
                        except Exception as de:
                            st.error(f"爭點各說判決歸納失敗: {de}")

            if "issue_doctrine_analysis_res" in st.session_state:
                d_res = st.session_state["issue_doctrine_analysis_res"]
                d_md = d_res.get("markdown_result", "")
                d_top = d_res.get("issue_topic", "")
                d_bench = d_res.get("benchmark_case")

                st.divider()
                st.subheader(f"📊 【{d_top}】爭點各說頻譜與裁判採何說歸納報告")
                if d_bench:
                    st.info(f"💡 本報告已嚴密錨定基準判決【{d_bench.get('case_id')}】，下方特別分設「✅ 相同見解」與「❌ 相反見解」專屬清單！")

                # 外部查詢直連
                st.caption("🌐 全國權威司法資料庫爭點直查：")
                s_urls = d_res.get("search_urls", {})
                if s_urls:
                    url_cols = st.columns(min(len(s_urls), 4))
                    for idx_u, (u_label, u_url) in enumerate(list(s_urls.items())[:4]):
                        with url_cols[idx_u % 4]:
                            st.link_button(u_label, u_url, use_container_width=True)

                st.markdown(d_md)

                st.divider()
                st.markdown("##### 🔗 爭點研析結果應用：")
                col_exp_d1, col_exp_d2 = st.columns(2)
                with col_exp_d1:
                    clean_top = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '_', d_top)[:20]
                    st.download_button(
                        label="💾 下載實務爭點歸納報告 (.md)",
                        data=d_md,
                        file_name=f"爭點各說裁判歸納_{clean_top}.md",
                        mime="text/markdown",
                        use_container_width=True,
                        key="btn_dl_issue_doctrines_md"
                    )
                with col_exp_d2:
                    if st.button("✍️ 將此爭點帶入「二試高分擬答生成」", use_container_width=True, key="btn_apply_doctrines_to_ans"):
                        st.session_state["ans_question_input"] = f"【核心爭點研究】：{d_top}\n\n請依上述爭點各說與實務定錨見解，撰寫上位卷 IRAC 示範擬答。"
                        st.session_state["ans_subject_choice"] = inp_issue_sub.split(" ")[0]
                        st.session_state["app_mode"] = MODE_ANS
                        st.rerun()

        # ----------------- 分頁 2: 指定兩大裁判橫向精確比對 -----------------
        with distinguish_tab2:
            st.markdown("#### ⚖️ 指定兩大裁判橫向精確比對 (Case A vs Case B Distinguishing)")
            st.caption("深度對比兩則裁判或大法庭裁定之【事實情境異同】、【當事人主張】、【法院心證核心對比】、【法律見解分歧 (肯否兩說)】及【司律二試案例區別作答心法】。")
            all_precedents_tags = ["-- 📚 從本機 3,680+ 筆權威庫中挑選裁判 --"] + get_all_precedent_options()

            c_a_val = st.session_state.get("target_compare_case_a", "最高法院 108 年度台上大字第 1719 號民事大法庭裁定")
            c_b_val = st.session_state.get("target_compare_case_b", "最高法院 96 年度台上字第 2851 號判決")
            c_top_val = st.session_state.get("target_compare_topic", "借名登記出名人未經同意處分標的物之效力")

            col_a_box, col_b_box = st.columns(2)
            with col_a_box:
                st.markdown("#### 🏛️ 【基準裁判 A】")
                def_idx_a = 0
                for idx_a, tag in enumerate(all_precedents_tags):
                    if c_a_val and c_a_val in tag:
                        def_idx_a = idx_a
                        break
                sel_tag_a = st.selectbox("從庫中選取裁判 A：", all_precedents_tags, index=def_idx_a, key="sel_cmp_tag_a")
                if sel_tag_a and sel_tag_a != "-- 📚 從本機 3,680+ 筆權威庫中挑選裁判 --":
                    c_a_val = sel_tag_a.split(" ｜ ")[0].strip()
                inp_case_a = st.text_input("裁判 A 案號/字號：", value=c_a_val, key="inp_cmp_case_a")

            with col_b_box:
                st.markdown("#### 🏛️ 【比對裁判 B】")
                def_idx_b = 0
                for idx_b, tag in enumerate(all_precedents_tags):
                    if c_b_val and c_b_val in tag:
                        def_idx_b = idx_b
                        break
                sel_tag_b = st.selectbox("從庫中選取裁判 B：", all_precedents_tags, index=def_idx_b, key="sel_cmp_tag_b")
                if sel_tag_b and sel_tag_b != "-- 📚 從本機 3,680+ 筆權威庫中挑選裁判 --":
                    c_b_val = sel_tag_b.split(" ｜ ")[0].strip()
                inp_case_b = st.text_input("裁判 B 案號/字號：", value=c_b_val, key="inp_cmp_case_b")

            inp_cmp_topic = st.text_input("核心比對爭點主題（選填）：", value=c_top_val, placeholder="例如：借名登記出名人處分權限、過失傷害注意義務標準...", key="inp_cmp_topic")

            with st.expander("📝 自訂補充兩案裁判內容或事實節錄（選填）", expanded=False):
                t_col1, t_col2 = st.columns(2)
                with t_col1:
                    custom_text_a = st.text_area("裁判 A 內容節錄：", height=100, key="custom_text_a")
                with t_col2:
                    custom_text_b = st.text_area("裁判 B 內容節錄：", height=100, key="custom_text_b")

            col_b_cmp, col_b_cclr = st.columns([3, 1])
            with col_b_cmp:
                btn_start_cmp = st.button("🚀 啟動 AI 裁判橫向比對與分歧研析", type="primary", use_container_width=True, key="btn_exec_case_cmp")
            with col_b_cclr:
                if st.button("✖️ 清除比對結果", use_container_width=True, key="btn_clr_case_cmp"):
                    st.session_state.pop("case_comparison_result", None)
                    st.rerun()

            if btn_start_cmp:
                if not inp_case_a.strip() or not inp_case_b.strip():
                    st.warning("請同時提供【裁判 A】與【裁判 B】之案號！")
                else:
                    with st.spinner(f"AI 司法典試顧問正在進行【{inp_case_a}】vs【{inp_case_b}】全方位事實區別與法理分歧研析..."):
                        try:
                            engine = LegalIssueQueryEngine()
                            cmp_res = engine.compare_precedents(
                                case_a=inp_case_a.strip(),
                                case_b=inp_case_b.strip(),
                                text_a=custom_text_a,
                                text_b=custom_text_b,
                                topic=inp_cmp_topic.strip()
                            )
                            st.session_state["case_comparison_result"] = cmp_res
                            st.session_state["target_compare_case_a"] = inp_case_a.strip()
                            st.session_state["target_compare_case_b"] = inp_case_b.strip()
                            st.session_state["target_compare_topic"] = inp_cmp_topic.strip()
                        except Exception as ce:
                            st.error(f"比對分析失敗: {ce}")

            if "case_comparison_result" in st.session_state:
                c_res = st.session_state["case_comparison_result"]
                c_md = c_res.get("markdown_result", "")
                ca_id = c_res.get("case_a", "")
                cb_id = c_res.get("case_b", "")

                st.divider()
                st.subheader(f"⚖️ 【{ca_id}】 vs 【{cb_id}】AI 裁判橫向比對研析報告")

                cb_col1, cb_col2 = st.columns(2)
                with cb_col1:
                    st.link_button(f"🏛️ 司法院裁判書直查【{ca_id}】", f"https://judgment.judicial.gov.tw/FJUD/default.aspx?k={ca_id}", use_container_width=True)
                with cb_col2:
                    st.link_button(f"🏛️ 司法院裁判書直查【{cb_id}】", f"https://judgment.judicial.gov.tw/FJUD/default.aspx?k={cb_id}", use_container_width=True)

                st.markdown(c_md)

                st.divider()
                st.markdown("##### 🔗 比對報告應用與後續演練：")
                clean_ca_id = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '_', ca_id)
                clean_cb_id = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '_', cb_id)
                cc_col1, cc_col2 = st.columns(2)
                with cc_col1:
                    st.download_button(
                        label="💾 下載兩大案例橫向比對報告 (.md)",
                        data=c_md,
                        file_name=f"案例橫向比對_{clean_ca_id}_vs_{clean_cb_id}.md",
                        mime="text/markdown",
                        use_container_width=True
                    )
                with cc_col2:
                    if st.button("📝 帶入試卷評分作為進階對比評分標準", use_container_width=True, key="btn_pass_cmp_to_eval"):
                        st.session_state["question_text_content"] = f"【二試進階實例案例區別題目】：\n請就【{ca_id}】與【{cb_id}】所涉及之案件事實與法律見解分歧，深入剖析其法律爭點、各說立論與事實區別標準。"
                        st.session_state["rubric_text_content"] = c_md
                        st.session_state["imported_from_bank_label"] = f"案例橫向比對標準【{ca_id[:15]} vs {cb_id[:15]}】"
                        st.session_state["app_mode"] = MODE_HOME
                        st.rerun()


# ----------------- 模式: 專屬法學全能問答樞紐 (萬能檢索・條文定位・爭點論辯・金額精算) -----------------
elif app_mode == MODE_QA or "法律問題" in app_mode or "法律諮詢" in app_mode or "生活法律" in app_mode or "一般法律" in app_mode or "智慧問答" in app_mode or "全能法律" in app_mode or "專屬法學" in app_mode or "萬能檢索" in app_mode:
    st.markdown("""
        <div style="text-align: center; margin-top: 5px; margin-bottom: 20px;">
            <h1 style="font-size: 2.2rem; margin-bottom: 6px;">🔍 司律與實務法學萬能檢索樞紐</h1>
            <p style="color: #555; font-size: 1.05rem; margin-bottom: 0;">專為本專案特化之全能法學檢索系統：單一搜尋欄支援法條定位（這情況適用哪一條？）、爭點論辯、例題金錢精算或生活法律爭議</p>
        </div>
    """, unsafe_allow_html=True)

    # 1. 專屬特化單一整體搜尋欄
    qa_input_val = st.session_state.get("current_qa_question_input", "")
    
    col_search_box, col_search_act = st.columns([4.2, 1.2])
    with col_search_box:
        user_question = st.text_area(
            "請輸入欲搜尋之法律問題、條文疑義、爭點或計算例題：",
            value=qa_input_val,
            height=95,
            placeholder="🔍 例如：\n1. 把別人的油漆塗在自己車上是民法哪一條？所有權歸誰？\n2. 借名登記出名人擅自出賣不動產之效力？實務與學說見解為何？\n3. 車齡2年8個月車禍零件14萬工資6萬，依定率遞減法折舊應賠償多少？\n4. 房東藉故扣留2個月押金不退還，我該如何合法要回？",
            key="txt_unified_law_search",
            label_visibility="collapsed"
        )
    with col_search_act:
        btn_start_qa = st.button("🔍 啟動全能法學檢索", type="primary", use_container_width=True, key="btn_run_legal_qa")
        if st.button("✖️ 清除搜尋", use_container_width=True, key="btn_clear_legal_qa"):
            st.session_state.pop("current_qa_result", None)
            st.session_state.pop("current_qa_question_input", None)
            st.session_state.pop("qa_conversation_history", None)
            st.session_state.pop("qa_generated_notice", None)
            st.session_state.pop("qa_generated_mediation", None)
            st.rerun()

    # 快捷檢索意圖分類標籤 (預設全自動偵測，亦可手動快切)
    qa_query_type = st.radio(
        "檢索意圖標籤：",
        QUERY_TYPES,
        horizontal=True,
        index=0,
        key="rad_qa_query_type",
        label_visibility="collapsed"
    )

    # 2. 原本那個功能也不錯可以保留 (保留在優雅收合的進階設定與專屬精算工具箱中)
    with st.expander("⚙️ 保留原版進階設定與專用金錢精算工具箱 (領域自選・立場選擇・輸出規格・五大多功能試算機)", expanded=False):
        st.markdown("##### 🎯 諮詢立場與報告規格設定：")
        col_q1, col_q2, col_q3 = st.columns([1.5, 1.2, 1.3])
        with col_q1:
            qa_domain = st.selectbox(
                "法律範疇分類（可自選或交由系統自動辨識）：",
                LEGAL_CONSULTATION_DOMAINS,
                index=0,
                key="sel_qa_domain"
            )
        with col_q2:
            qa_standpoint = st.selectbox(
                "諮詢立場與評估角度：",
                USER_STANDPOINTS,
                index=0,
                key="sel_qa_standpoint"
            )
        with col_q3:
            qa_output_mode = st.selectbox(
                "諮詢報告架構模式：",
                OUTPUT_MODES,
                index=0,
                key="sel_qa_output_mode"
            )

        st.divider()
        st.markdown("##### 🧮 專用法律金錢精算機（純 Python 零誤差精算法定公式，亦可點擊帶入上方搜尋欄進行 AI 深度剖析）：")
        calc_tab1, calc_tab2, calc_tab3, calc_tab4, calc_tab5 = st.tabs([
            "🚗 車損零件折舊",
            "💼 勞退新制資遣費",
            "👨‍👩‍👧 夫妻剩餘財產",
            "📜 遺產應繼與特留分",
            "💰 法定遲延利息"
        ])

        with calc_tab1:
            st.caption("依行政院固定資產耐用年數表與最高法院77年度第九次民事庭會議決議：工資全額賠償不折舊，零件依法折舊，殘值底線不低於取得原價10%。")
            cv_c1, cv_c2, cv_c3 = st.columns(3)
            with cv_c1:
                calc_v_part = st.number_input("零件維修費 (元)：", min_value=0.0, value=120000.0, step=1000.0, key="num_c_v_part")
            with cv_c2:
                calc_v_labor = st.number_input("工資板烤費 (元)：", min_value=0.0, value=40000.0, step=1000.0, key="num_c_v_labor")
            with cv_c3:
                calc_v_type = st.selectbox("車輛種類與耐用年數：", [
                    "自用小客車 (耐用年數5年，年折舊率 0.369)",
                    "營業小客車/計程車 (耐用年數4年，年折舊率 0.438)",
                    "機車 (耐用年數3年，年折舊率 0.536)",
                    "貨車 (耐用年數4年，年折舊率 0.438)"
                ], key="sel_c_v_type")

            cv_c4, cv_c5, cv_c6 = st.columns(3)
            with cv_c4:
                calc_v_years = st.number_input("出廠車齡（滿幾年）：", min_value=0, max_value=30, value=2, key="num_c_v_years")
            with cv_c5:
                calc_v_months = st.number_input("畸零月數（幾個月）：", min_value=0, max_value=11, value=6, key="num_c_v_months")
            with cv_c6:
                calc_v_method = st.selectbox("折舊計算方式：", [
                    "定率遞減法 (每年折舊率計算，殘值底線 10%)",
                    "平均法 (直線法，每年平均折舊)"
                ], key="sel_c_v_method")

            calc_v_neg = st.slider("我方過失相抵比例 (%)：", min_value=0, max_value=100, value=0, key="sli_c_v_neg")
            
            btn_run_v, btn_pass_v = st.columns([1, 1])
            with btn_run_v:
                if st.button("🧮 立即精算車損折舊", use_container_width=True, key="btn_calc_vehicle_run"):
                    res_v = calculate_vehicle_depreciation(
                        part_cost=calc_v_part,
                        labor_cost=calc_v_labor,
                        age_years=int(calc_v_years),
                        age_months=int(calc_v_months),
                        vehicle_type=calc_v_type,
                        method=calc_v_method,
                        comparative_negligence_pct=calc_v_neg
                    )
                    st.session_state["calc_v_result"] = res_v
            with btn_pass_v:
                if st.button("📝 帶入上方搜尋欄進行 AI 深度剖析", use_container_width=True, key="btn_apply_v_search"):
                    st.session_state["current_qa_question_input"] = f"車輛車損賠償精算案例：車輛種類為【{calc_v_type.split(' ')[0]}】，車齡【{calc_v_years} 年 {calc_v_months} 個月】，維修支出：更換新零件 NT${calc_v_part:,.0f} 元，工資 NT${calc_v_labor:,.0f} 元，我方過失責任比例為 {calc_v_neg}%。請依【{calc_v_method.split(' ')[0]}】折舊計算，拆解得請求之損害賠償總金額與法理要件。"
                    st.session_state["qa_auto_run_trigger"] = True
                    st.rerun()

            if "calc_v_result" in st.session_state:
                vr = st.session_state["calc_v_result"]
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("零件折舊後殘值", f"NT${vr['part_final_value']:,.0f}")
                m2.metric("工資不折舊", f"NT${vr['labor_cost']:,.0f}")
                m3.metric("折舊前損害總額", f"NT${(vr['part_original'] + vr['labor_cost']):,.0f}")
                m4.metric("最終應獲賠金額", f"NT${vr['final_award']:,.0f}", delta=f"-NT${vr['part_depreciation_total']:,.0f} (折舊)")
                with st.expander("🔍 查看詳細計算步驟與法院折舊明細", expanded=True):
                    for step in vr["steps"]:
                        st.write(f"- {step}")
                    st.caption(f"**法律依據**：{vr['legal_basis']}")

        with calc_tab2:
            st.caption("依勞工退休金條例第 12 條（勞退新制）每滿 1 年發給 0.5 個月平均工資，未滿 1 年以比例計，最高 6 個月為限；及勞動基準法第 16 條預告期間工資。")
            cs_c1, cs_c2 = st.columns(2)
            with cs_c1:
                calc_s_wage = st.number_input("月平均工資 (元)：", min_value=0.0, value=65000.0, step=1000.0, key="num_c_s_wage")
            with cs_c2:
                calc_s_notice = st.checkbox("雇主是否已依法給足預告期？（若未給足依法應給付預告工資）", value=False, key="chk_c_s_notice")
            cs_c3, cs_c4, cs_c5 = st.columns(3)
            with cs_c3:
                calc_s_years = st.number_input("工作年資（滿幾年）：", min_value=0, max_value=50, value=3, key="num_c_s_years")
            with cs_c4:
                calc_s_months = st.number_input("畸零月數：", min_value=0, max_value=11, value=7, key="num_c_s_months")
            with cs_c5:
                calc_s_days = st.number_input("畸零天數：", min_value=0, max_value=30, value=15, key="num_c_s_days")

            btn_run_s, btn_pass_s = st.columns([1, 1])
            with btn_run_s:
                if st.button("🧮 立即精算資遣費與預告工資", use_container_width=True, key="btn_calc_sev_run"):
                    res_s = calculate_severance_pay(
                        monthly_wage=calc_s_wage,
                        years=int(calc_s_years),
                        months=int(calc_s_months),
                        days=int(calc_s_days),
                        has_advance_notice=calc_s_notice
                    )
                    st.session_state["calc_s_result"] = res_s
            with btn_pass_s:
                if st.button("📝 帶入上方搜尋欄進行 AI 深度剖析", use_container_width=True, key="btn_apply_s_search"):
                    st.session_state["current_qa_question_input"] = f"勞工資遣費與預告工資精算案例：勞工月平均工資 NT${calc_s_wage:,.0f} 元，總年資【{calc_s_years} 年 {calc_s_months} 個月 {calc_s_days} 天】，雇主無預警終止勞動契約（{'已給預告期' if calc_s_notice else '未給預告期'}）。請依勞工退休金條例第12條與勞基法第16、17條，精算勞工依法應得之資遣費、預告工資及救濟途徑。"
                    st.session_state["qa_auto_run_trigger"] = True
                    st.rerun()

            if "calc_s_result" in st.session_state:
                sr = st.session_state["calc_s_result"]
                sm1, sm2, sm3, sm4 = st.columns(4)
                sm1.metric("新制資遣基數", f"{sr['capped_factor']:.3f} 個月")
                sm2.metric("新制資遣費", f"NT${sr['severance_amount']:,.0f}")
                sm3.metric("預告期工資", f"NT${sr['notice_pay']:,.0f}", help=f"法定預告期 {sr['notice_days']} 日")
                sm4.metric("合計應給付總額", f"NT${sr['total_due']:,.0f}")
                st.caption(f"**年資計算**：{sr['tenure_str']} ｜ **法條依據**：{sr['legal_basis']}")

        with calc_tab3:
            st.caption("民法第 1030 條之 1 法定財產制剩餘財產分配：婚後現存財產扣除婚後負債，並扣除因繼承、無償取得之財產與慰撫金後，計算雙方差額並平均分配。")
            cm_col1, cm_col2 = st.columns(2)
            with cm_col1:
                st.markdown("**【夫 (先生) 財產與負債】**")
                calc_h_assets = st.number_input("夫婚後現存財產總額 (元)：", min_value=0.0, value=8000000.0, step=100000.0, key="num_c_h_a")
                calc_h_debts = st.number_input("夫婚後所負債務總額 (元)：", min_value=0.0, value=2000000.0, step=100000.0, key="num_c_h_d")
                calc_h_exempt = st.number_input("夫因繼承/無償贈與/慰撫金取得 (元)：", min_value=0.0, value=1000000.0, step=50000.0, key="num_c_h_e")
            with cm_col2:
                st.markdown("**【妻 (太太) 財產與負債】**")
                calc_w_assets = st.number_input("妻婚後現存財產總額 (元)：", min_value=0.0, value=3000000.0, step=100000.0, key="num_c_w_a")
                calc_w_debts = st.number_input("妻婚後所負債務總額 (元)：", min_value=0.0, value=500000.0, step=50000.0, key="num_c_w_d")
                calc_w_exempt = st.number_input("妻因繼承/無償贈與/慰撫金取得 (元)：", min_value=0.0, value=0.0, step=50000.0, key="num_c_w_e")

            btn_run_m, btn_pass_m = st.columns([1, 1])
            with btn_run_m:
                if st.button("🧮 立即精算剩餘財產分配額", use_container_width=True, key="btn_calc_mar_run"):
                    res_m = calculate_marital_property_division(
                        husband_assets=calc_h_assets,
                        husband_debts=calc_h_debts,
                        husband_exempt=calc_h_exempt,
                        wife_assets=calc_w_assets,
                        wife_debts=calc_w_debts,
                        wife_exempt=calc_w_exempt
                    )
                    st.session_state["calc_m_result"] = res_m
            with btn_pass_m:
                if st.button("📝 帶入上方搜尋欄進行 AI 深度剖析", use_container_width=True, key="btn_apply_m_search"):
                    st.session_state["current_qa_question_input"] = f"夫妻剩餘財產分配案例：夫婚後財產 NT${calc_h_assets:,.0f}，負債 NT${calc_h_debts:,.0f}，無償取得 NT${calc_h_exempt:,.0f}；妻婚後財產 NT${calc_w_assets:,.0f}，負債 NT${calc_w_debts:,.0f}，無償取得 NT${calc_w_exempt:,.0f}。請依民法第1030條之1分析雙方淨財產、差額分配金額、時效與抗辯事由。"
                    st.session_state["qa_auto_run_trigger"] = True
                    st.rerun()

            if "calc_m_result" in st.session_state:
                mr = st.session_state["calc_m_result"]
                mm1, mm2, mm3 = st.columns(3)
                mm1.metric("夫婚後淨財產", f"NT${mr['husband_net']:,.0f}")
                mm2.metric("妻婚後淨財產", f"NT${mr['wife_net']:,.0f}")
                mm3.metric("雙方差額", f"NT${mr['difference']:,.0f}")
                st.success(f"⚖️ 分配結論：由 **{mr['giver']}** 給付 **{mr['receiver']}** 剩餘財產差額半數 **NT${mr['transfer_amount']:,.0f}** 元！")

        with calc_tab4:
            st.caption("民法第 1138、1144 條法定應繼分與第 1223 條特留分精算。")
            ci_c1, ci_c2, ci_c3 = st.columns(3)
            with ci_c1:
                calc_i_estate = st.number_input("被繼承人遺產總淨額 (元)：", min_value=0.0, value=12000000.0, step=100000.0, key="num_c_i_estate")
            with ci_c2:
                calc_i_spouse = st.checkbox("配偶是否在世為共同繼承人？", value=True, key="chk_c_i_spouse")
            with ci_c3:
                calc_i_order = st.selectbox("其他順序繼承人血親類別：", [
                    "第一順序：子女 (直系血親卑親屬)",
                    "第二順序：父母",
                    "第三順序：兄弟姊妹",
                    "第四順序：祖父母",
                    "無其他順序血親繼承人 (僅配偶單獨繼承)"
                ], key="sel_c_i_order")
            
            calc_i_count = st.number_input("該順序血親繼承人人數（人）：", min_value=0, max_value=20, value=3, key="num_c_i_count")

            btn_run_i, btn_pass_i = st.columns([1, 1])
            with btn_run_i:
                if st.button("🧮 立即精算應繼分與特留分", use_container_width=True, key="btn_calc_inh_run"):
                    order_idx = 1
                    if "第二順序" in calc_i_order: order_idx = 2
                    elif "第三順序" in calc_i_order: order_idx = 3
                    elif "第四順序" in calc_i_order: order_idx = 4
                    elif "無其他" in calc_i_order: order_idx = 0
                    res_i = calculate_inheritance_shares(
                        estate_total=calc_i_estate,
                        has_spouse=calc_i_spouse,
                        order=order_idx,
                        heir_count=int(calc_i_count)
                    )
                    st.session_state["calc_i_result"] = res_i
            with btn_pass_i:
                if st.button("📝 帶入上方搜尋欄進行 AI 深度剖析", use_container_width=True, key="btn_apply_i_search"):
                    st.session_state["current_qa_question_input"] = f"遺產繼承應繼分與特留分例題：被繼承人遺留遺產總額 NT${calc_i_estate:,.0f} 元，繼承人有配偶（{'有' if calc_i_spouse else '無'}）以及【{calc_i_order.split('：')[1]}】共 {calc_i_count} 人。請依民法第1138、1144與1223條，逐一計算各繼承人之應繼分比例、金額與特留分扣減原則。"
                    st.session_state["qa_auto_run_trigger"] = True
                    st.rerun()

            if "calc_i_result" in st.session_state:
                ir = st.session_state["calc_i_result"]
                st.markdown("##### 📊 各繼承人應繼分與特留分試算分配清單：")
                i_rows = []
                for h in ir["heirs_summary"]:
                    i_rows.append({
                        "繼承人身分": h["role"],
                        "法定應繼分比例": h["fraction"],
                        "應繼分金額 (NT$)": f"{h['amount']:,.0f}",
                        "法定特留分金額 (NT$)": f"{h['reserved']:,.0f}",
                        "法律註記": h["note"]
                    })
                st.table(i_rows)
                st.caption(f"**法律依據**：{ir['legal_basis']}")

        with calc_tab5:
            st.caption("民法第 203 條：應付利息之債務，其利率未經約定，亦無法律可據者，週年利率為百分之五。")
            cnt_c1, cnt_c2, cnt_c3 = st.columns(3)
            with cnt_c1:
                calc_n_p = st.number_input("請求本金金額 (元)：", min_value=0.0, value=500000.0, step=10000.0, key="num_c_n_p")
            with cnt_c2:
                calc_n_d = st.number_input("經過天數（日）：", min_value=1, max_value=3650, value=180, key="num_c_n_d")
            with cnt_c3:
                calc_n_r = st.number_input("週年利率 (%)：", min_value=0.1, max_value=20.0, value=5.0, step=0.5, key="num_c_n_r")

            if st.button("🧮 立即精算遲延利息", use_container_width=True, key="btn_calc_int_run"):
                res_int = calculate_statutory_interest(
                    principal=calc_n_p,
                    days=int(calc_n_d),
                    annual_rate_pct=calc_n_r
                )
                im1, im2, im3 = st.columns(3)
                im1.metric("請求本金", f"NT${res_int['principal']:,.0f}")
                im2.metric("法定利息金額", f"NT${res_int['interest_amount']:,.0f}", delta=f"{res_int['days']} 天")
                im3.metric("本利和總額", f"NT${res_int['total_amount']:,.0f}")

    # 3. 執行檢索推論
    do_run_qa = btn_start_qa or st.session_state.pop("qa_auto_run_trigger", False)
    if do_run_qa:
        if not user_question.strip():
            st.warning("請先輸入具體法律問題、條文疑義、爭點或計算題目！")
        else:
            with st.spinner("專屬法學智慧檢索引擎正在檢索現行法典、最高法院判決、大法庭裁定與權威法理，進行深度推論..."):
                try:
                    engine = LegalQAEngine()
                    qa_hist = st.session_state.get("qa_conversation_history", [])
                    qa_res = engine.answer_legal_question(
                        question=user_question.strip(),
                        domain=qa_domain,
                        standpoint=qa_standpoint,
                        output_mode=qa_output_mode,
                        query_type=qa_query_type,
                        history=qa_hist
                    )
                    st.session_state["current_qa_result"] = qa_res
                    st.session_state["current_qa_question_input"] = user_question.strip()
                    if "qa_conversation_history" not in st.session_state:
                        st.session_state["qa_conversation_history"] = []
                    st.session_state["qa_conversation_history"].append({
                        "question": user_question.strip(),
                        "answer": qa_res.get("content", "")
                    })
                except Exception as qe:
                    st.error(f"法律檢索與諮詢分析失敗: {qe}")

    if "current_qa_result" in st.session_state:
        res = st.session_state["current_qa_result"]
        qa_ans = res.get("content", "")
        qa_q = res.get("question", "")
        q_dom = res.get("domain", "")
        q_mode_tag = res.get("query_type", "法理深度剖析")

        st.divider()
        st.markdown(f"### 📋 【專屬法學智慧檢索結果：{q_mode_tag.split(' ')[0]}】")
        st.markdown(qa_ans)

        st.divider()
        st.markdown("##### 🛠️ 實務救濟文書生成與延伸工具：")

        # 存證信函生成區
        with st.expander("📮 一鍵自動草擬【郵局存證信函】正式草稿（可直接複製或發函）", expanded=False):
            n_c1, n_c2, n_c3 = st.columns([1.2, 1.2, 1])
            with n_c1:
                n_sender = st.text_input("寄件人姓名：", value="本人", key="inp_notice_sender")
            with n_c2:
                n_recv = st.text_input("相對人姓名/公司名稱：", value="相對人", key="inp_notice_recv")
            with n_c3:
                n_days = st.number_input("催告履行期限 (天)：", min_value=3, max_value=30, value=7, key="inp_notice_days")

            if st.button("📑 生成存證信函標準範本", key="btn_gen_notice", use_container_width=True):
                with st.spinner("正在以專業律師函令規格草擬存證信函..."):
                    engine = LegalQAEngine()
                    notice_text = engine.generate_legal_notice(
                        question=qa_q,
                        legal_advice=qa_ans,
                        sender_name=n_sender,
                        receiver_name=n_recv,
                        deadline_days=int(n_days)
                    )
                    st.session_state["qa_generated_notice"] = notice_text

            if "qa_generated_notice" in st.session_state:
                st.text_area("存證信函草稿內文（可直接複製）：", value=st.session_state["qa_generated_notice"], height=260, key="txt_area_notice_out")
                st.download_button(
                    "💾 下載存證信函草稿 (.txt)",
                    data=st.session_state["qa_generated_notice"],
                    file_name="存證信函草稿.txt",
                    mime="text/plain",
                    use_container_width=True
                )

        # 調解聲請要旨區
        with st.expander("🏛️ 一鍵生成【鄉鎮市區調解聲請要旨與談判方案】", expanded=False):
            if st.button("📝 生成調解聲請要旨與和解方案", key="btn_gen_mediation", use_container_width=True):
                with st.spinner("正在擬定公所調解委員會聲請要旨與談判退讓底線..."):
                    engine = LegalQAEngine()
                    med_text = engine.generate_mediation_summary(
                        question=qa_q,
                        legal_advice=qa_ans
                    )
                    st.session_state["qa_generated_mediation"] = med_text

            if "qa_generated_mediation" in st.session_state:
                st.markdown(st.session_state["qa_generated_mediation"])
                st.download_button(
                    "💾 下載調解聲請要旨 (.md)",
                    data=st.session_state["qa_generated_mediation"],
                    file_name="調解委員會聲請要旨.md",
                    mime="text/markdown",
                    use_container_width=True
                )

        # 延伸連動導航
        st.write("")
        act_col1, act_col2, act_col3 = st.columns(3)
        with act_col1:
            st.download_button(
                "📥 下載本次法律諮詢報告 (.md)",
                data=f"# 法律諮詢意見書\n\n**諮詢問題**：\n{qa_q}\n\n**分析結論**：\n{qa_ans}",
                file_name="法律諮詢意見書.md",
                mime="text/markdown",
                use_container_width=True
            )
        with act_col2:
            if st.button("⚖️ 帶入智慧六法查閱法條", use_container_width=True, key="btn_qa_to_six_codes"):
                st.session_state["app_mode"] = mode_options[7]
                st.rerun()
        with act_col3:
            if st.button("🔍 帶入統一法學樞紐檢索判決", use_container_width=True, key="btn_qa_to_search"):
                st.session_state["lp_search_query"] = qa_q[:40]
                st.session_state["app_mode"] = mode_options[4]
                st.rerun()

        # 連續追問區
        st.divider()
        st.markdown("##### 💬 針對上述分析繼續追問（維持對話上下文）：")
        fu_c1, fu_c2 = st.columns([4, 1])
        with fu_c1:
            followup_input = st.text_input("輸入追問問題：", placeholder="例如：如果對方收到存證信函完全不理我，我下一步需要先去調解還是能直接提告？", key="txt_qa_followup_in")
        with fu_c2:
            st.write("")
            btn_followup = st.button("🚀 送出追問", type="primary", use_container_width=True, key="btn_exec_qa_followup")

        if btn_followup and followup_input.strip():
            with st.spinner("AI 顧問正在結合前述案情脈絡，為您深度回答追問..."):
                try:
                    engine = LegalQAEngine()
                    qa_hist = st.session_state.get("qa_conversation_history", [])
                    fu_res = engine.answer_legal_question(
                        question=followup_input.strip(),
                        domain=q_dom,
                        standpoint=res.get("standpoint", USER_STANDPOINTS[0]),
                        output_mode=res.get("output_mode", OUTPUT_MODES[0]),
                        history=qa_hist
                    )
                    st.session_state["current_qa_result"] = fu_res
                    if "qa_conversation_history" not in st.session_state:
                        st.session_state["qa_conversation_history"] = []
                    st.session_state["qa_conversation_history"].append({
                        "question": followup_input.strip(),
                        "answer": fu_res.get("content", "")
                    })
                    st.rerun()
                except Exception as fe:
                    st.error(f"追問回答失敗: {fe}")

# ----------------- 模式: 一鍵 AI 裁判與長篇函釋要旨自動精鍊 (AI 判解精鍊旗艦) -----------------
elif app_mode == MODE_SUMMARIZER or "一鍵 AI 裁判" in app_mode or "AI 摘要" in app_mode or "AI裁判" in app_mode or "AI 裁判" in app_mode:
    st.header("📑 一鍵 AI 裁判與長篇函釋核心要旨自動精鍊系統")
    st.caption("完美對標權威法學庫旗艦功能！支援「先輸入字號秒查」；若大庫未直接收錄，即時引導貼上裁判/函釋全文，由 AI 秒級深度萃取六大標準化法學精髓與司律上位 IRAC 論理！")
    st.divider()

    # 案號縮寫速查語法指引與常見格式說明
    with st.expander("💡 點此查看【案號縮寫速查語法指南】（支援法院簡稱如 SC/SC行/最高院/最高行/智商/智財/高院/台中高分院/各地院、判決/裁定/判例/院字/院解/更審/智財專利家事）", expanded=False):
        st.markdown("""
- **法院簡稱支援**：支援各級法院縮寫開頭或接於年份後，如：
  - `SC108台上1719` / `最高院108台上1719`（最高法院 108 年度台上字第 1719 號判決）
  - `SC行110上15` / `最高行110上15`（最高行政法院 110 年度上字第 15 號判決）
  - `智商111民專上2` / `智財法院111民專上2`（智慧財產及商業法院 111 年度民專上字第 2 號民事判決）
  - `高院108上易50`（臺灣高等法院 108 年度上易字第 50 號判決）
  - `台中高分院107上更一20`（臺灣高等法院臺中分院 107 年度上更(一)字第 20 號判決）
  - `台北地院110重訴12` / `北院110重訴12`（臺灣臺北地方法院 110 年度重訴字第 12 號判決）
  - `士林地院109訴45` / `士院109訴45`（臺灣士林地方法院 109 年度訴字第 45 號判決）
  - `北高行109訴567`（臺北高等行政法院 109 年度訴字第 567 號判決）
  - `最高行109大1裁`（最高行政法院 109 年度大字第 1 號行政大法庭裁定）
- **基本案號縮寫**：如 `108台上908`（代表 108 年度台上字第 908 號民事或刑事裁判，判決與裁定均涵蓋）。
- **指定性質**：案號末尾加 `民`、`刑`、`行`（如 `108台上908民` 代表 108 年度台上字第 908 號民事判決）。
- **指定書類**：
  - 末尾加 `決`：代表判決（如 `108台上908決`、`108台上908民決`）。
  - 末尾加 `裁`：代表裁定（如 `108台上大1719裁`、`108台上908裁`）。
  - 末尾加 `例`：代表判例（如 `40台上86例`、`30上482例`、`65台上2440例`）。
- **司法院歷史核心解釋**：支援 `院字2949`（司法院院字第2949號解釋）、`院解字3001` 或 `院解3001`（院解字第3001號解釋）、`釋字785`、`111憲判16`。
- **更審字軌相容**：不拘括號與數字寫法，`重上更一15`、`重上更(一)15`、`重上更（一）15`、`重上更1` 等價兼容。
- **專業法院特殊字軌**：涵蓋 `加上` / `家上`（家事裁判）、`民著上`（智慧財產著作權）、`行專上`（專利行政訴訟）、`民專上`、`行商上`、`民商上` 等。
- **行政函釋字號**：支援機關字軌公文號與純流水號（如 `經商字第 10702425580 號`、`10702425580`、`金管保產字第 10904918231 號`）。
""")


    # 本機權威庫下拉選單快速挑選
    all_precedents_tags = ["-- 📚 或從本機 3,680+ 筆權威庫中挑選裁判 --"] + get_all_precedent_options()
    default_tag_idx = 0
    cur_cite_val = st.session_state.get("sum_citation_search", "")
    if cur_cite_val:
        for opt_idx, opt in enumerate(all_precedents_tags):
            if cur_cite_val in opt:
                default_tag_idx = opt_idx
                break

    sel_prec_tag = st.selectbox(
        "📚 從本機 3,680+ 筆權威裁判庫快速挑選（支援大法庭、憲判字、高等法院、地院實戰判決）：",
        all_precedents_tags,
        index=default_tag_idx,
        key="sel_prec_for_mode7"
    )
    if sel_prec_tag and sel_prec_tag != "-- 📚 或從本機 3,680+ 筆權威庫中挑選裁判 --":
        selected_case_id = sel_prec_tag.split(" ｜ ")[0].strip()
        if selected_case_id != cur_cite_val:
            st.session_state["sum_citation_search"] = selected_case_id
            st.session_state["citation_rev"] = st.session_state.get("citation_rev", 0) + 1
            st.session_state["sum_input_title"] = ""
            st.session_state["sum_input_text"] = ""
            st.session_state.pop("last_ai_sum_res", None)
            st.rerun()

    # 第一步：先打字號 (裁判案號 / 行政函釋字號)
    cur_cite_val = st.session_state.get("sum_citation_search", "")
    cite_rev = st.session_state.get("citation_rev", 0)
    col_sc1, col_sc2, col_sc3 = st.columns([5, 1.2, 1])
    with col_sc1:
        citation_input = st.text_input(
            "🔍 第一步：請先輸入裁判案號或行政函釋字號（例如：最高行110上15、北高行109訴567、108台上大1719裁、40台上86例、院字2949、重上更一15、經商字第...）：",
            value=cur_cite_val,
            placeholder="輸入裁判字號縮寫或函釋公文字號（支援 最高行110上15、北高行109訴567、108台上908民、108台上大1719裁、40台上86例、院字2949、重上更一15、111憲判16、經商字第...）",
            key=f"txt_citation_search_input_{cite_rev}"
        )
    with col_sc2:
        btn_search_cite = st.button("🔍 查找字號", type="primary", use_container_width=True, key="btn_trigger_search_cite")
    with col_sc3:
        if st.button("✖️ 清除重置", use_container_width=True, key="btn_clear_citation_search"):
            st.session_state["sum_citation_search"] = ""
            st.session_state["citation_rev"] = st.session_state.get("citation_rev", 0) + 1
            st.session_state["sum_input_text"] = ""
            st.session_state["sum_input_title"] = ""
            st.session_state.pop("last_ai_sum_res", None)
            st.rerun()

    # 更新 session_state 中的字號值
    if citation_input != cur_cite_val:
        st.session_state["sum_citation_search"] = citation_input

    # 執行字號查找
    matched_doc = None
    if citation_input.strip():
        matched_doc = find_legal_doc_by_citation(citation_input.strip())

    to_summarize_text = ""
    to_summarize_type = "🏛️ 最高法院/高院裁判書"
    to_summarize_title = ""
    trigger_summarize = False

    # 分支 A：資料庫成功命中 (Found in Database)
    if matched_doc and matched_doc.get("found"):
        st.success(f"🎉 **【資料庫權威收錄命中】**：成功比對本機裁判庫【{matched_doc['title']}】！已即時載入案由爭點、主文心證與歷審完整論理。")

        with st.container(border=True):
            m_c1, m_c2, m_c3 = st.columns([2.2, 1.8, 3])
            m_c1.markdown(f"**🏛️ 機關 / 審理法院**：  \n`{matched_doc.get('court_or_agency', '司法/行政機關')}`")
            m_c2.markdown(f"**📜 文書類型**：  \n`{matched_doc.get('doc_type', '權威判解')}`")
            laws_str = "、".join(matched_doc.get("laws_cited", [])) if matched_doc.get("laws_cited") else "涉及實體法與程序法關鍵爭點法理"
            m_c3.markdown(f"**🎯 關聯重點法條**：  \n`{laws_str}`")

            if matched_doc.get("holding_snippet"):
                st.markdown(f"**💡 裁判 / 函釋核心要旨節錄**：  \n> {matched_doc.get('holding_snippet')}")

        # 官方權威外部資料庫即時查閱
        if matched_doc.get("search_urls"):
            with st.expander("🌐 官方與法學權威資料庫直通查閱（司法院判決書開放系統・法學資料庫・憲法法庭）", expanded=False):
                u_cols = st.columns(min(len(matched_doc["search_urls"]), 4))
                for idx, (label, u_link) in enumerate(list(matched_doc["search_urls"].items())[:4]):
                    with u_cols[idx]:
                        st.link_button(label, u_link, use_container_width=True)

        with st.expander(f"👁️ 檢視或增修自動載入之裁判全文內容（共 {len(matched_doc.get('text', ''))} 字）", expanded=False):
            loaded_text = st.text_area(
                "可直接在此檢視或微調載入之內文：",
                value=matched_doc.get("text", ""),
                height=240,
                key="txt_loaded_hit_text"
            )

        col_act1, col_act2 = st.columns([3, 1])
        with col_act1:
            if st.button("⚡ 一鍵啟動 AI 核心要旨深度精鍊（提煉六大標準化精髓與 IRAC 金句）", type="primary", use_container_width=True, key="btn_run_from_hit"):
                to_summarize_text = loaded_text or matched_doc.get("text", "")
                to_summarize_type = matched_doc.get("doc_type", "裁判書")
                to_summarize_title = matched_doc.get("title", citation_input.strip())
                trigger_summarize = True
        with col_act2:
            if st.button("🔄 重新輸入字號", use_container_width=True, key="btn_reinput_hit"):
                st.session_state["sum_citation_search"] = ""
                st.session_state.pop("last_ai_sum_res", None)
                st.rerun()

    # 分支 B：若輸入字號但資料庫未直接收錄 (Not Found in Database -> 顯示標準公文案號與精準直連導引)
    elif citation_input.strip():
        std_name = matched_doc.get("standard_title") if matched_doc else citation_input.strip()
        parsed_p = matched_doc.get("parsed_info", {}) if matched_doc else {}
        court_identified = parsed_p.get("court") or ("最高法院" if "台上" in std_name else "各級法院")
        
        st.warning(f"🔍 **案號已完成標準化辨識**：【{std_name}】（隸屬：{court_identified}）")
        st.caption("💡 提示：本機裁判庫尚未收錄此案之本機全文，但系統已為您自動組裝**標準法定公文全銜**與**官方司法院裁判書開放系統精準查詢直連**！請點擊下方直通按鈕複製全文，或直接貼於下方：")

        # 呈現直通檢索卡
        if matched_doc and matched_doc.get("search_urls"):
            st.markdown("##### 🌐 點擊以下權威官方資料庫，一鍵查找並複製全文：")
            u_cols = st.columns(min(len(matched_doc["search_urls"]), 4))
            for idx, (label, u_link) in enumerate(list(matched_doc["search_urls"].items())[:4]):
                with u_cols[idx]:
                    st.link_button(label, u_link, use_container_width=True)

        st.divider()
        st.subheader(f"📝 請貼上【{std_name}】之裁判全文或函釋內容")

        col_nf1, col_nf2 = st.columns([3, 1])
        with col_nf1:
            manual_title_in = st.text_input("文書名稱 / 案號全銜（已自動代入標準名稱）：", value=st.session_state.get("sum_input_title", std_name), key="txt_manual_title_nf")
        with col_nf2:
            type_options = ["🏛️ 最高法院/高院裁判書", "📜 憲法法庭判決/釋字", "📑 中央部會行政函釋 (經濟部/金管會)", "📋 行政訴願決定書", "🎓 法學期刊名家評釋論文"]
            suggested_type = matched_doc.get("doc_type") if matched_doc else type_options[0]
            t_idx = type_options.index(suggested_type) if suggested_type in type_options else 0
            manual_type_in = st.selectbox("文書種類：", type_options, index=t_idx, key="sel_manual_type_nf")

        # 支援上傳文字檔 / Word / PDF
        uploaded_doc_file = st.file_uploader("📂 或直接上傳裁判/函釋文字檔案 (.txt, .docx, .pdf)：", type=["txt", "docx", "pdf"], key="file_doc_uploader_nf")
        pasted_text = st.session_state.get("sum_input_text", "")
        if uploaded_doc_file is not None:
            try:
                if uploaded_doc_file.name.endswith(".txt"):
                    pasted_text = uploaded_doc_file.read().decode("utf-8", errors="ignore")
                elif uploaded_doc_file.name.endswith(".docx"):
                    import docx
                    d = docx.Document(uploaded_doc_file)
                    pasted_text = "\n".join([p.text for p in d.paragraphs])
                elif uploaded_doc_file.name.endswith(".pdf"):
                    import pypdf
                    reader = pypdf.PdfReader(uploaded_doc_file)
                    pasted_text = "\n".join([page.extract_text() or "" for page in reader.pages])
                st.success(f"✅ 成功自檔案【{uploaded_doc_file.name}】讀取共 {len(pasted_text)} 字！")
            except Exception as fe:
                st.warning(f"檔案解析提示: {fe}")

        manual_full_text = st.text_area(
            "請在此貼上裁判全文、大法庭裁定理由或主管機關行政函釋全文：",
            value=pasted_text,
            height=300,
            placeholder=f"在此貼上【{std_name}】之裁判書全文、主文或事實與理由段落，AI 即刻為您解析...",
            key="txt_manual_full_text_nf"
        )

        b_nf1, b_nf2 = st.columns([3, 1])
        with b_nf1:
            if st.button("⚡ 啟動專業級 AI 核心要旨深度精鍊（提煉六大標準化精髓與 IRAC 金句）", type="primary", use_container_width=True, key="btn_run_from_manual_nf"):
                if not manual_full_text.strip():
                    st.warning("請先貼上裁判全文或行政函釋！")
                else:
                    to_summarize_text = manual_full_text
                    to_summarize_type = manual_type_in
                    to_summarize_title = manual_title_in or std_name
                    trigger_summarize = True
        with b_nf2:
            if st.button("✖️ 清除內容", use_container_width=True, key="btn_clear_manual_nf"):
                st.session_state["sum_input_text"] = ""
                st.session_state["sum_input_title"] = ""
                st.session_state.pop("last_ai_sum_res", None)
                st.rerun()

    # 分支 C：使用者尚未輸入字號 (初始狀態)
    else:
        st.info("💡 **操作指引**：請於上方輸入裁判案號或部會長篇函釋字號進行秒級查找；若手邊已有現成裁判書全文，亦可直接展開下方【直接手動貼上全文】區域直接貼入！")

        with st.expander("📝 直接手動貼上全文 / 上傳檔案（免輸入字號）", expanded=False):
            col_init1, col_init2 = st.columns([3, 1])
            with col_init1:
                init_title_in = st.text_input("文書名稱 / 案號字號：", value=st.session_state.get("sum_input_title", ""), placeholder="例如：最高法院 108 年度台上字第 908 號...", key="txt_init_title")
            with col_init2:
                type_options = ["🏛️ 最高法院/高院裁判書", "📜 憲法法庭判決/釋字", "📑 中央部會行政函釋 (經濟部/金管會)", "📋 行政訴願決定書", "🎓 法學期刊名家評釋論文"]
                init_type_in = st.selectbox("文書種類：", type_options, index=0, key="sel_init_type")

            init_uploaded_file = st.file_uploader("📂 上傳裁判/函釋文字檔案 (.txt, .docx, .pdf)：", type=["txt", "docx", "pdf"], key="file_init_uploader")
            init_pasted_text = st.session_state.get("sum_input_text", "")
            if init_uploaded_file is not None:
                try:
                    if init_uploaded_file.name.endswith(".txt"):
                        init_pasted_text = init_uploaded_file.read().decode("utf-8", errors="ignore")
                    elif init_uploaded_file.name.endswith(".docx"):
                        import docx
                        d = docx.Document(init_uploaded_file)
                        init_pasted_text = "\n".join([p.text for p in d.paragraphs])
                    elif init_uploaded_file.name.endswith(".pdf"):
                        import pypdf
                        reader = pypdf.PdfReader(init_uploaded_file)
                        init_pasted_text = "\n".join([page.extract_text() or "" for page in reader.pages])
                    st.success(f"✅ 成功自檔案讀取共 {len(init_pasted_text)} 字！")
                except Exception as fe:
                    st.warning(f"檔案解析提示: {fe}")

            init_full_text = st.text_area(
                "請貼上欲進行 AI 摘要之法學裁判全文或行政函釋：",
                value=init_pasted_text,
                height=280,
                placeholder="在此貼上數千至數萬字之法學裁判或公報釋令全文...",
                key="txt_init_full_text"
            )

            if st.button("⚡ 啟動專業級 AI 核心要旨深度精鍊", type="primary", use_container_width=True, key="btn_run_init"):
                if not init_full_text.strip():
                    st.warning("請先貼上裁判全文或行政函釋！")
                else:
                    to_summarize_text = init_full_text
                    to_summarize_type = init_type_in
                    to_summarize_title = init_title_in
                    trigger_summarize = True

    # 共通執行 AI 核心要旨精鍊
    if trigger_summarize and to_summarize_text.strip():
        with st.spinner("AI 大法官書記處法官正在解構案情、主文心證、核心爭點、關鍵法理與二試上位 IRAC 金句..."):
            try:
                summarizer = AILegalSummarizer()
                sum_res = summarizer.summarize(
                    doc_text=to_summarize_text,
                    doc_type=to_summarize_type,
                    title=to_summarize_title
                )
                st.session_state["last_ai_sum_res"] = sum_res
                st.session_state["sum_input_title"] = to_summarize_title
                st.session_state["sum_input_text"] = to_summarize_text
            except Exception as se:
                st.error(f"AI 摘要失敗: {se}")

    # 成果展示區 (標準化六大核心要旨報告)
    if "last_ai_sum_res" in st.session_state:
        sum_res = st.session_state["last_ai_sum_res"]
        active_title = sum_res.get("title") or st.session_state.get("sum_input_title") or "法學文書"
        st.divider()
        st.markdown(f"### 📑 【{active_title}】AI 專業級 核心要旨精鍊報告")
        st.markdown(sum_res.get("markdown_result", ""))

        st.divider()
        st.subheader("🔗 摘要成果一鍵轉化為司律考卷戰力：")
        s_act1, s_act2, s_act3 = st.columns(3)
        clean_act_title = re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '_', active_title)[:15]
        with s_act1:
            st.download_button(
                "📥 下載完整 Markdown 摘要報告",
                data=sum_res.get("markdown_result", ""),
                file_name=f"AI摘要_{clean_act_title}.md",
                mime="text/markdown",
                use_container_width=True
            )
        with s_act2:
            if st.button("📝 帶入試卷評分 (作為評分標準)", use_container_width=True, key="btn_sum_to_eval"):
                st.session_state["question_text_content"] = f"【核心爭點題目】：\n請就【{active_title}】之案例事實與爭點深入申論其法律效果與實務見解。"
                st.session_state["rubric_text_content"] = sum_res.get("markdown_result", "")
                st.session_state["imported_from_bank_label"] = f"AI裁判摘要標準【{active_title[:15]}】"
                st.session_state["app_mode"] = MODE_HOME
                st.rerun()
        with s_act3:
            if st.button("📖 帶入高分擬答生成", use_container_width=True, key="btn_sum_to_ans"):
                m4_q_text = f"請就【{active_title}】所涉及之核心法律爭點，依 IRAC 架構撰寫標準上位卷擬答。"
                st.session_state["m4_target_question"] = m4_q_text
                st.session_state["m4_text_area_input"] = m4_q_text
                st.session_state["app_mode"] = mode_options[3]
                st.rerun()

    # 批次匯入司法院開放資料擴充大庫區塊
    st.divider()
    with st.expander("📦 【大庫擴充管理】批次匯入司法院裁判書開放資料 (Open Data ZIP/JSON) 至本機庫", expanded=False):
        op_tab_zip, op_tab_api = st.tabs([
            "📂 方式一：手動上傳司法院 Open Data 打包檔 (RAR / ZIP / 7Z / JSON)",
            "🌐 方式二：使用司法院開放平臺帳號密碼 API 直接連線同步"
        ])

        with op_tab_zip:
            st.markdown("""
司法院資料開放平臺（[`opendata.judicial.gov.tw`](https://opendata.judicial.gov.tw/)）所提供之歷史各級法院按月份打包之裁判書資料集（常以 **RAR** 或 **ZIP** 壓縮格式封裝，內部為各裁判書之 JSON 檔案）：

#### 📥 如何在司法院官網取得裁判 RAR 檔？
1. 前往 **[司法院資料開放平臺 (opendata.judicial.gov.tw)](https://opendata.judicial.gov.tw/)** 並註冊/登入會員。
2. 進入 **「資料集下載」** ➔ **「裁判書資料專區」**。
3. 選擇所需之年度與月份（點擊下載對應之 `.rar` 或 `.zip` 壓縮檔）。
4. 下載後**無需手動解壓**，直接上傳下方檔案框，系統已內建專用解壓核心，自動解壓縮內含之 JSON 裁判檔並秒級入庫！

> 💡 **若手邊暫無 RAR/ZIP 檔案？**  
> 完全不影響使用！請直接在上方輸入字號縮寫（如 `最高行108上625`、`最高行110上15`、`108台上大1719裁`），系統會立即產生**標準案號與官方判決全文直通連結**，點擊複製全文貼入上方文字框，AI 會在 3 秒內自動完成六大精髓與 IRAC 深度萃取！
""")
            uploaded_op_files = st.file_uploader("📂 選擇司法院開放資料檔案 (.rar, .zip, .7z 或 .json，支援多檔選取)：", type=["rar", "zip", "7z", "json"], accept_multiple_files=True, key="uploader_opendata_zip")

        with op_tab_api:
            st.markdown("""
#### 🌐 司法院官方 API (RESTful) 直連登入同步
依照司法院官方 API 規範，只要輸入您在司法院資料開放平臺註冊之**帳號**與**密碼**，系統將自動向 `https://data.judicial.gov.tw/jdg/api/Auth` 換取官方驗證 Token，並直接透過官方 API 調閱最新裁判書存入本地大庫！

> ⚠️ **官方連線與憑證注意**：  
> 1. 司法院伺服器之 SSL 憑證缺少 Subject Key Identifier，系統已自動啟用安全略過模式確保暢通連線。  
> 2. 司法院官方 API 規範：伺服器每日僅於**凌晨 0 時至 6 時**提供大量下載與清單服務，其餘時段司法院端可能限制訪問。
""")
            col_api_u, col_api_p = st.columns(2)
            with col_api_u:
                api_user_in = st.text_input("司法院開放平臺帳號 (user)：", key="api_judicial_user")
            with col_api_p:
                api_pwd_in = st.text_input("司法院開放平臺密碼 (password)：", type="password", key="api_judicial_pwd")

            col_api_btn1, col_api_btn2 = st.columns([2, 1])
            with col_api_btn1:
                btn_test_auth = st.button("🔑 測試連線並換取 6 小時官方 Token", use_container_width=True, key="btn_test_judicial_auth")
            with col_api_btn2:
                btn_clear_token = st.button("✖️ 清除 Token", use_container_width=True, key="btn_clear_judicial_token")
                if btn_clear_token:
                    st.session_state.pop("judicial_api_token", None)
                    st.rerun()

            if btn_test_auth:
                if not api_user_in.strip() or not api_pwd_in.strip():
                    st.warning("請先輸入司法院開放平臺帳號與密碼！")
                else:
                    with st.spinner("正在連線至司法院驗證伺服器 (https://data.judicial.gov.tw/jdg/api/Auth)..."):
                        from import_judicial_opendata import JudicialOpenDataClient
                        client = JudicialOpenDataClient()
                        auth_res = client.authenticate(api_user_in.strip(), api_pwd_in.strip())
                        if auth_res.get("success"):
                            st.session_state["judicial_api_token"] = auth_res["token"]
                            st.success(f"🎉 司法院官方驗證成功！取得 Token：`{auth_res['token'][:8]}...`（有效時間 6 小時）")
                        else:
                            st.error(f"❌ 司法院驗證失敗：{auth_res.get('error')}")

            # 若已有 Token，提供進一步直接拉取裁判功能
            cur_token = st.session_state.get("judicial_api_token", "")
            if cur_token:
                st.info(f"✅ **目前授權狀態**：已取得司法院官方通行 Token (`{cur_token[:10]}...`)")
                st.markdown("##### 🚀 依裁判案號或 JID 直接向司法院 API 抓取入庫：")
                col_jid_in, col_jid_act = st.columns([3, 1])
                with col_jid_in:
                    inp_api_jid = st.text_input(
                        "輸入欲調閱之裁判 JID (例如：`CHDM,100,訴,1552,20130517,2` 或 `TPAA,108,上,625,20191219,1`)：",
                        placeholder="例如：TPAA,108,上,625,20191219,1",
                        key="inp_api_fetch_jid"
                    )
                with col_jid_act:
                    btn_fetch_jdoc = st.button("📥 線上抓取入庫", type="primary", use_container_width=True, key="btn_fetch_api_jdoc")

                if btn_fetch_jdoc and inp_api_jid.strip():
                    with st.spinner(f"正在向司法院 API 調閱【{inp_api_jid.strip()}】裁判全文..."):
                        from import_judicial_opendata import JudicialOpenDataClient, parse_official_opendata_record, OUTPUT_CATALOG_PATH, REPO_CATALOG_PATH
                        import json
                        client = JudicialOpenDataClient()
                        doc_res = client.fetch_jdoc(inp_api_jid.strip(), cur_token)
                        if doc_res.get("success"):
                            doc_data = doc_res.get("data", {})
                            parsed_doc = parse_official_opendata_record(doc_data)
                            if parsed_doc and parsed_doc.get("case_id"):
                                with open(OUTPUT_CATALOG_PATH, "r", encoding="utf-8") as f:
                                    cur_c = json.load(f)
                                cur_c.append(parsed_doc)
                                with open(OUTPUT_CATALOG_PATH, "w", encoding="utf-8") as f:
                                    json.dump(cur_c, f, ensure_ascii=False, indent=2)
                                with open(REPO_CATALOG_PATH, "w", encoding="utf-8") as f:
                                    json.dump(cur_c, f, ensure_ascii=False, indent=2)
                                st.success(f"🎉 成功由司法院 API 調閱並入庫：【{parsed_doc['title']}】！全文共 {len(parsed_doc.get('full_text',''))} 字。")
                            else:
                                st.warning("裁判資料已下載，但欄位格式解析異常。")
                        else:
                            st.error(f"調閱失敗：{doc_res.get('error')}（提示：官方 API 開放時段為每日凌晨 0 時至 6 時）")

                st.markdown("---")
                st.markdown("##### 📋 步驟二：自動拉取司法院最新異動裁判清單 (`JList`) 並批次下載入庫")
                st.caption("⚠️ **重要官方限制**：司法院官方 API 下載服務依規定**僅於每日凌晨 00:00~06:00 開放下載**，其餘時段若伺服器返回限制屬官方正常機制。")
                
                col_jl_s, col_jl_btn = st.columns([2, 1])
                with col_jl_s:
                    batch_jlist_count = st.slider("選擇批次抓取異動裁判篇數：", min_value=1, max_value=30, value=10, key="slider_jlist_fetch_n")
                with col_jl_btn:
                    st.write("")
                    btn_exec_jlist = st.button("🚀 自動批次抓取異動入庫", type="primary", use_container_width=True, key="btn_run_jlist_batch")

                if btn_exec_jlist:
                    with st.spinner("正在拉取司法院 7 日前異動裁判清單 (JList)..."):
                        import importlib, import_judicial_opendata
                        importlib.reload(import_judicial_opendata)
                        client = import_judicial_opendata.SafeJudicialOpenDataClient()
                        jlist_res = client.fetch_jlist(cur_token)
                        if not jlist_res.get("success"):
                            st.error(f"❌ 取得異動清單失敗：{jlist_res.get('error')}（提醒：官方僅於每日凌晨 00:00~06:00 開放調閱）")
                        else:
                            jlist_data = jlist_res.get("data", [])
                            jids = []
                            if isinstance(jlist_data, list):
                                for item in jlist_data:
                                    if isinstance(item, str):
                                        jids.append(item)
                                    elif isinstance(item, dict) and "jid" in item:
                                        jids.append(item["jid"])
                            elif isinstance(jlist_data, dict):
                                jids = jlist_data.get("list", []) or jlist_data.get("jids", [])
                            
                            if not jids:
                                st.info("目前無異動清單資料。")
                            else:
                                st.write(f"共取得 {len(jids)} 筆異動 JID，開始批次下載前 {min(batch_jlist_count, len(jids))} 篇...")
                                downloaded_n = 0
                                pb = st.progress(0)
                                for idx, jid in enumerate(jids[:batch_jlist_count]):
                                    doc_r = client.fetch_jdoc(jid, cur_token)
                                    if doc_r.get("success"):
                                        parsed = import_judicial_opendata.parse_official_opendata_record(doc_r.get("data", {}))
                                        if parsed and parsed.get("case_id"):
                                            cat_p = Path(RAW_DATA_DIR) / "precedents_catalog.json"
                                            if cat_p.exists():
                                                try:
                                                    cur_list = json.loads(cat_p.read_text(encoding="utf-8"))
                                                    cur_list.append(parsed)
                                                    cat_p.write_text(json.dumps(cur_list, ensure_ascii=False, indent=2), encoding="utf-8")
                                                except Exception:
                                                    pass
                                            downloaded_n += 1
                                    pb.progress((idx + 1) / min(batch_jlist_count, len(jids)))
                                st.success(f"🎉 成功批次同步入庫 {downloaded_n} 篇最新司法院裁判！")
        if uploaded_op_files:
            if st.button("🚀 立即解析並擴充至本機裁判庫", type="primary", use_container_width=True, key="btn_exec_opendata_expand"):
                files_to_process = uploaded_op_files if isinstance(uploaded_op_files, list) else [uploaded_op_files]
                with st.spinner(f"正在深度解壓並解析 {len(files_to_process)} 個上傳檔案中的裁判書..."):
                    try:
                        from import_judicial_opendata import parse_official_opendata_record, extract_archive_to_temp, OUTPUT_CATALOG_PATH, REPO_CATALOG_PATH
                        import tempfile, json
                        from pathlib import Path
                        
                        incoming_records = []
                        for up_f in files_to_process:
                            fn_lower = up_f.name.lower()
                            if fn_lower.endswith((".zip", ".rar", ".7z")):
                                with tempfile.TemporaryDirectory() as td:
                                    archive_tmp = Path(td) / up_f.name
                                    with open(archive_tmp, "wb") as f_up:
                                        f_up.write(up_f.read())
                                    
                                    ext_dir = Path(td) / "extracted"
                                    ext_dir.mkdir(parents=True, exist_ok=True)
                                    
                                    ok = extract_archive_to_temp(archive_tmp, ext_dir)
                                    if ok:
                                        for jf_path in ext_dir.glob("**/*.json"):
                                            try:
                                                with open(jf_path, "r", encoding="utf-8") as jf:
                                                    c = json.load(jf)
                                                    items = c if isinstance(c, list) else [c]
                                                    for it in items:
                                                        p = parse_official_opendata_record(it)
                                                        if p and p.get("case_id"):
                                                            incoming_records.append(p)
                                            except Exception:
                                                continue
                                    else:
                                        st.warning(f"檔案【{up_f.name}】自動解壓未成功。若為特殊壓縮格式，建議於本機解壓出 .json 檔案後多選拖曳上傳！")
                            elif fn_lower.endswith(".json"):
                                try:
                                    c = json.load(up_f)
                                    items = c if isinstance(c, list) else [c]
                                    for it in items:
                                        p = parse_official_opendata_record(it)
                                        if p and p.get("case_id"):
                                            incoming_records.append(p)
                                except Exception:
                                    pass
                        
                        if not incoming_records:
                            st.warning("檔案中未找到符合司法院標準欄位之裁判書 JSON（請確認壓縮檔內含有裁判書 .json 檔案）。")
                        else:
                            # 讀取現有大庫並合併
                            with open(OUTPUT_CATALOG_PATH, "r", encoding="utf-8") as f:
                                cur_catalog = json.load(f)
                            existing_ids = {x.get("case_id") for x in cur_catalog if x.get("case_id")}
                            
                            new_added = 0
                            for rec in incoming_records:
                                cid = rec.get("case_id")
                                if cid and cid not in existing_ids:
                                    cur_catalog.append(rec)
                                    existing_ids.add(cid)
                                    new_added += 1
                            
                            # 存檔
                            with open(OUTPUT_CATALOG_PATH, "w", encoding="utf-8") as f:
                                json.dump(cur_catalog, f, ensure_ascii=False, indent=2)
                            with open(REPO_CATALOG_PATH, "w", encoding="utf-8") as f:
                                json.dump(cur_catalog, f, ensure_ascii=False, indent=2)
                            
                            st.success(f"🎉 成功擴充 {new_added:,} 筆裁判！本機裁判大庫總筆數已提升至：{len(cur_catalog):,} 筆！")
                            st.rerun()
                    except Exception as ie:
                        st.error(f"開放資料匯入失敗: {ie}")

# ----------------- 模式 6: 智慧六法與條文判解綜合標註 (法條・沿革・爭點・筆記) -----------------
elif app_mode == MODE_SIX_CODES or "智慧六法" in app_mode:
    st.header("⚖️ 智慧六法全書與條文爭點判解綜合標註系統")
    st.write("全面收錄全台 **2,053 部國家法律、法規命令與施行細則，共 62,342 條法定條文，及 600+ 則中央部會權威行政函釋**，直接在條文下方完整串接**條文結構**、**立法理由與沿革**、**憲判字/最高法院大法庭權威裁判**、**學說肯否二說**、**法規命令施行細則全文點閱**、**主管機關權威函釋**及**考生個人手寫讀書筆記**！")

    # 1. 導航選擇列
    col_b, col_l, col_q = st.columns([1, 1, 2])
    with col_b:
        branch_options = list(SIX_CODES_TAXONOMY.keys())
        default_br = st.session_state.get("six_codes_branch", branch_options[0])
        br_idx = branch_options.index(default_br) if default_br in branch_options else 0
        selected_branch = st.selectbox("1. 選擇法學門類：", branch_options, index=br_idx, key=f"sel_br_widget_{default_br}")
        st.session_state["six_codes_branch"] = selected_branch
    with col_l:
        available_laws = get_laws_in_branch(selected_branch)
        default_law = st.session_state.get("six_codes_law", available_laws[0] if available_laws else "")
        law_idx = available_laws.index(default_law) if default_law in available_laws else 0
        selected_law = st.selectbox("2. 選擇法典名稱：", available_laws, index=law_idx, key=f"sel_law_widget_{default_law}")
        st.session_state["six_codes_law"] = selected_law
    with col_q:
        default_kw = st.session_state.get("six_codes_search_kw", "")
        search_kw = st.text_input(
            "3. 搜尋條號（如 184、19、64、759-1）或條文關鍵字：",
            value=default_kw,
            placeholder="輸入條號或法理關鍵字（如：純粹經濟、借名登記、原因自由行為）...",
            key=f"search_kw_widget_{st.session_state.get('six_codes_kw_rev', 0)}"
        )
        st.session_state["six_codes_search_kw"] = search_kw
        st.caption("💡 **專業布林精準搜尋**：支援 `＆`（且）、`＋`（或）、`－`（排除）、`( )`（優先組合）。例：`(侵權行為 ＋ 債務不履行) ＆ (純粹經濟 － 故意)`")

    # 🌟 新功能：更新六法按鈕（按下去之後六法會自動聯網更新最近的修法，同步至本機大典）
    up_col1, up_col2 = st.columns([3, 1])
    with up_col1:
        st.caption(f"💡 目前法學大庫已收錄 **{selected_law}**。若立法院近期三讀通過修正條文，點擊右方按鈕即可自動連線全國法規會與立法院公報更新！")
    with up_col2:
        if st.button(f"🔄 更新六法（【{selected_law}】最新修法）", use_container_width=True, key=f"btn_update_law_{selected_law}"):
            with st.spinner(f"正在聯網比對並更新【{selected_law}】最新公布條文與立法理由..."):
                update_res = update_law_amendments(selected_law)
                clear_six_codes_cache()
                st.session_state[f"last_amendment_res_{selected_law}"] = update_res
                st.toast(f"✅ 【{selected_law}】修法資料更新完成！", icon="🎉")

    if st.session_state.get(f"last_amendment_res_{selected_law}"):
        last_res = st.session_state.get(f"last_amendment_res_{selected_law}")
        with st.expander(f"🆕 【{selected_law}】最新修法更新報告 ｜ 📅 {last_res.get('latest_amendment_date', '最新修正公布')}", expanded=True):
            st.markdown(f"**🌟 修法重點摘要：** {last_res.get('summary', '')}")
            st.caption(f"更新狀態：`{last_res.get('status')}` ｜ 本次更新條文數：`{last_res.get('amended_count', 0)}` 條")
            for am_item in last_res.get("amended_articles", []):
                st.markdown(f"##### 📌 {am_item.get('article_no')}")
                st.info(f"**最新施行條文全文：**\n{am_item.get('new_content', '')}")
                if am_item.get('amendment_reason'):
                    st.markdown(f"🏛️ **立法院官方立法理由：**\n{am_item.get('amendment_reason')}")
                if am_item.get('exam_points'):
                    st.success(f"✍️ **司律二試國考作答熱點：**\n{am_item.get('exam_points')}")
                st.markdown("---")

    # 若當前選擇者為法規命令或細則，提示授權母法並提供快速返回母法按鈕
    if any(s in selected_law for s in ["辦法", "細則", "準則", "規則", "規程", "標準"]):
        parent_candidate = None
        for p_cand in ["公司法", "證券交易法", "民法", "專利法", "商標法", "著作權法", "勞動基準法", "行政程序法", "民事訴訟法", "刑事訴訟法"]:
            if p_cand in selected_law:
                parent_candidate = p_cand
                break
        if not parent_candidate:
            if "公司" in selected_law: parent_candidate = "公司法"
            elif "證券" in selected_law or "董事會" in selected_law: parent_candidate = "公司法"
            elif "專利" in selected_law: parent_candidate = "專利法"
            elif "商標" in selected_law: parent_candidate = "商標法"
            elif "著作" in selected_law: parent_candidate = "著作權法"
            elif "勞動" in selected_law or "請假" in selected_law: parent_candidate = "勞動基準法"

        if parent_candidate:
            bc_col1, bc_col2 = st.columns([3, 1])
            with bc_col1:
                st.info(f"📘 您目前正在研讀法規命令/施行細則：**《{selected_law}》**（授權母法為【{parent_candidate}】）")
            with bc_col2:
                if st.button(f"🔙 返回母法【{parent_candidate}】", use_container_width=True):
                    st.session_state["six_codes_law"] = parent_candidate
                    st.session_state["six_codes_search_kw"] = ""
                    st.session_state["six_codes_kw_rev"] = st.session_state.get("six_codes_kw_rev", 0) + 1
                    st.rerun()

    # 完整法律/法規命令立法沿革與歷次修正紀錄 (共 XX 次修正公報)
    law_hist_info = get_law_legislative_history(selected_law)
    total_amendments = law_hist_info.get("total_amendments", 0)
    timeline = law_hist_info.get("timeline", [])

    if total_amendments > 0:
        first_date = timeline[0].get("date", "") if timeline else ""
        latest_date = timeline[-1].get("date", "") if timeline else ""
        date_summary = f"（{first_date} 制定公布 ➔ {latest_date} 最新修正）" if first_date and latest_date else ""
        with st.expander(f"📜 【{selected_law}】完整立法沿革與歷次修正公報 ｜ 🏛️ 共歷經 {total_amendments} 次制定/修正公布 {date_summary}", expanded=False):
            st.markdown(f"#### 📜 《{selected_law}》法定沿革與歷次修正公報資料庫")
            st.caption(f"法規類別：`{law_hist_info.get('category', '全國法規')}` ｜ 法規性質：`{law_hist_info.get('type', '法律')}` ｜ 全國法規代碼 (PCode)：`{law_hist_info.get('pcode', 'N/A')}`")

            hist_kw = st.text_input(f"在《{selected_law}》歷次沿革公報中搜尋（如年份、條號、總統令號、修正要點）：", key=f"hist_kw_{selected_law}")
            filtered_timeline = timeline
            if hist_kw:
                filtered_timeline = [t for t in timeline if hist_kw in t.get("content", "") or hist_kw in t.get("date", "") or hist_kw in t.get("decree", "")]
                st.caption(f"找到 {len(filtered_timeline)} 筆符合「{hist_kw}」之修正紀錄：")

            with st.container(height=350):
                for t in reversed(filtered_timeline):
                    seq_badge = f"第 {t['seq']} 次修正" if t['seq'] > 1 else "制定發布"
                    st.markdown(f"**🏷️ 【{seq_badge}】📅 {t['date']} ｜ {t['decree']} ｜ `{t['action']}`**")
                    st.info(t['content'])
                    st.markdown("---")

    # 跨部會中央主管機關行政函釋快速檢索專區
    with st.expander("🏛️ 中央主管機關行政函釋（經濟部/智財局/金管會/法務部/勞動部/財政部）跨部會速查庫 (已收錄 600+ 則)", expanded=False):
        st.markdown("全面收錄中央主管機關之具拘束力行政指導、令函與重要解釋。您可直接依主管部會或關鍵字查詢：")
        all_rulings_pool = get_all_administrative_rulings()
        agencies_filter = ["全部機關", "經濟部商業司", "經濟部商業發展署", "經濟部智慧財產局", "金融監督管理委員會", "法務部", "勞動部", "財政部賦稅署"]
        c_a1, c_a2 = st.columns([1, 2])
        with c_a1:
            sel_agency = st.selectbox("主管機關篩選：", agencies_filter, key="browse_agency_filter")
        with c_a2:
            search_ruling_kw = st.text_input("輸入函釋字號、法條或關鍵字（如：大同條款、生成式AI、內線交易、合理保密措施...）：", key="browse_ruling_kw")

        filtered_rulings = all_rulings_pool
        if sel_agency != "全部機關":
            filtered_rulings = [r for r in filtered_rulings if sel_agency in r.get("agency", "")]
        if search_ruling_kw:
            filtered_rulings = [r for r in filtered_rulings if search_ruling_kw in r.get("doc_number", "") or search_ruling_kw in r.get("title", "") or search_ruling_kw in r.get("holding", "") or search_ruling_kw in r.get("law_name", "")]

        st.caption(f"共篩選出 **{len(filtered_rulings)} 筆** 主管機關行政函釋：")
        with st.container(height=350):
            for r in filtered_rulings:
                st.markdown(f"**🏢 【{r.get('agency')}】`{r.get('doc_number')}` ｜ {r.get('law_name')} {r.get('article_target', '')}**")
                st.markdown(f"**🌟 {r.get('title')}** (📅 {r.get('date')})")
                if r.get('exam_point_hint'):
                    st.caption(f"✍️ **國考作答提示：** {r.get('exam_point_hint')}")
                st.markdown("---")

    # 執行檢索
    matched_articles = search_articles(keyword=search_kw, selected_law=selected_law, selected_branch=selected_branch)

    st.markdown(f"**📚 當前檢索結果**：共找到 **{len(matched_articles)}** 條條文")

    if not matched_articles:
        st.info("查無符合條文，請嘗試更換條號數字或搜尋關鍵字。")
    else:
        for idx, art in enumerate(matched_articles[:30]):
            lname = art.get("law_name", "")
            ano = art.get("article_no", "")
            content = art.get("content", "")

            anno = get_article_annotations(law_name=lname, article_no=ano, content=content)
            precedents = anno.get("precedents", [])
            notes = anno.get("notes", [])

            # 整合預載之核心法規命令與六法中所有關聯命令（包含公司登記辦法、公開發行公司董事會議事辦法等）
            raw_key_regs = get_law_key_regulations(lname)
            raw_mapped_orders = anno.get("orders", [])

            key_regulations = []
            seen_reg_names = set()
            for r in raw_key_regs:
                r_name = r.get("name")
                if r_name and r_name not in seen_reg_names:
                    seen_reg_names.add(r_name)
                    key_regulations.append(r)

            for o in raw_mapped_orders:
                o_name = o.get("name")
                if o_name and o_name not in seen_reg_names:
                    seen_reg_names.add(o_name)
                    o_arts = o.get("articles", [])
                    key_regulations.append({
                        "name": o_name,
                        "type": o.get("type", "法規命令"),
                        "desc": o.get("desc", ""),
                        "article_count": o.get("articles_count", len(o_arts)),
                        "articles": o_arts,
                        "details": {
                            "name": o_name,
                            "category": o.get("category", "中央行政部會"),
                            "modified_date": o.get("modified_date", ""),
                            "url": "",
                            "total_articles": len(o_arts),
                            "articles": [{"no": a.get("article_no", ""), "content": a.get("content", "")} for a in o_arts]
                        } if o_arts else get_regulation_full_details(o_name)
                    })

            admin_rulings = anno.get("admin_rulings", []) or get_admin_rulings_for_article(lname, ano)

            legis_data = anno.get("legislative_details", {}) or get_article_legislative_details(lname, ano, content)
            curated_amends = legis_data.get("curated_amendments", [])
            timeline_hits = legis_data.get("timeline_hits", [])
            total_amends_display = len(curated_amends) if curated_amends else len(timeline_hits)

            questions = anno.get("questions", [])
            handouts = anno.get("handouts", [])

            combined_materials = handouts + notes

            badge_amend = " ｜ 🆕 【最新修正施行】" if art.get("is_latest_amendment") else ""
            badge_prec = f" ｜ 🏛️ 【收錄 {len(precedents)} 筆大法庭/憲判字】" if precedents else ""
            badge_orders_rulings = f" ｜ 📋 【{len(key_regulations)} 部法規/細則 ＋ {len(admin_rulings)} 筆主管函釋】" if (key_regulations or admin_rulings) else ""
            badge_legis = f" ｜ 🕰️ 【{total_amends_display} 次修法對照】" if total_amends_display > 0 else ""
            badge_materials = f" ｜ 📘 【收錄 {len(combined_materials)} 份名師講義與個人讀書筆記】" if combined_materials else ""

            exp_label = f"📖 【{lname} {ano}】{badge_amend}{badge_prec}{badge_orders_rulings}{badge_legis}{badge_materials}"
            with st.expander(exp_label, expanded=bool(idx < 2 or art.get("is_latest_amendment"))):
                if art.get("is_latest_amendment"):
                    st.success(f"🆕 **此條文為立法院最新三讀通過並經總統府公布之修正條文！** (施行日期：{art.get('modified_date', '最新公布')})")
                    if art.get("amendment_reason"):
                        st.markdown(f"🏛️ **官方立法理由：** {art.get('amendment_reason')}")
                    if art.get("exam_points"):
                        st.markdown(f"✍️ **國考作答熱點：** {art.get('exam_points')}")
                st.markdown(f"> **📜 條文全文**：\n> {content}")

                tab_prec, tab_orders_rulings, tab_legis, tab_materials, tab_ai = st.tabs([
                    f"🏛️ 權威司法判解 ({len(precedents)} 筆)",
                    f"📋 關聯法規命令、施行細則與主管機關行政函釋 ({len(key_regulations)} 部法規・{len(admin_rulings)} 筆函釋)",
                    f"🕰️ 立法理由與歷史條文 ({total_amends_display} 次修法對照)",
                    f"📘 關聯名師講義與個人手寫讀書筆記 ({len(combined_materials)} 份・線上閱讀 PDF)",
                    "🤖 AI 深度釋析與作答模版"
                ])

                with tab_prec:
                    if precedents:
                        for p_idx, p in enumerate(precedents):
                            st.markdown(f"**【{p.get('level')}】`{p.get('case_id')}`** ｜ **{p.get('title')}**")
                            st.info(f"**核心要旨/主文：**\n{p.get('holding')}")
                            if p.get('scholarly_views'):
                                st.caption(f"📚 **學說實務對比：** {p.get('scholarly_views')}")
                            if p.get('exam_application_hint'):
                                st.success(f"✍️ **國考作答指示：** {p.get('exam_application_hint')}")

                            c_p1, c_p2 = st.columns(2)
                            with c_p1:
                                if st.button(f"⚡ 產出本判決 AI 深度摘要", key=f"btn_tab_sum_{idx}_{p_idx}", use_container_width=True):
                                    st.session_state["sum_citation_search"] = p.get("case_id", "")
                                    st.session_state["citation_rev"] = st.session_state.get("citation_rev", 0) + 1
                                    st.session_state["app_mode"] = mode_options[6]
                                    st.rerun()
                            with c_p2:
                                if st.button(f"🔄 帶入進行案例橫向比對", key=f"btn_tab_cmp_{idx}_{p_idx}", use_container_width=True):
                                    st.session_state["target_compare_case_a"] = p.get("case_id", "")
                                    st.session_state["target_compare_topic"] = f"{lname} {ano} 相關裁判見解分歧"
                                    st.session_state["m5_sub_mode_idx"] = 4
                                    st.session_state["app_mode"] = mode_options[4]
                                    st.rerun()
                            st.markdown("---")
                    else:
                        st.caption("本機權威判解庫中目前無直接標註此條文之大法庭裁定，可前往【統一法學檢索樞紐】或由 AI 進行歷審精選裁判與學說補強。")

                with tab_orders_rulings:
                    st.markdown(f"#### 📋 【{lname} {ano}】關聯法規命令、施行細則與主管機關行政函釋")
                    st.caption("全面整合 **授權法規命令與細則全文點閱**、**主管機關行政指導與解釋令函**，以及**跨法典法律/命令快速直通聯結**！")

                    # 第一區塊：關聯法規命令與施行細則
                    st.markdown("##### 📘 一、授權法規命令、施行細則與相關關聯法規全文")
                    if key_regulations:
                        st.caption(f"已串接行政院及主管部會發布之法規命令與細則全文。點擊下方各命令卡片即可展開閱讀完整條文：")
                        for r_idx, reg in enumerate(key_regulations):
                            reg_name = reg["name"]
                            reg_type = reg["type"]
                            reg_desc = reg["desc"]
                            art_count = reg.get("article_count", 0)
                            reg_details = reg.get("details")

                            badge_count = f"共 {art_count} 條全文" if art_count > 0 else "施行細則"
                            with st.expander(f"📘 《{reg_name}》 (`{reg_type}`) ｜ 📚 {badge_count}", expanded=(r_idx == 0 and idx == 0)):
                                st.markdown(f"**規範主旨/適用範圍**：\n{reg_desc}")
                                if reg.get("key_articles_hint"):
                                    st.info(f"💡 **國考與實務核心考點條文**：\n{reg['key_articles_hint']}")

                                raw_arts = (reg_details.get("articles") if reg_details else None) or reg.get("articles") or []
                                arts = []
                                for a in raw_arts:
                                    a_no = a.get("no") or a.get("article_no") or ""
                                    a_c = a.get("content") or ""
                                    if a_no or a_c:
                                        arts.append({"no": a_no, "content": a_c})

                                if arts:
                                    st.markdown(f"##### 📖 《{reg_name}》條文全文點閱系統 (共收錄 {len(arts)} 條)")

                                    read_mode = st.radio(
                                        f"條文檢視模式 ({reg_name})：",
                                        ["🔍 依條號選取詳細研讀", "📜 展開瀏覽全法規所有條文", "🔎 條文內關鍵字搜尋"],
                                        horizontal=True,
                                        key=f"reg_mode_{idx}_{r_idx}"
                                    )

                                    if read_mode == "🔍 依條號選取詳細研讀":
                                        art_options = [f"{a['no']} - {a['content'][:35]}..." if len(a['content']) > 35 else f"{a['no']} - {a['content']}" for a in arts]
                                        chosen_art_str = st.selectbox(
                                            f"請選擇欲研讀之條號：",
                                            options=art_options,
                                            key=f"sel_art_{idx}_{r_idx}"
                                        )
                                        chosen_idx = art_options.index(chosen_art_str)
                                        target_art = arts[chosen_idx]
                                        st.markdown(f"**【{target_art['no']}】**")
                                        st.info(target_art['content'])
                                    elif read_mode == "📜 展開瀏覽全法規所有條文":
                                        with st.container(height=350):
                                            for a in arts:
                                                st.markdown(f"**{a['no']}**")
                                                st.markdown(f"> {a['content']}")
                                                st.markdown("---")
                                    elif read_mode == "🔎 條文內關鍵字搜尋":
                                        sub_kw = st.text_input(f"輸入在《{reg_name}》內搜尋之文字：", key=f"sub_kw_{idx}_{r_idx}")
                                        if sub_kw:
                                            hit_arts = [a for a in arts if sub_kw in a['no'] or sub_kw in a['content']]
                                            st.caption(f"在《{reg_name}》中找到 {len(hit_arts)} 條包含「{sub_kw}」之條文：")
                                            for a in hit_arts:
                                                st.markdown(f"**{a['no']}**")
                                                st.markdown(f"> {a['content']}")
                                                st.markdown("---")
                                        else:
                                            st.caption("請輸入關鍵字以即時過濾法規命令條文。")

                                # 跳轉與外鏈按鈕列
                                btn_col1, btn_col2 = st.columns([1, 1])
                                with btn_col1:
                                    if st.button(f"📖 在六法主檢索區開啟《{reg_name}》全文", key=f"btn_jump_order_{idx}_{r_idx}", type="primary"):
                                        st.session_state["six_codes_law"] = reg_name
                                        for br_name, br_laws in SIX_CODES_TAXONOMY.items():
                                            if reg_name in br_laws:
                                                st.session_state["six_codes_branch"] = br_name
                                                break
                                        st.session_state["six_codes_search_kw"] = ""
                                        st.session_state["six_codes_kw_rev"] = st.session_state.get("six_codes_kw_rev", 0) + 1
                                        st.rerun()
                                Dangerously_url = reg_details.get("url") if reg_details else ""
                                with btn_col2:
                                    if Dangerously_url:
                                        st.link_button(f"🌐 前往全國法規資料庫官方查看《{reg_name}》", Dangerously_url)
                    else:
                        st.info("此法規母法目前無直接對應之核心法規命令，或直接以母法本體為規範依據。")

                    # 任意快速直通調閱全國 2,053 部法律與 10,452 部行政命令 (任意調閱與連結其他法律)
                    with st.expander(f"🔗 快速連結與直通調閱其他法律或行政命令全文 (支援全台 2,053 部法律與 10,452 部法規命令)", expanded=False):
                        st.caption("可在此直接搜尋並一鍵切換調閱任何相關法律（如：性侵害犯罪防治法、刑法、兒童及少年福利與權益保障法）或行政命令：")
                        col_rel1, col_rel2 = st.columns([3, 1])
                        with col_rel1:
                            all_law_names = sorted(list(law_map.keys()))
                            kw_rel_law = st.text_input("輸入欲聯結之法律名稱關鍵字：", placeholder="例如：性侵害犯罪防治法、個人資料保護法、刑法...", key=f"kw_rel_law_{idx}")
                        with col_rel2:
                            st.write("")
                            st.write("")
                            matched_rel_laws = [l for l in all_law_names if kw_rel_law.strip() and kw_rel_law.strip() in l][:20] if kw_rel_law.strip() else []

                        if matched_rel_laws:
                            sel_rel_law = st.selectbox("選擇欲切換研讀之關聯法律：", matched_rel_laws, key=f"sel_rel_law_{idx}")
                            if st.button(f"🚀 一鍵開啟《{sel_rel_law}》條文全文", key=f"btn_switch_rel_law_{idx}", type="primary"):
                                st.session_state["six_codes_law"] = sel_rel_law
                                for br_name, br_laws in SIX_CODES_TAXONOMY.items():
                                    if sel_rel_law in br_laws:
                                        st.session_state["six_codes_branch"] = br_name
                                        break
                                st.session_state["six_codes_search_kw"] = ""
                                st.session_state["six_codes_kw_rev"] = st.session_state.get("six_codes_kw_rev", 0) + 1
                                st.rerun()

                        # 行政命令部分
                        all_orders_map = get_chorder_regulations_map()
                        kw_custom_reg = st.text_input(f"或輸入行政命令/細則名稱（例如：專利法施行細則、公開發行公司、勞工請假...）：", key=f"kw_custom_reg_{idx}")
                        if kw_custom_reg:
                            matched_regs = [k for k in all_orders_map.keys() if kw_custom_reg in k][:15]
                            if matched_regs:
                                selected_custom_reg = st.selectbox(f"找到相符法規命令：", matched_regs, key=f"sel_custom_reg_{idx}")
                                c_details = get_regulation_full_details(selected_custom_reg)
                                if c_details:
                                    st.success(f"已載入《{c_details['name']}》（主管部會：{c_details['category']}，共 {c_details['total_articles']} 條）")
                                    with st.container(height=300):
                                        for a in c_details["articles"]:
                                            st.markdown(f"**{a['no']}**")
                                            st.markdown(f"> {a['content']}")
                                            st.markdown("---")
                            else:
                                st.warning("未找到相符之法規命令名稱。")

                    st.markdown("---")

                    # 第二區塊：主管機關權威行政函釋庫
                    st.markdown("##### 📜 二、主管機關權威行政函釋庫 (經濟部/智財局/金管會/法務部/衛福部/勞動部)")
                    st.caption("深度整合主管機關具拘束力之行政指導、函令解釋與實務爭點法律見解：")

                    if admin_rulings:
                        for r_item in admin_rulings:
                            agency_badge = r_item.get("agency", "主管機關")
                            doc_no = r_item.get("doc_number", "函釋字號")
                            r_date = r_item.get("date", "")
                            r_title = r_item.get("title", "")
                            r_holding = r_item.get("holding", "")
                            r_analysis = r_item.get("content_analysis", "")
                            r_hint = r_item.get("exam_point_hint", "")

                            st.markdown(f"##### 🏢 【{agency_badge}】`{doc_no}` ｜ 📅 {r_date}")
                            st.markdown(f"**🌟 函釋主旨**：**{r_title}**")
                            st.info(f"**核心要旨（Holding）：**\n{r_holding}")
                            if r_analysis:
                                with st.expander("📖 查看機關詳細行政法理釋析與法令依據", expanded=False):
                                    st.markdown(r_analysis)
                            if r_hint:
                                st.success(f"✍️ **司律國考上位卷作答引述指引：**\n{r_hint}")
                            st.markdown("---")
                    else:
                        st.info(f"目前本地快取中暫無針對【{lname} {ano}】之預載專屬函釋。您可以立即點擊下方按鈕，由 AI 聯網智慧檢索並補強最新函釋！")

                    # 智慧爬取與補強按鈕
                    crawl_key = f"crawl_rulings_{lname}_{ano}"
                    if st.button(f"🔄 智慧檢索/爬取此條文主管機關最新函釋", key=f"btn_crawl_ruling_{idx}"):
                        with st.spinner(f"正在連線中央主管機關資料庫，為【{lname} {ano}】爬取最新行政函釋與解釋令..."):
                            try:
                                crawled = crawl_and_synthesize_admin_rulings(law_name=lname, article_no=ano, content=content)
                                st.session_state[crawl_key] = crawled
                                st.success(f"🎉 成功爬取並新增 {len(crawled)} 筆主管機關權威函釋！已同步永久寫入本地行政函釋資料庫。")
                                st.rerun()
                            except Exception as ce:
                                st.error(f"函釋爬取失敗: {ce}")

                    if crawl_key in st.session_state:
                        c_list = st.session_state[crawl_key]
                        for c in c_list:
                            st.markdown(f"##### 🏢 【{c.get('agency')}】`{c.get('doc_number')}` ｜ 📅 {c.get('date')}")
                            st.markdown(f"**🌟 函釋主旨**：**{c.get('title')}**")
                            st.info(f"**核心要旨：**\n{c.get('holding')}")
                            if c.get("content_analysis"):
                                st.markdown(f"**法理分析：**\n{c.get('content_analysis')}")
                            if c.get("exam_point_hint"):
                                st.success(f"✍️ **作答指引：** {c.get('exam_point_hint')}")

                with tab_legis:
                    st.markdown(f"#### 📜 【{lname} {ano}】立法意旨、歷次修法理由與歷史新舊條文對照庫")
                    st.caption("完整串接立法院法律提案公報、法律覆議與總統修正公布令，呈現原始立法意旨、歷次修正說明與條文新舊文字變革！")

                    intent = legis_data.get("legislative_intent", "")
                    summary_reasons = legis_data.get("summary_reasons", "")

                    if intent:
                        st.success(f"**🎯 原始立法意旨與核心保護法益：**\n\n{intent}")
                    if summary_reasons:
                        st.info(f"**💡 歷次修正總綱與規範演革重心：**\n\n{summary_reasons}")

                    if curated_amends:
                        st.markdown(f"##### 🕰️ 歷次修法理由全文與新舊條文對照表 (收錄 {len(curated_amends)} 次重大修正)")
                        for a_idx, amend in enumerate(curated_amends):
                            with st.expander(f"📅 【{amend.get('date')}】{amend.get('gazette', '')} ｜ 🌟 {amend.get('key_changes', '條文修正')}", expanded=(a_idx == 0)):
                                p_text = amend.get("previous_text", "")
                                c_text = amend.get("current_text", "")
                                if p_text or c_text:
                                    st.markdown("**⚖️ 新舊法條文文字對照：**")
                                    col_old, col_new = st.columns(2)
                                    with col_old:
                                        st.markdown("**🕰️ 修正前歷史條文（舊法）**")
                                        st.caption(p_text if p_text else "（初次制定或舊無此條）")
                                    with col_new:
                                        st.markdown("**📜 修正後施行條文（新法）**")
                                        st.caption(c_text if c_text else content)

                                st.markdown(f"**📜 立法院三讀官方修正理由全文：**\n{amend.get('reason')}")
                                if amend.get("exam_impact"):
                                    st.success(f"✍️ **司律國考新舊法適用要點：**\n{amend.get('exam_impact')}")
                                st.markdown("---")
                    elif not intent and not summary_reasons:
                        st.info(f"💡 目前本地精選庫中暫無針對【{lname} {ano}】之預載深度立法理由。您可以查看下方官方公報沿革，或點擊下方按鈕由 AI 智慧萃取歷次修正理由與新舊條文對照！")

                    if timeline_hits:
                        st.markdown(f"##### 🏛️ 本條於全法沿革中之歷次修正發布令（全國法規資料庫官方紀錄共 {len(timeline_hits)} 次）")
                        with st.container(height=260):
                            for h in timeline_hits:
                                seq_tag = f"第 {h['seq']} 次修正" if h['seq'] > 1 else "制定公布"
                                st.markdown(f"**🏷️ 【{seq_tag}】📅 {h['date']} ｜ {h['decree']} ｜ `{h['action']}`**")
                                st.caption(h['content'])
                                st.markdown("---")

                    # AI 智慧萃取/擴充按鈕
                    leg_ai_key = f"ai_legis_{lname}_{ano}"
                    if st.button(f"✨ 啟動 AI 深度萃取立法理由與歷次新舊條文對照（立法院公報與法規資料庫）", key=f"btn_ai_legis_{idx}"):
                        with st.spinner(f"正在連線 Gemini 3.x Flash 為【{lname} {ano}】萃取立法院三讀修正理由、修法背景與新舊法對照表..."):
                            try:
                                synthesized = synthesize_article_legislative_details(lname, ano, content)
                                st.session_state[leg_ai_key] = synthesized
                                st.success("🎉 成功提煉並更新本條立法理由與新舊法對照表！已同步持久化保存。")
                                st.rerun()
                            except Exception as le_err:
                                st.error(f"立法理由提煉失敗: {le_err}")

                    if leg_ai_key in st.session_state:
                        ai_res = st.session_state[leg_ai_key]
                        if ai_res.get("legislative_intent") and not intent:
                            st.success(f"**🎯 原始立法意旨：**\n{ai_res['legislative_intent']}")
                        if ai_res.get("curated_amendments") and not curated_amends:
                            for a in ai_res["curated_amendments"]:
                                st.markdown(f"**📅 【{a.get('date')}】{a.get('gazette', '')}**")
                                st.info(f"**修正理由：**\n{a.get('reason')}")
                                if a.get("previous_text"):
                                    st.caption(f"**舊條文：**\n{a.get('previous_text')}")
                                if a.get("exam_impact"):
                                    st.success(f"**新舊法適用要點：**\n{a.get('exam_impact')}")

                with tab_materials:
                    st.markdown(f"#### 📘 關聯名師授課講義與個人手寫讀書筆記（共 {len(combined_materials)} 份）")
                    st.caption("已將課輔講義、名師授課體系教材與個人手寫筆記全面整合，並內建 **PDF 即時在線閱讀器**，點擊即可直接於頁面內翻閱閱讀或下載！")

                    if combined_materials:
                        for m_idx, mat in enumerate(combined_materials):
                            m_tag = mat.get("tag", "【講義筆記】")
                            m_fn = mat.get("filename", "")
                            m_reason = mat.get("match_reason", "考科章節關聯")
                            m_path = mat.get("path", "")
                            m_size = mat.get("size_kb", 0)

                            with st.container():
                                st.markdown(f"**📄 `{m_tag}` 《{m_fn}》** (`{m_size}` KB)")
                                st.info(f"🎯 **關聯章節與考點標註**：{m_reason}")

                                # 內嵌 PDF 線上閱讀與下載
                                if m_path and Path(m_path).exists() and m_fn.lower().endswith(".pdf"):
                                    viewer_exp_key = f"exp_pdf_{idx}_{m_idx}"
                                    with st.expander(f"👁️ 點此直接在線展開閱讀 PDF 講義 / 手寫筆記全文（無需跳出）", expanded=False):
                                        try:
                                            with open(m_path, "rb") as f_pdf:
                                                pdf_bytes = f_pdf.read()
                                            b64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
                                            pdf_display = f'<iframe src="data:application/pdf;base64,{b64_pdf}" width="100%" height="600" type="application/pdf" style="border: 1px solid #ddd; border-radius: 8px;"></iframe>'
                                            st.markdown(pdf_display, unsafe_allow_html=True)
                                            st.download_button(
                                                label=f"💾 下載此份 PDF ({m_fn})",
                                                data=pdf_bytes,
                                                file_name=m_fn,
                                                mime="application/pdf",
                                                key=f"dl_pdf_{idx}_{m_idx}"
                                            )
                                        except Exception as pe:
                                            st.warning(f"PDF 讀取提示: {pe}")
                                            if Path(m_path).exists():
                                                with open(m_path, "rb") as fp:
                                                    st.download_button(f"💾 下載《{m_fn}》至本機閱讀", fp, file_name=m_fn, key=f"dl_fb_{idx}_{m_idx}")
                                elif m_path and Path(m_path).exists():
                                    with open(m_path, "rb") as fp:
                                        st.download_button(f"💾 下載《{m_fn}》", fp, file_name=m_fn, key=f"dl_non_pdf_{idx}_{m_idx}")

                                st.markdown("---")
                    else:
                        st.info(f"💡 目前您的資料庫中暫無直接對應【{lname} {ano}】之專屬課輔講義或個人讀書筆記。您可前往【模式 9：手寫筆記蒸餾與 SFT 模型微調大庫】上傳並自動歸納您的專屬讀書筆記！")

                with tab_ai:
                    ai_cache_key = f"ai_anno_{lname}_{ano}"
                    if st.button(f"✨ 啟動 AI 深度釋析（立法理由、主管機關函釋、通說有力說）", key=f"btn_run_anno_{idx}"):
                        with st.spinner(f"正在由 Gemini Flash 為【{lname} {ano}】生成立法沿革、法務部/金管會函釋與二試作答模版..."):
                            try:
                                annotator = SixCodesDeepAnnotator()
                                report = annotator.annotate_article(law_name=lname, article_no=ano, content=content)
                                st.session_state[ai_cache_key] = report
                            except Exception as ee:
                                st.error(f"生成註釋失敗: {ee}")

                    if ai_cache_key in st.session_state:
                        st.markdown(st.session_state[ai_cache_key])

                st.divider()
                act1, act2, act3 = st.columns(3)
                with act1:
                    if st.button(f"📝 帶入試卷評分標準", key=f"btn_pass_eval_{idx}", use_container_width=True):
                        st.session_state["question_text_content"] = f"【依據法規審理】：{lname} {ano}\n\n【條文內容】：\n{content}"
                        st.session_state["rubric_text_content"] = f"【評分指標與法規依據】：\n1. 正確引述 {lname} {ano} 之構成要件與法律效果。\n2. 參酌相關實務見解與立法理由進行涵攝。"
                        st.session_state["imported_from_bank_label"] = f"六法條文【{lname} {ano}】"
                        st.session_state["app_mode"] = "📝 試卷評分與手寫辨識 (手寫/PDF/Word)"
                        st.rerun()
                with act2:
                    if st.button(f"🔍 帶入法學檢索樞紐", key=f"btn_pass_query_{idx}", use_container_width=True):
                        st.session_state["ai_query_input_text"] = f"{lname} {ano} 相關核心爭點與實務裁判"
                        st.session_state["lp_search_query"] = f"{lname} {ano}"
                        st.session_state["lb_input_statute"] = f"{lname}第{ano}條"
                        st.session_state["m5_sub_mode_idx"] = 1
                        st.session_state["app_mode"] = mode_options[4]
                        st.rerun()
                with act3:
                    if st.button(f"📖 針對此法條出題/擬答", key=f"btn_pass_ans_{idx}", use_container_width=True):
                        st.session_state["m4_target_question"] = f"請針對【{lname} {ano}】之構成要件與實務重大爭議，設計一則二試案例題並給予上位卷擬答。\n條文：{content}"
                        st.session_state["app_mode"] = "📖 高分權威擬答生成"
                        st.rerun()

# ----------------- 模式 7: 手寫筆記蒸餾與 SFT 模型微調大庫 -----------------
elif app_mode == MODE_SFT or "手寫筆記蒸餾" in app_mode:
    st.header("📥 個人手寫筆記 OCR 蒸餾與 100 萬筆 SFT 微調庫管線")
    st.write("本系統直接支援將考生個人手寫讀書筆記（PDF、掃描圖、Samsung Notes）透過 Gemini 多模態神經網路進行法學架構辨識，並即時提煉蒸餾為高品質的司律二試 IRAC 實例題解、一試單選題與四維度評分微調語料。")

    sft_tab1, sft_tab2, sft_tab3, sft_tab4 = st.tabs([
        "📤 單份筆記匯入與即時蒸餾",
        "📚 全科文字自動提取與合併單一 PDF",
        "📂 已收錄手寫筆記與 SFT 樣本瀏覽",
        "📊 100 萬筆 SFT 總資料庫與 Colab 微調指南"
    ])

    with sft_tab1:
        st.subheader("1. 匯入個人法學筆記並啟動多模態蒸餾入庫")
        st.write("本系統直接支援將考生個人手寫/打字讀書筆記（PDF、掃描圖、Samsung Notes）透過 Gemini 多模態神經網路進行法學架構辨識，並即時提煉蒸餾為高品質的司律二試 IRAC 實例題解、一試單選題與四維度評分微調語料。")

        distill_mode = st.radio(
            "請選擇匯入方式：",
            ["📂 方案 A：直接自 Google Drive 筆記庫挑選並蒸餾 (免上傳，全庫收錄 550+ 份)", "📤 方案 B：手動上傳新筆記檔案 (PDF/圖片/Word)"],
            horizontal=True,
            key="distill_import_mode"
        )

        if "方案 A" in distill_mode:
            from ingest_user_notes_to_sft import get_google_drive_notes_list, distill_single_note_file, sync_all_drive_notes_to_samsung_notes
            drive_notes = get_google_drive_notes_list()
            if drive_notes:
                sub_counts_dict = {}
                for n in drive_notes:
                    sub_counts_dict[n["subject"]] = sub_counts_dict.get(n["subject"], 0) + 1
                cat_summary = "、".join(f"{s} {c} 份" for s, c in sorted(sub_counts_dict.items(), key=lambda x: -x[1])[:8])
                st.caption(f"⚡ 目前已歸檔 **{len(drive_notes)} 份** 個人筆記（涵蓋 {cat_summary} 等全台法學考科）：")

                CIVIL_GROUP = ["民總", "債總", "債各", "物權", "身分法", "民法", "民法考古題"]
                CRIM_GROUP = ["刑總", "刑分", "刑法考古題"]
                PUB_GROUP = ["憲法", "行政法", "公法考古題"]
                COMM_GROUP = ["商事法", "保險法"]
                IP_GROUP = ["專利法", "商標法", "著作權法", "智慧財產權法"]

                civil_count = sum(1 for n in drive_notes if n["subject"] in CIVIL_GROUP)
                crim_count = sum(1 for n in drive_notes if n["subject"] in CRIM_GROUP)
                pub_count = sum(1 for n in drive_notes if n["subject"] in PUB_GROUP)
                comm_count = sum(1 for n in drive_notes if n["subject"] in COMM_GROUP)
                ip_count = sum(1 for n in drive_notes if n["subject"] in IP_GROUP)

                sft_cat_opts = [
                    f"全部科目 (全庫共 {len(drive_notes)} 份)",
                    f"🌟 【民法全輯】(總則/債編/物權/身分 共 {civil_count} 份)",
                    f"🌟 【刑法全輯】(刑總/刑分 共 {crim_count} 份)",
                    f"🌟 【公法全輯】(憲法/行政法 共 {pub_count} 份)",
                    f"🌟 【商事法全輯】(公司/證交/保險 共 {comm_count} 份)",
                    f"🌟 【智財全輯】(專利/商標/著作權 共 {ip_count} 份)"
                ]
                for s, c in sorted(sub_counts_dict.items(), key=lambda x: -x[1]):
                    sft_cat_opts.append(f"【{s}】(共 {c} 份)")

                col_d1, col_d2 = st.columns([1, 2])
                with col_d1:
                    filter_sub_label = st.selectbox("筆記科目篩選：", sft_cat_opts, key="sft_filter_sub")

                if "全部科目" in filter_sub_label:
                    sub_notes = drive_notes
                    filter_sub = "全部科目"
                elif "民法全輯" in filter_sub_label:
                    sub_notes = [n for n in drive_notes if n["subject"] in CIVIL_GROUP]
                    filter_sub = "民法全輯"
                elif "刑法全輯" in filter_sub_label:
                    sub_notes = [n for n in drive_notes if n["subject"] in CRIM_GROUP]
                    filter_sub = "刑法全輯"
                elif "公法全輯" in filter_sub_label:
                    sub_notes = [n for n in drive_notes if n["subject"] in PUB_GROUP]
                    filter_sub = "公法全輯"
                elif "商事法全輯" in filter_sub_label:
                    sub_notes = [n for n in drive_notes if n["subject"] in COMM_GROUP]
                    filter_sub = "商事法全輯"
                elif "智財全輯" in filter_sub_label:
                    sub_notes = [n for n in drive_notes if n["subject"] in IP_GROUP]
                    filter_sub = "智慧財產權法全輯"
                else:
                    filter_sub = filter_sub_label.split("【")[1].split("】")[0]
                    sub_notes = [n for n in drive_notes if n["subject"] == filter_sub]

                with col_d2:
                    all_distill_label = f"🌟 【全部分析】批次分析並蒸餾此分類全部筆記 (共 {len(sub_notes)} 份)"
                    note_opts = [all_distill_label] + [
                        f"【{n['subject']}】{n['filename']} ({n['size_mb']:.2f} MB)" + (f" 🎯已提煉 {n['distilled_count']} 筆" if n['distilled_count'] > 0 else "")
                        for n in sub_notes
                    ]
                    sel_sft_note = st.selectbox("選擇欲蒸餾之雲端筆記：", note_opts, key="sft_sel_note")

                if sel_sft_note == all_distill_label:
                    st.info(f"💡 已選擇【全部分析】！系統將批次遍歷【{filter_sub}】全部 **{len(sub_notes)} 份** 筆記，透過 Gemini Flash 多模態神經網路執行高精度手寫辨識、爭點提煉與 SFT 微調語料蒸餾，並即時合併寫入 SFT 微調庫。")
                    c_btn_a1, c_btn_a2 = st.columns([2, 1])
                    with c_btn_a1:
                        if st.button(f"🚀 一鍵啟動全部分析：批次多模態 OCR 蒸餾並入庫 (共 {len(sub_notes)} 份)", type="primary", key="btn_distill_all_drive_sft"):
                            prog_bar_dist = st.progress(0.0)
                            status_dist = st.empty()
                            total_new_samples = []
                            success_files = 0
                            failed_files = 0

                            for idx_d, d_note in enumerate(sub_notes, 1):
                                status_dist.text(f"正在蒸餾 [{idx_d}/{len(sub_notes)}]: 《{d_note['filename'][:25]}...》")
                                prog_bar_dist.progress(idx_d / len(sub_notes))
                                try:
                                    cur_samples = distill_single_note_file(d_note["path"], max_pages=15)
                                    if cur_samples:
                                        total_new_samples.extend(cur_samples)
                                        success_files += 1
                                except Exception as e_dist_single:
                                    failed_files += 1

                            prog_bar_dist.progress(1.0)
                            status_dist.text("✅ 全選筆記批次蒸餾完成！")
                            st.balloons()
                            st.success(f"🎉 全部分析蒸餾完成！共處理 {len(sub_notes)} 份筆記（成功 {success_files} 份，失敗 {failed_files} 份），成功提煉出 **{len(total_new_samples)} 組** 高品質 SFT 法學微調樣本！")
                            if total_new_samples:
                                with st.expander("🔍 檢視本次全部分析提煉之 SFT 樣本預覽 (前 10 組)", expanded=True):
                                    for s_idx, s in enumerate(total_new_samples[:10], 1):
                                        st.markdown(f"**【樣本 {s_idx}】ID: `{s.get('id')}`**")
                                        st.caption(f"指令 (Instruction): {s.get('instruction')}")
                                        st.markdown(f"**題目情境 (Input)**：\n{s.get('input')}")
                                        st.markdown(f"**示範解答 (Output)**：\n{s.get('output')}")
                                        st.divider()
                    with c_btn_a2:
                        if st.button("🔄 同步 Google Drive 最新筆記", key="btn_sync_sft_notes"):
                            with st.spinner("正在同步..."):
                                c = sync_all_drive_notes_to_samsung_notes()
                                load_all_drive_notes.clear()
                                st.success(f"同步完成！新增/更新 {c} 份筆記。")
                                st.rerun()
                elif sel_sft_note:
                    sel_note_idx = note_opts.index(sel_sft_note) - 1
                    target_note = sub_notes[sel_note_idx]

                    c_btn_a1, c_btn_a2 = st.columns([2, 1])
                    with c_btn_a1:
                        if st.button("🚀 啟動此份雲端筆記多模態 OCR 蒸餾並寫入 SFT 微調庫", type="primary", key="btn_distill_drive_sft"):
                            with st.spinner(f"⚖️ 正在運用 Gemini Flash 解析《{target_note['filename']}》手寫法條、爭點肯否二說與實務判例..."):
                                try:
                                    new_samples = distill_single_note_file(target_note["path"], max_pages=15)
                                    if new_samples:
                                        st.balloons()
                                        st.success(f"🎉 蒸餾成功！自《{target_note['filename']}》中成功提煉出 **{len(new_samples)} 組** 高品質 SFT 法學微調樣本，並已自動同步合併至主微調大庫！")
                                        with st.expander("🔍 檢視本次提煉之 SFT 樣本預覽", expanded=True):
                                            for s_idx, s in enumerate(new_samples, 1):
                                                st.markdown(f"**【樣本 {s_idx}】ID: `{s.get('id')}`**")
                                                st.caption(f"指令 (Instruction): {s.get('instruction')}")
                                                st.markdown(f"**題目情境 (Input)**：\n{s.get('input')}")
                                                st.markdown(f"**示範解答 (Output)**：\n{s.get('output')}")
                                                st.divider()
                                    else:
                                        st.warning("未能從此檔案中辨識出足夠的法學爭點，請確認檔案內容或稍後重試。")
                                except Exception as de:
                                    st.error(f"蒸餾處理失敗: {de}")
                    with c_btn_a2:
                        if st.button("🔄 同步 Google Drive 最新筆記", key="btn_sync_sft_notes_single"):
                            with st.spinner("正在同步..."):
                                c = sync_all_drive_notes_to_samsung_notes()
                                load_all_drive_notes.clear()
                                st.success(f"同步完成！新增/更新 {c} 份筆記。")
                                st.rerun()
            else:
                st.info("💡 目前 Google Drive 尚無筆記檔案。")
                if st.button("🔄 一鍵自 Google Drive「資源」目錄同步所有法學筆記"):
                    with st.spinner("正在同步..."):
                        c = sync_all_drive_notes_to_samsung_notes()
                        load_all_drive_notes.clear()
                        st.success(f"同步完成！共匯入 {c} 份筆記檔案。")
                        st.rerun()

        else:
            up_file = st.file_uploader(
                "選擇手寫/打字筆記檔案（支援 PDF, PNG, JPG, WEBP, Word docx）：",
                type=["pdf", "png", "jpg", "jpeg", "webp", "docx"],
                key="sft_note_uploader"
            )

            if up_file is not None:
                st.info(f"📄 已選擇檔案：`{up_file.name}` ({len(up_file.getvalue()) / (1024*1024):.2f} MB)")
                if st.button("🚀 啟動多模態 OCR 辨識並蒸餾寫入 SFT 微調庫", type="primary", key="btn_distill_sft"):
                    with st.spinner("⚖️ 正在運用 Gemini Flash 解析手寫法條、爭點肯否二說與實務判例，並轉化為標準 SFT 資料..."):
                        try:
                            # 1. 建立獨立檔案永久典藏至社群筆記庫，並實時連動注入六法註記大典
                            arch_res = archive_uploaded_note(
                                file_bytes=up_file.getvalue(),
                                filename=up_file.name,
                                subject="法學筆記",
                                summary=f"考生上傳之《{up_file.name}》"
                            )

                            from ingest_user_notes_to_sft import ingest_single_uploaded_file
                            new_samples = ingest_single_uploaded_file(up_file.getvalue(), up_file.name)
                            if new_samples:
                                st.balloons()
                                st.success(f"🎉 蒸餾成功！自《{up_file.name}》中成功提煉出 **{len(new_samples)} 組** 高品質 SFT 法學微調樣本，並已自動新建獨立檔案 `{arch_res.get('archive_filename', up_file.name)}` 永久典藏至社群筆記庫與六法大典！")
                                with st.expander("🔍 檢視本次提煉之 SFT 樣本預覽", expanded=True):
                                    for s_idx, s in enumerate(new_samples, 1):
                                        st.markdown(f"**【樣本 {s_idx}】ID: `{s.get('id')}`**")
                                        st.caption(f"指令 (Instruction): {s.get('instruction')}")
                                        st.markdown(f"**題目情境 (Input)**：\n{s.get('input')}")
                                        st.markdown(f"**示範解答 (Output)**：\n{s.get('output')}")
                                        st.divider()
                            else:
                                st.warning("未能從此檔案中辨識出足夠的法學爭點，請確認檔案清晰度或是否包含法律筆記內容。但該檔案已成功新建獨立檔案典藏至社群庫！")
                        except Exception as de:
                            st.error(f"蒸餾處理失敗: {de}")

            # 社群考生共享講義與讀書筆記寶庫
            st.divider()
            comm_notes_all = load_community_notes()
            st.markdown(f"#### 👥 全民共享講義筆記寶庫（已永久典藏 {len(comm_notes_all)} 份社群筆記）")
            st.caption("所有考生手動上傳之手寫/PDF筆記均新建獨立檔案永久保存，供後人研讀並實時注入六法條文註記：")
            if comm_notes_all:
                for c_note in comm_notes_all:
                    c_n_title = c_note.get("filename", "法學筆記")
                    c_n_sub = c_note.get("subject", "法學")
                    c_n_uploader = c_note.get("uploader", "社群考生")
                    c_n_time = c_note.get("uploaded_at", "")
                    c_n_path = c_note.get("file_path", "")
                    c_n_size = c_note.get("size_kb", 0)

                    with st.expander(f"📄 【{c_n_sub}】《{c_n_title}》 ｜ 👤 {c_n_uploader} ｜ 📅 {c_n_time} ({c_n_size} KB)"):
                        st.caption(f"檔案路徑：`{c_note.get('relative_path')}`")
                        if c_n_path and Path(c_n_path).exists():
                            try:
                                with open(c_n_path, "rb") as bf:
                                    st.download_button(
                                        label=f"💾 下載此份筆記檔案 ({c_n_size} KB)",
                                        data=bf.read(),
                                        file_name=c_n_title,
                                        key=f"dl_cn_{c_note.get('note_id')}"
                                    )
                            except Exception:
                                pass
            else:
                st.info("💡 目前社群筆記寶庫中暫無外部上傳檔案。您在此上傳的任何講義或手寫筆記，系統都將建立獨立檔案典藏入庫！")

    with sft_tab2:
        st.subheader("📚 全考科整合：依體系合併為單一完整 PDF 與全科文字自動提取")
        st.write("直接將一整個法學考科（如身分法 27 份、民總 21 份、刑分 16 份、商事法 20 份、保險法 17 份等）所有零散筆記依據法學章節體系邏輯順序，拼接合併為【單一完整 PDF】方便平日研讀，或啟動【全科文字自動提取】彙編為 Markdown 大典並直接批次入庫！")

        from ingest_user_notes_to_sft import (
            get_google_drive_notes_list, merge_subject_pdfs, extract_subject_text_corpus, get_chapter_sort_key
        )

        all_notes = get_google_drive_notes_list()
        sub_dict = {}
        for n in all_notes:
            if "全科整合" not in n["filename"] and "全科體系" not in n["filename"] and not n["filename"].endswith("_全科筆記文字總彙編.md"):
                sub_dict.setdefault(n["subject"], []).append(n)

        if sub_dict:
            all_sub_count = sum(len(nlist) for nlist in sub_dict.values())
            CIVIL_GROUP = ["民總", "債總", "債各", "物權", "身分法", "民法"]
            civil_notes = [n for n in all_notes if n["subject"] in CIVIL_GROUP]

            all_choice_label = f"🌟 【全部考科】全部分析 (全庫共 {all_sub_count} 份筆記 / 講義)"
            civil_choice_label = f"🌟 【民法全輯】(總則/債總/債各/物權/身分 共 {len(civil_notes)} 份)"

            sub_options = [all_choice_label, civil_choice_label] + [
                f"【{s}】(共 {len(nlist)} 份筆記 / 講義)"
                for s, nlist in sorted(sub_dict.items(), key=lambda x: -len(x[1]))
            ]
            sel_sub_label = st.selectbox("請選擇欲處理的法學考科：", sub_options, key="merge_sub_select")
            if sel_sub_label == all_choice_label:
                sel_subject = "全部考科"
                sub_notes = [n for nlist in sub_dict.values() for n in nlist]
            elif sel_sub_label == civil_choice_label:
                sel_subject = "民法全輯"
                sub_notes = civil_notes
            else:
                sel_subject = sel_sub_label.split("【")[1].split("】")[0]
                sub_notes = sub_dict[sel_subject]

            with st.expander(f"📋 展開檢視【{sel_subject}】所收錄的 {len(sub_notes)} 份章節檔案清單（已依體系順序排列）", expanded=False):
                sorted_sub_notes = sorted(sub_notes, key=lambda x: (x.get("subject", ""), get_chapter_sort_key(x["path"])))
                for s_idx, sn in enumerate(sorted_sub_notes, 1):
                    badge = "⚡ 已快取" if sn["is_cached"] else "📄 待提取"
                    dist_badge = f" ｜ 🎯 已提煉 {sn['distilled_count']} 組 SFT" if sn["distilled_count"] > 0 else ""
                    st.write(f"{s_idx}. **《{sn['filename']}》** (`{sn['size_mb']:.2f} MB`) ｜ {badge}{dist_badge}")

            st.divider()

            c_op1, c_op2 = st.columns(2)

            with c_op1:
                st.markdown(f"### 📑 方案一：合併為《{sel_subject}》單一完整 PDF")
                st.caption(f"自動依據章節法理順序（如親屬總論 -> 婚約 -> 婚姻...至扣減權）高速拼接本考科所有 {len(sub_notes)} 份 PDF，生成一個完整可離線劃記閱讀的超大 PDF。")
                if st.button(f"🚀 開始合併【{sel_subject}】全科為單一 PDF", type="primary", key="btn_run_merge_pdf"):
                    with st.spinner(f"正在使用高精度 C++ 引擎依章節順序拼接【{sel_subject}】各章頁面..."):
                        try:
                            merge_res = merge_subject_pdfs(sel_subject)
                            st.session_state[f"merged_pdf_{sel_subject}"] = merge_res
                            st.balloons()
                            st.success(f"🎉 合併成功！已生成《{merge_res['output_path'].name}》")
                        except Exception as me:
                            st.error(f"合併失敗: {me}")

                if f"merged_pdf_{sel_subject}" in st.session_state:
                    m_info = st.session_state[f"merged_pdf_{sel_subject}"]
                    st.info(f"📄 總頁數：**{m_info['total_pages']} 頁** ｜ 檔案大小：**{m_info['file_size_mb']:.2f} MB**")
                    if m_info["output_path"].exists():
                        with open(m_info["output_path"], "rb") as f_pdf:
                            st.download_button(
                                label=f"⬇️ 立即下載【{sel_subject}】全科整合手寫體系總筆記 PDF",
                                data=f_pdf.read(),
                                file_name=m_info["output_path"].name,
                                mime="application/pdf",
                                key="btn_dl_merged_pdf"
                            )

            with c_op2:
                st.markdown(f"### ⚡ 方案二：全科自動文字提取與 OCR 彙編")
                st.caption(f"自動遍歷【{sel_subject}】所有 {len(sub_notes)} 份檔案，優先調用高速快取與數位字；若為手寫筆記掃描檔則由 Gemini Flash 辨識並彙整為單一 Markdown 筆記大典。")
                ocr_flag = st.checkbox("自動對手寫掃描檔啟用 Gemini Flash 多模態 OCR", value=True, key="chk_auto_ocr_full")

                if st.button(f"⚡ 開始全自動文字提取【{sel_subject}】全科筆記", type="primary", key="btn_run_extract_corpus"):
                    prog_bar = st.progress(0.0)
                    status_text = st.empty()

                    def ui_progress(cur, total, fname):
                        prog_bar.progress(cur / total)
                        status_text.text(f"正在提取 [{cur}/{total}]: 《{fname[:25]}...》")

                    with st.spinner(f"正在遍歷與提取【{sel_subject}】全考科文字..."):
                        try:
                            corpus_res = extract_subject_text_corpus(
                                sel_subject,
                                auto_ocr=ocr_flag,
                                progress_callback=ui_progress
                            )
                            st.session_state[f"corpus_{sel_subject}"] = corpus_res
                            prog_bar.progress(1.0)
                            status_text.text("全科文字提取完成！")
                            st.balloons()
                            st.success(f"🎉 提取成功！全科彙整共提取 **{corpus_res['total_chars']:,} 字元**（共 {corpus_res['total_notes']} 份檔案）。")
                        except Exception as ce:
                            st.error(f"文字提取失敗: {ce}")

                if f"corpus_{sel_subject}" in st.session_state:
                    c_info = st.session_state[f"corpus_{sel_subject}"]
                    st.info(f"📝 總文字量：**{c_info['total_chars']:,} 字元** ｜ 收錄章節：**{c_info['total_notes']} 章**")
                    st.download_button(
                        label=f"⬇️ 立即下載【{sel_subject}】全科筆記文字總彙編 Markdown",
                        data=c_info["full_text"].encode("utf-8"),
                        file_name=f"{sel_subject}_全科筆記文字總彙編.md",
                        mime="text/markdown",
                        key="btn_dl_corpus_md"
                    )
                    with st.expander(f"🔍 檢視【{sel_subject}】全科文字彙總預覽 (前 2,000 字)", expanded=False):
                        st.markdown(c_info["full_text"][:2000] + "\n\n*(篇幅過長，已截斷預覽，完整全文請點擊上方按鈕下載)*")
        else:
            st.info("目前尚未偵測到任何法學筆記檔案。")

    with sft_tab3:
        from ingest_user_notes_to_sft import get_google_drive_notes_list
        all_dn = get_google_drive_notes_list()
        st.subheader(f"📂 SamsungNotes 已永久歸檔之個人法學筆記 ({len(all_dn)} 份)")
        if all_dn:
            st.caption(f"目前已於雲端硬碟永久歸檔 **{len(all_dn)} 份** 手寫與打字法學筆記：")
            sub_dict = {}
            for n in all_dn:
                sub_dict.setdefault(n["subject"], []).append(n)

            for s_name, n_list in sub_dict.items():
                with st.expander(f"📁 【{s_name}】共 {len(n_list)} 份筆記檔案", expanded=False):
                    for nf in n_list:
                        status_str = " | ⚡ 已快取" if nf["is_cached"] else ""
                        dist_str = f" | 🎯 已提煉 {nf['distilled_count']} 組 SFT" if nf["distilled_count"] > 0 else ""
                        st.write(f"- 📄 **《{nf['filename']}》** ｜ 大小：`{nf['size_mb']:.2f} MB`{status_str}{dist_str}")
        else:
            st.info("目前尚未有手寫筆記檔案。")

        st.divider()
        st.subheader("📝 目前個人筆記 SFT 庫提煉精華 (law_exam_user_notes_sft.jsonl)")
        user_sft_file = Path(DATA_DIR) / "training_data" / "law_exam_user_notes_sft.jsonl"
        if user_sft_file.exists():
            try:
                user_samples = []
                with open(user_sft_file, "r", encoding="utf-8") as f_us:
                    for line in f_us:
                        l = line.strip()
                        if l:
                            user_samples.append(json.loads(l))
                st.caption(f"已提煉 **{len(user_samples)} 組** 手寫筆記專屬微調題解：")
                for u_idx, us in enumerate(user_samples[:10], 1):
                    with st.expander(f"📌 【筆記題解 {u_idx}】{us.get('input', '')[:40]}..."):
                        st.caption(f"**指令**：{us.get('instruction')}")
                        st.write(f"**題目**：\n{us.get('input')}")
                        st.info(f"**解答**：\n{us.get('output')}")
            except Exception as ue:
                st.error(f"讀取筆記微調資料失敗: {ue}")
        else:
            st.info("目前尚未生成個人筆記 SFT 檔案。")

    with sft_tab4:
        st.subheader("📊 SFT 微調資料庫總覽與規格")

        ver_file = Path(DATA_DIR) / "training_data" / "law_exam_verified_sft.jsonl"
        mas_file = Path(DATA_DIR) / "training_data" / "law_exam_master_sft_unified.jsonl"
        bal_file = Path(DATA_DIR) / "training_data" / "law_exam_balanced_weighted_sft.jsonl"

        c1, c2, c3 = st.columns(3)
        c1.metric("純核實核心庫 (100% 真跡)", f"{5082:,} 筆" if ver_file.exists() else "建構中")
        c2.metric("混合加權平衡庫 (推薦)", f"{118650:,} 筆" if bal_file.exists() else "建構中")
        c3.metric("全量百萬統一大庫", f"{1005082:,} 筆" if mas_file.exists() else "建構中")

        st.markdown("""
        #### 🛡️ Hugging Face Arrow 綱要相容保證：
        每一筆 SFT 樣本均嚴格標準化為 5 大核心欄位，徹底杜絕訓練資料載入與分詞之型別異常：
        - `id`: 樣本唯一識別碼
        - `source_type`: 資料來源識別（手寫筆記 / 真實判決 / 憲法法庭 / 名師講義 / 模擬題庫 / 合成推理底模）
        - `instruction`: 任務系統指令（IRAC 申論、一試單選、評分診斷）
        - `input`: 案例情境或題目題幹
        - `output`: 上位卷完整解答或標準試題解析

        #### ⚖️ 資料庫組成比例與實證透明度 (Synthesis Ratio Disclosure)：
        - **純核實核心庫 (5,082 筆)**：100% 取自真實實質裁判、憲法法庭判決、歷年司律真題及考生個人手寫筆記，無合成樣本。
        - **混合加權平衡庫 (118,650 筆)**：
          - **78,650 筆 (66.3%)**：真實高價值核心資料科學過採樣（手寫筆記 500x、真題 50x、名師學說 20x、裁判憲法 10x）。
          - **40,000 筆 (33.7%)**：司法論證結構模板 (`synthesized_judicial_reasoning`)，作為三段論法語法底模以避免顯存過擬合。
        - **全量百萬統一大庫 (1,005,082 筆)**：5,082 筆核實真跡 (0.5%) + 1,000,000 筆司法推理語法模板基準庫 (99.5%)。非百萬篇真實判決，使用者應依 `source_type` 欄位區隔真實裁判（`verified_*`）與模板（`synthetic_*`）。
        - **標籤語意說明**：`source_type` 欄位以 `verified_` 前綴標記，係指資料來自非合成之真實政府裁判或考題採集管道（相對於模板生成資料），非代表每筆法學論述經由國家考試閱卷委員逐字人工法學公證。

        #### 🔄 兩種「續訓」技術模式之嚴謹區別：
        1. **同環境 Checkpoint 斷點續訓 (In-Session Resumption)**：
           - 透過 `RESUME_FROM_CHECKPOINT=True`；
           - **完整恢復**：模型權重 + AdamW 優化器狀態矩陣 + 學習率排程步數 + 亂數種子，無損接續前次中斷點。
        2. **跨 Session LoRA 熱啟動微調 (Cross-Session Continual Warm Start)**：
           - 透過 `EXISTING_LORA_PATH` 指定已導出之 LoRA 目錄或 Zip 檔；
           - **僅繼承權重**：優化器與學習率會重新初始化，展開第二階段增量遷移微調。

        #### 📜 資料性質與著作權遵循界限 (Legal & Copyright Boundaries)：
        - **公開公務資訊 (公共領域)**：實務裁判書、憲法裁判、公報、法規命令及考選部公務真題，依《著作權法》第 9 條第 1 項規定依法不得為著作權之標的，屬開放公務資訊。
        - **私人研析與學術文獻**：個人手寫筆記為考生著作，名師講義學說為著作人版權；依《著作權法》第 52 條及第 65 條，合理使用（Fair Use）之成立須視具體利用之目的、性質、所利用之質與量及其對潛在市場之影響個案審酌，本專案聲明僅為內部工程用途與限制提示，非授權判定，亦不具法律豁免效力；未獲權利人授權嚴禁將受保護教材進行公開傳輸、發布或商業營利。
        - **用途與免責聲明**：本資料集與微調模型純屬內部學術研究與個人自律解題訓練，使用者應自負資料來源之合法性責任；模型產生之推論亦不得取代合格律師之正式法律諮詢。

        #### 🚀 Google Colab / Kaggle 雲端微調執行指南：
        1. **Colab 訓練**：開啟專案目錄下 `train_colab.ipynb`，直接掛載 Google Drive 讀取資料集；
        2. **Kaggle 訓練**：開啟 `train_kaggle.ipynb`，支援自訂/官方平衡庫（具備全檔串流校驗與 SHA-256 審計）或推薦使用 Private Dataset 本地掛載；
        3. **顯卡規格**：Unsloth 4-bit 顯存優化核心限定使用 NVIDIA GPU（T4 / V100 / A100 / L4），不支援 TPU。
        """)
