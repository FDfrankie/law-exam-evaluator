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
import json
from pathlib import Path
from PIL import Image

from config import init_directories, GOOGLE_DRIVE_DATA_DIR, get_gemini_api_key, RAW_DATA_DIR, DATA_DIR, DEFAULT_GEMINI_MODEL, GEMINI_FALLBACK_MODELS
from doc_parser import parse_document, ocr_handwritten_images
from evaluator import LawExamEvaluator
from exam_generator import LawExamGenerator
try:
    from legal_query_engine import (
        LegalIssueQueryEngine,
        search_local_precedents,
        get_all_precedent_options,
        get_precedent_by_id,
        get_precedents_catalog,
        generate_judicial_search_urls,
        search_precedents_lawbank_style,
        LAWBANK_COMMON_CASE_WORDS,
        LAWBANK_COURTS_TAXONOMY,
        LAWSNOTE_TIME_RANGES,
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
        search_precedents_lawbank_style = getattr(_lqe, "search_precedents_lawbank_style", lambda **kw: [])
        LAWBANK_COMMON_CASE_WORDS = getattr(_lqe, "LAWBANK_COMMON_CASE_WORDS", ["全部字別 (不限)", "台上大", "台上", "憲判"])
        LAWBANK_COURTS_TAXONOMY = getattr(_lqe, "LAWBANK_COURTS_TAXONOMY", {"全部法院 (全體司法體系)": []})
        LAWSNOTE_TIME_RANGES = getattr(_lqe, "LAWSNOTE_TIME_RANGES", ["全部時間 (不限年份)"])
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
        search_precedents_lawbank_style = lambda **kw: []
        LAWBANK_COMMON_CASE_WORDS = ["全部字別 (不限)", "台上大", "台上", "憲判"]
        LAWBANK_COURTS_TAXONOMY = {"全部法院 (全體司法體系)": []}
        LAWSNOTE_TIME_RANGES = ["全部時間 (不限年份)"]
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
    from lawbank_engine import (
        BooleanQueryParser,
        evaluate_boolean_query,
        IndictmentJudgmentComparator,
        BUILTIN_INDICTMENT_CASES,
        AILegalSummarizer,
        BUILTIN_LANDMARK_DOCS
    )
except ImportError:
    try:
        import lawbank_engine as _lbe
        BooleanQueryParser = getattr(_lbe, "BooleanQueryParser", None)
        evaluate_boolean_query = getattr(_lbe, "evaluate_boolean_query", lambda q, t: True)
        IndictmentJudgmentComparator = getattr(_lbe, "IndictmentJudgmentComparator", None)
        BUILTIN_INDICTMENT_CASES = getattr(_lbe, "BUILTIN_INDICTMENT_CASES", [])
        AILegalSummarizer = getattr(_lbe, "AILegalSummarizer", None)
        BUILTIN_LANDMARK_DOCS = getattr(_lbe, "BUILTIN_LANDMARK_DOCS", [])
    except Exception:
        class BooleanQueryParser:
            @classmethod
            def is_boolean_query(cls, q): return False
        def evaluate_boolean_query(q, t): return True
        IndictmentJudgmentComparator = None
        BUILTIN_INDICTMENT_CASES = []
        AILegalSummarizer = None
        BUILTIN_LANDMARK_DOCS = []

# 設定頁面配置
st.set_page_config(
    page_title="司律考試 AI 評分與命題大師",
    page_icon="⚖️",
    layout="wide"
)

init_directories()


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
        "📝 試卷評分與手寫辨識 (手寫/PDF/Word)",
        "🎯 司律模擬出題 (一試/二試 & 手寫筆記客製命題)",
        "📚 歷年真題庫檢索與模擬演練 (法研所 / 轉學考 / 司法官律師 / 司法特考)",
        "📖 高分權威擬答生成",
        "🔍 統一法學檢索樞紐與 AI 判決研析 (布林檢索・多庫矩陣・爭點大典)",
        "📑 一鍵 AI 裁判與長篇函釋要旨自動精鍊 (法源 AI 摘要旗艦)",
        "⚖️ 智慧六法與條文判解綜合標註 (法條・沿革・爭點・筆記)",
        "📥 手寫筆記蒸餾與 SFT 模型微調大庫"
    ]
    if "app_mode" not in st.session_state:
        st.session_state["app_mode"] = mode_options[0]
    else:
        old_val = st.session_state["app_mode"]
        if "爭點查詢" in old_val or "統一法學檢索" in old_val:
            st.session_state["app_mode"] = mode_options[4]
        elif "AI 裁判" in old_val or "AI 摘要" in old_val or "AI裁判" in old_val or "起訴書" in old_val:
            st.session_state["app_mode"] = mode_options[5]
        elif "智慧六法" in old_val:
            st.session_state["app_mode"] = mode_options[6]
        elif "手寫筆記蒸餾" in old_val:
            st.session_state["app_mode"] = mode_options[7]
        elif old_val not in mode_options:
            st.session_state["app_mode"] = mode_options[0]

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

# ----------------- 模式 1: 試卷評分 -----------------
if app_mode == "📝 試卷評分與手寫辨識 (手寫/PDF/Word)":
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
            ["✍️ 手動輸入題目文字", "📷 拍照 / 圖片上傳試題 (AI 自動 OCR)", "👥 從社群考生共享題庫挑選題目"],
            horizontal=True
        )

        new_extracted_q = None
        if q_input_mode == "👥 從社群考生共享題庫挑選題目":
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
elif app_mode == "🎯 司律模擬出題 (一試/二試 & 手寫筆記客製命題)":
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
        st.markdown("##### 🎯 第二步：設定核心考點爭點（支援分類快選）")
        available_topics_map = get_subject_topics_taxonomy(subject)
        topic_options = ["-- 請選擇司律高頻考點爭點（點選自動帶入） --"] + list(available_topics_map.keys())
        sel_preset_topic = st.selectbox(
            f"依【{subject}】分類快選高頻考點：",
            topic_options,
            key=f"sel_topic_preset_{subject}"
        )

        default_topic_text = ""
        if sel_preset_topic and sel_preset_topic != "-- 請選擇司律高頻考點爭點（點選自動帶入） --":
            default_topic_text = available_topics_map[sel_preset_topic]

        topic = st.text_input(
            "出題核心主題/考點（若有上傳筆記亦可留空或輸入重點關鍵字）：",
            value=default_topic_text,
            placeholder="例如：借名登記、侵權純經濟損失、原因自由行為...",
            key=f"exam_topic_input_{subject}"
        )
        if default_topic_text:
            st.caption(f"💡 已自動選定高頻爭點：`{default_topic_text}`（您可直接修改或補充自訂關鍵字）")


    st.markdown("#### 📚 放入我的個人筆記 / 爭點講義（支援手寫 PDF 與圖片）")

    # 預先讀取雲端筆記清單，確保標籤與計數精確
    try:
        from ingest_user_notes_to_sft import get_google_drive_notes_list, read_note_text, sync_all_drive_notes_to_samsung_notes
        drive_notes = get_google_drive_notes_list()
    except Exception:
        drive_notes = []

    drive_tab_label = f"📂 從 Google Drive 個人筆記庫挑選 (免上傳，全庫收錄 {len(drive_notes)} 份筆記)" if drive_notes else "📂 從 Google Drive 個人筆記庫挑選 (免上傳)"

    note_tab_drive, note_tab_upload, note_tab_text, note_tab_cw = st.tabs([
        drive_tab_label,
        "📄 手動上傳新筆記 (支援 PDF/Word/TXT/圖片)",
        "✍️ 直接貼上/編輯筆記文字",
        "🎓 從名師課輔講義庫挑選 (115+ 份講義與題解)"
    ])

    notes_from_drive = ""
    with note_tab_drive:
        try:
            if drive_notes:
                st.caption(f"⚡ 已自您的 Google Drive「資源」與筆記庫自動偵測並收錄 **{len(drive_notes)} 份** 個人手寫與打字法學筆記（免下載免上傳，點選即讀！）：")

                # 科目分類群組與統計
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

                sub_counts = {}
                for n in drive_notes:
                    sub_counts[n["subject"]] = sub_counts.get(n["subject"], 0) + 1

                cat_options = [
                    f"全部科目 (全庫共 {len(drive_notes)} 份)",
                    f"🌟 【民法全輯】(總則/債編/物權/身分 共 {civil_count} 份)",
                    f"🌟 【刑法全輯】(刑總/刑分 共 {crim_count} 份)",
                    f"🌟 【公法全輯】(憲法/行政法 共 {pub_count} 份)",
                    f"🌟 【商事法全輯】(公司/證交/保險 共 {comm_count} 份)",
                    f"🌟 【智財全輯】(專利/商標/著作權 共 {ip_count} 份)"
                ]
                for s, c in sorted(sub_counts.items(), key=lambda x: -x[1]):
                    cat_options.append(f"【{s}】(共 {c} 份)")

                # 智能預設選中匹配當前考科
                default_cat_idx = 0
                if subject:
                    if any(k in subject for k in ["民法", "債", "物權", "身分", "總則"]):
                        default_cat_idx = 1
                    elif any(k in subject for k in ["刑法", "刑總", "刑分"]):
                        default_cat_idx = 2
                    elif any(k in subject for k in ["公法", "憲法", "行政"]):
                        default_cat_idx = 3
                    elif any(k in subject for k in ["商事", "公司", "保險", "證交"]):
                        default_cat_idx = 4
                    elif any(k in subject for k in ["智財", "智慧財產", "專利", "商標", "著作"]):
                        default_cat_idx = 5

                col_sel1, col_sel2 = st.columns([1, 2])
                with col_sel1:
                    sel_note_category = st.selectbox(
                        "筆記分類篩選：",
                        cat_options,
                        index=default_cat_idx,
                        key="sel_note_subject_filter"
                    )

                # 依分類篩選筆記
                if "全部科目" in sel_note_category:
                    filtered_notes = drive_notes
                    cat_display = "全部科目"
                elif "民法全輯" in sel_note_category:
                    filtered_notes = [n for n in drive_notes if n["subject"] in CIVIL_GROUP]
                    cat_display = "民法全輯（總則/債編/物權/身分）"
                elif "刑法全輯" in sel_note_category:
                    filtered_notes = [n for n in drive_notes if n["subject"] in CRIM_GROUP]
                    cat_display = "刑法全輯（刑總/刑分）"
                elif "公法全輯" in sel_note_category:
                    filtered_notes = [n for n in drive_notes if n["subject"] in PUB_GROUP]
                    cat_display = "公法全輯（憲法/行政法）"
                elif "商事法全輯" in sel_note_category:
                    filtered_notes = [n for n in drive_notes if n["subject"] in COMM_GROUP]
                    cat_display = "商事法全輯"
                elif "智財全輯" in sel_note_category:
                    filtered_notes = [n for n in drive_notes if n["subject"] in IP_GROUP]
                    cat_display = "智慧財產權法全輯"
                else:
                    target_sub = sel_note_category.split("【")[1].split("】")[0]
                    filtered_notes = [n for n in drive_notes if n["subject"] == target_sub]
                    cat_display = target_sub

                with col_sel2:
                    all_notes_label = f"🌟 【全部分析】載入此分類全部筆記 (共 {len(filtered_notes)} 份，自動文字提取/OCR 彙整)"
                    note_labels = [all_notes_label] + [
                        f"【{n['subject']}】{n['filename']} ({n['size_mb']:.2f} MB)" + (" ⚡已快取" if n['is_cached'] else "")
                        for n in filtered_notes
                    ]
                    sel_note_label = st.selectbox(
                        "選擇 Google Drive 筆記檔案：",
                        note_labels,
                        key="sel_drive_note_file"
                    )

                if sel_note_label == all_notes_label:
                    st.info(f"💡 已選擇【全部分析】！系統將遍歷【{cat_display}】全部 **{len(filtered_notes)} 份** 雲端筆記，優先調用高速數位文字與本機快取；手寫或掃描 PDF 自動調用 Gemini Flash 進行多模態辨識，彙編成完整法學爭點大典以供客製命題。")
                    c_btn1, c_btn2 = st.columns([2, 1])
                    with c_btn1:
                        load_all_btn = st.button(f"🚀 一鍵分析並載入全部筆記 (共 {len(filtered_notes)} 份)", type="primary", key="btn_load_all_drive_notes")
                    with c_btn2:
                        sync_btn = st.button("🔄 同步 Google Drive 最新筆記", key="btn_sync_drive_notes")
                        if sync_btn:
                            with st.spinner("正在掃描雲端硬碟各科筆記..."):
                                c = sync_all_drive_notes_to_samsung_notes()
                                st.success(f"同步完成！已收錄 {c} 份筆記檔案。")
                                st.rerun()

                    session_all_key = f"cached_all_notes_text_{cat_display}_{len(filtered_notes)}"
                    if load_all_btn or (session_all_key in st.session_state):
                        if load_all_btn:
                            prog_bar = st.progress(0.0)
                            status_txt = st.empty()
                            all_texts = []
                            for idx_n, n_item in enumerate(filtered_notes, 1):
                                status_txt.text(f"正在分析筆記 [{idx_n}/{len(filtered_notes)}]: 《{n_item['filename'][:25]}...》")
                                prog_bar.progress(idx_n / len(filtered_notes))
                                try:
                                    t_part = read_note_text(n_item["path"], max_pages=15, auto_ocr=True)
                                    if t_part and not t_part.startswith("["):
                                        all_texts.append(f"### 《{n_item['filename']}》（科目：{n_item['subject']}）\n{t_part}")
                                except Exception as n_err:
                                    pass
                            combined_all = "\n\n---\n\n".join(all_texts)
                            st.session_state[session_all_key] = combined_all
                            prog_bar.progress(1.0)
                            status_txt.text("✅ 全部分析與文字提取完成！")
                            st.balloons()

                        combined_all = st.session_state.get(session_all_key, "")
                        if combined_all:
                            notes_from_drive = combined_all
                            st.success(f"🎉 成功全部分析【{cat_display}】共 {len(filtered_notes)} 份筆記，累計取得 {len(combined_all):,} 字元！已自動帶入下方命題引擎。")
                            with st.expander("🔍 檢視已解析之全部分類筆記重點與爭點摘要", expanded=False):
                                st.text_area("全部分析筆記內容彙整（已用於客製命題）：", value=combined_all, height=220, key="preview_drive_all_notes")
                elif sel_note_label:
                    sel_idx = note_labels.index(sel_note_label) - 1
                    chosen_note = filtered_notes[sel_idx]

                    c_btn1, c_btn2 = st.columns([2, 1])
                    with c_btn1:
                        load_btn = st.button("🚀 載入此份雲端筆記 (自動進行文字提取 / 手寫多模態 OCR)", type="primary", key="btn_load_drive_note")
                    with c_btn2:
                        sync_btn_single = st.button("🔄 同步 Google Drive 最新筆記", key="btn_sync_drive_notes_single")
                        if sync_btn_single:
                            with st.spinner("正在掃描雲端硬碟各科筆記..."):
                                c = sync_all_drive_notes_to_samsung_notes()
                                st.success(f"同步完成！已收錄 {c} 份筆記檔案。")
                                st.rerun()

                    session_key = f"cached_note_text_{chosen_note['filename']}"
                    if load_btn or (session_key in st.session_state):
                        if load_btn:
                            with st.spinner(f"正在讀取《{chosen_note['filename']}》；手寫或掃描檔案自動調用 Gemini 多模態神經網路辨識..."):
                                text_content = read_note_text(chosen_note["path"], max_pages=15, auto_ocr=True)
                                st.session_state[session_key] = text_content

                        text_content = st.session_state.get(session_key, "")
                        if text_content and not text_content.startswith("["):
                            notes_from_drive = text_content
                            st.success(f"🎉 成功讀取筆記《{chosen_note['filename']}》，共取得 {len(text_content):,} 字元！")
                            with st.expander("🔍 檢視已解析之筆記重點與爭點摘要", expanded=True):
                                st.text_area("筆記內容預覽（可用於客製命題）：", value=text_content, height=180, key="preview_drive_note")
                        elif text_content:
                            st.warning(text_content)
            else:
                st.info("💡 目前 Google Drive SamsungNotes 尚未收錄筆記檔案，請點擊下方按鈕自動同步。")
                if st.button("🔄 一鍵自 Google Drive「資源」目錄同步所有法學筆記"):
                    with st.spinner("正在同步..."):
                        c = sync_all_drive_notes_to_samsung_notes()
                        st.success(f"同步完成！共匯入 {c} 份筆記檔案。")
                        st.rerun()
        except Exception as e_drive:
            st.error(f"讀取 Google Drive 筆記失敗: {e_drive}")

    notes_from_file = ""
    with note_tab_upload:
        uploaded_note_file = st.file_uploader(
            "上傳個人筆記檔案（支援手寫掃描 PDF、Word、TXT、JPG、PNG、WEBP）：",
            type=["pdf", "docx", "txt", "md", "png", "jpg", "jpeg", "webp"],
            key="note_uploader"
        )
        if uploaded_note_file is not None:
            try:
                with st.spinner("🔍 正在解析文件；若為手寫或掃描檔，自動啟動 Gemini 多模態神經網路進行辨識..."):
                    parsed_text, _ = parse_document(uploaded_note_file.read(), uploaded_note_file.name, auto_ocr_handwriting=True)
                    notes_from_file = parsed_text
                    st.success(f"已讀取筆記《{uploaded_note_file.name}》，成功擷取/辨識出 {len(parsed_text):,} 字元！")
                    with st.expander("🔍 檢視已辨識/提取之筆記重點與爭點摘要"):
                        st.text_area("筆記內容預覽：", value=parsed_text, height=180, key="preview_ocr_note")
            except Exception as pe:
                st.error(f"檔案解析失敗: {pe}")

    notes_from_text = ""
    with note_tab_text:
        default_val = notes_from_drive if notes_from_drive else (notes_from_file if notes_from_file else "")
        notes_from_text = st.text_area(
            "直接貼上或補充法學筆記、實務見解或考點爭議重點：",
            value=default_val,
            height=140,
            placeholder="例如：貼上王澤鑑老師權益歸屬說論點、最高法院108台上大字1719號裁定重點摘要..."
        )

    notes_from_coursework = ""
    with note_tab_cw:
        cw_index_path = Path(RAW_DATA_DIR) / "academic_coursework_index.json"
        if cw_index_path.exists():
            try:
                with open(cw_index_path, "r", encoding="utf-8") as f_cw:
                    cw_list = json.load(f_cw)
                cw_sub_list = [c for c in cw_list if subject in c.get("subject", "") or c.get("subject", "") in subject]
                if not cw_sub_list:
                    cw_sub_list = cw_list

                all_cw_label = f"🌟 【全部分析】引用此考科所有名師講義重點 (共 {len(cw_sub_list)} 份)"
                cw_options = [all_cw_label] + [f"【{c.get('subject')}】{c.get('filename')} ({c.get('char_count', 0):,} 字)" for c in cw_sub_list]
                sel_cw = st.selectbox("選擇欲引用的名師講義/課輔檔案：", cw_options, key="select_coursework_doc")
                if sel_cw == all_cw_label:
                    st.caption(f"📁 涵蓋本考科全部 **{len(cw_sub_list)} 份** 名師講義與課輔大綱精華。")
                    if st.checkbox("✅ 確認載入全部講義精華爭點以進行全科命題", value=True, key="cb_use_all_cw"):
                        notes_from_coursework = "\n\n---\n\n".join([f"### 《{c.get('filename')}》（考科：{c.get('subject')}）\n" + c.get("summary_preview", "") for c in cw_sub_list])
                elif sel_cw:
                    sel_idx = cw_options.index(sel_cw) - 1
                    chosen_item = cw_sub_list[sel_idx]
                    st.caption(f"📁 來源目錄：`{chosen_item.get('relative_path')}` ｜ 字數：{chosen_item.get('char_count', 0):,} 字")
                    st.info(f"**講義摘要預覽**：\n{chosen_item.get('summary_preview', '')}...")
                    if st.checkbox("✅ 確認載入此講義重點以進行客製命題", value=True, key="cb_use_cw"):
                        notes_from_coursework = chosen_item.get("summary_preview", "")
            except Exception as e:
                st.error(f"讀取講義庫失敗: {e}")
        else:
            st.info("💡 講義索引檔案載入中（若尚未生成完畢，稍候將自動呈現）。")

    final_notes = (notes_from_text if notes_from_text else (notes_from_drive if notes_from_drive else (notes_from_file if notes_from_file else notes_from_coursework))).strip()
    if final_notes:
        st.info(f"💡 目前已載入個人筆記重點（共 {len(final_notes):,} 字），命題引擎將嚴密結合您的筆記重點進行客製化命題！")

    if stage == "一試 (選擇題 / 單選題)":
        stage1_tab_ai, stage1_tab_300 = st.tabs([
            "🎲 AI 智慧命題模式（任意題數 & 支援手寫筆記 OCR 客製出題）",
            "📖 司律一試 300 題全真模擬題庫實戰（自選題數 5~50 題即時測驗）"
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
                    status_text.success(f"🎉 成功生成【{subject}】共 {len(exam_res.get('questions', []))} 題司律一試測驗卷！")
                    st.session_state["stage1_exam_data"] = exam_res

                except Exception as e:
                    st.error(f"出題失敗: {e}")

        with stage1_tab_300:
            st.markdown("#### 📖 司律一試行政法 300 題全真模擬題庫（精選範本試卷）")
            st.write("已完整解析收錄附件《司律一試行政法全真模擬題庫暨詳解（300題完整版）》，可自由指定抽考題數，包含標準答案速查表、逐題解析與實務裁判字號！")

            c300_col1, c300_col2, c300_col3 = st.columns([1, 1, 1])
            with c300_col1:
                part_choice = st.selectbox(
                    "選擇篇章大類：",
                    [
                        "全卷 300 題隨機抽考",
                        "第一篇：核心法理、公私法性質、依法行政與裁量 (第 1~90 題)",
                        "第二篇：具體行政行為定性分類、附款、效力與廢止 (第 91~240 題)",
                        "第三篇：綜合案例實事實務題組題 (第 241~300 題)"
                    ]
                )
            with c300_col2:
                cat_300_categories = [
                    "全部考點分類 (不限)",
                    "⚖️ [依法行政原則與法源]",
                    "🏛️ [公私法性質與雙階理論]",
                    "📜 [不確定法律概念與行政裁量]",
                    "📑 [行政處分之定性與實例]",
                    "📌 [行政處分之附款與效力]",
                    "📝 [行政契約與事實行為]",
                    "📜 [行政命令與地方法規]",
                    "🌐 [行政法關係與權利義務]",
                    "🧩 [第 241~300 題：綜合實務題組題]"
                ]
                cat_300_choice = st.selectbox(
                    "🎯 考點分類專題篩選：",
                    cat_300_categories,
                    key="sel_cat_300_choice"
                )
            with c300_col3:
                count_300_choice = st.selectbox(
                    "抽題題數：",
                    ["5 題 (快速隨測)", "10 題 (標準測驗)", "20 題 (大模考)", "30 題 (全篇實戰)", "50 題 (高強度特訓)", "自訂題數"],
                    key="count_300_select"
                )
                if count_300_choice == "自訂題數":
                    take_count = st.number_input("請輸入抽取題數 (1~100 題)：", min_value=1, max_value=100, value=10, key="custom_300_count")
                else:
                    take_count = int(count_300_choice.split(" ")[0])

            if st.button("🚀 從 300 題庫抽取試題開始測驗", type="primary", use_container_width=True):
                bank_file = Path(RAW_DATA_DIR) / "admin_law_300_mcqs.json"
                if not bank_file.exists():
                    candidate_p = Path(__file__).resolve().parent.parent / "raw_exams" / "admin_law_300_mcqs.json"
                    if candidate_p.exists():
                        bank_file = candidate_p
                if not bank_file.exists():
                    st.error("找不到 300 題庫檔案，請確認 raw_exams/admin_law_300_mcqs.json 是否存在。")
                else:
                    import random
                    import unicodedata
                    with open(bank_file, "r", encoding="utf-8") as f:
                        bank_data = json.load(f)

                    pool = bank_data.get("questions", [])
                    # 1. 篇章過濾
                    if part_choice.startswith("第一篇"):
                        pool = [q for q in pool if 1 <= q.get("question_no", 0) <= 90]
                    elif part_choice.startswith("第二篇"):
                        pool = [q for q in pool if 91 <= q.get("question_no", 0) <= 240]
                    elif part_choice.startswith("第三篇"):
                        pool = [q for q in pool if 241 <= q.get("question_no", 0) <= 300]

                    # 2. 考點分類過濾
                    if cat_300_choice != "全部考點分類 (不限)":
                        def match_cat_filter(q_item, chosen_cat):
                            q_cat = unicodedata.normalize("NFKC", q_item.get("category", "")).strip("[]")
                            q_no = q_item.get("question_no", 0)
                            if "依法行政" in chosen_cat or "法源" in chosen_cat:
                                return "依法行政" in q_cat or "法源" in q_cat
                            elif "公私法" in chosen_cat or "雙階" in chosen_cat:
                                return "公私法" in q_cat or "雙階" in q_cat or "採購" in q_cat
                            elif "行政裁量" in chosen_cat or "不確定法律概念" in chosen_cat:
                                return "裁量" in q_cat or "不確定法律概念" in q_cat
                            elif "行政處分之定性" in chosen_cat:
                                return "行政處分" in q_cat and "附款" not in q_cat and "效力" not in q_cat
                            elif "附款" in chosen_cat or "效力" in chosen_cat:
                                return "附款" in q_cat or "效力" in q_cat
                            elif "行政契約" in chosen_cat or "事實行為" in chosen_cat:
                                return "行政契約" in q_cat or "事實行為" in q_cat or "自願執行" in q_cat
                            elif "行政命令" in chosen_cat or "地方法規" in chosen_cat:
                                return "命令" in q_cat or "法規" in q_cat
                            elif "行政法關係" in chosen_cat:
                                return "行政法關係" in q_cat or "特別權力" in q_cat
                            elif "題組" in chosen_cat:
                                return 241 <= q_no <= 300 or "題組" in q_cat
                            return True

                        filtered_pool = [q for q in pool if match_cat_filter(q, cat_300_choice)]
                        if filtered_pool:
                            pool = filtered_pool
                        else:
                            st.warning(f"在篇章【{part_choice[:10]}】中未篩得【{cat_300_choice}】題目，已擴展至全卷相同考點抽取。")
                            pool = [q for q in bank_data.get("questions", []) if match_cat_filter(q, cat_300_choice)]

                    if not pool:
                        pool = bank_data.get("questions", [])

                    selected_qs = random.sample(pool, min(take_count, len(pool)))
                    # 重新編排題號
                    reindexed_qs = []
                    new_answer_key = {}
                    for i, q in enumerate(selected_qs, 1):
                        q_copy = dict(q)
                        q_copy["original_no"] = q_copy.get("question_no")
                        q_copy["question_no"] = i
                        ans = q_copy.get("answer", "A")
                        new_answer_key[str(i)] = ans
                        reindexed_qs.append(q_copy)

                    cat_tag = f"・{cat_300_choice}" if cat_300_choice != "全部考點分類 (不限)" else ""
                    st.session_state["stage1_exam_data"] = {
                        "subject": "行政法",
                        "topic": f"300題模擬題庫精選（{part_choice[:10]}{cat_tag}）",
                        "total_count": len(reindexed_qs),
                        "questions": reindexed_qs,
                        "answer_key": new_answer_key
                    }
                    st.success(f"已成功依【{part_choice[:10]}】與【{cat_300_choice}】抽取 {len(reindexed_qs)} 題，請於下方開始作答！")

        # 若 session 中有一試試題，展示作答、速查表與詳解
        if "stage1_exam_data" in st.session_state:
            exam_data = st.session_state["stage1_exam_data"]
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
                    key=f"user_choice_{q_no}"
                )
                if user_ans:
                    user_answers[str(q_no)] = user_ans[1] # 提取 'A'

                st.write("")

            col_submit, col_export = st.columns([1, 1])
            with col_submit:
                if st.button("🏁 交卷立即線上批改評分", type="primary"):
                    st.session_state["stage1_graded"] = True
                    st.session_state["stage1_user_answers"] = user_answers
                    st.rerun()

            with col_export:
                md_content = LawExamGenerator.format_stage1_exam_markdown(exam_data)
                st.download_button(
                    label="💾 一鍵下載完整全真模擬試卷 (Markdown 檔)",
                    data=md_content,
                    file_name=f"司律一試_{exam_data.get('subject')}_{exam_data.get('topic')[:10]}_{len(questions)}題.md",
                    mime="text/markdown"
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

            # 第二部分：標準答案速查表 (置於試題區與線上批改評分之後，避免提前洩題)
            st.divider()
            st.subheader(f"📋 【第二部分：標準答案速查表】(共 {len(questions)} 題)")

            u_answers_map = st.session_state.get("stage1_user_answers", user_answers) if is_graded else {}
            # 以每 5 題一行排版速查表
            cols_per_row = 5
            for row_start in range(1, len(questions) + 1, cols_per_row):
                key_cols = st.columns(cols_per_row)
                for c_idx in range(cols_per_row):
                    q_num = row_start + c_idx
                    if q_num <= len(questions):
                        with key_cols[c_idx]:
                            c_ans = answer_key.get(str(q_num), 'A')
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
elif app_mode == "📚 歷年真題庫檢索與模擬演練 (法研所 / 轉學考 / 司法官律師 / 司法特考)":
    st.header("📚 全台法學歷年真題庫與名師講義精華檢索")

    comm_q_all = load_community_questions()
    m3_tab1, m3_tab2, m3_tab3 = st.tabs([
        "🏛️ 考選部與臺大法研/轉學考歷年真題庫",
        "🎓 大學名師講義與課輔爭點知識庫 (190+ 份各科講義與簡報)",
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
elif app_mode == "📖 高分權威擬答生成":
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
elif app_mode == "🔍 統一法學檢索樞紐與 AI 判決研析 (布林檢索・多庫矩陣・爭點大典)" or "爭點查詢" in app_mode or "統一法學檢索" in app_mode or "爭點速查" in app_mode:
    st.header("🔍 統一法學檢索樞紐與 AI 判決深度研析中心")
    st.caption("全面整合【法源式布林邏輯精準檢索】、【全方位法學統一檢索】、【AI 判決精華深度摘要】與【案例橫向比對 (Case Distinguishing)】，直通七法、法源法律網與司法院 30 年判決，支援一站式爭點與判解秒級研析。")

    st.divider()

    m5_sub_modes = [
        "⚖️ 法源級 裁判書多維專業檢索 (支援布林語法)",
        "⚡ 法律人 (LawPlayer) 極速熱搜與全國資料庫矩陣",
        "🤖 AI 智慧爭點深度剖析與二試上位卷 IRAC 大典",
        "📜 AI 判決精華深度摘要 (主文・事實・心證・評析)",
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

    # ==================== 子功能 1: ⚖️ 法源級 裁判書多維專業檢索 (LawBank 規格) ====================
    if m5_active_tab == m5_sub_modes[0]:
        st.subheader("⚖️ 法源法律網 (LawBank) 規格裁判書多維專業檢索系統")
        st.caption("完整比照「法源法律網 (LawBank)」專業裁判書查詢規格，支援布林邏輯運算（＆、＋、－、( )），與法院體系、民國年度 (jud_year)、常用字別 (sel_judword)、裁判案號 (jud_no)、裁判案由 (jt)、主文/心證 (jmain/txtopinion)、案件爭點 (txtargument)、相關法條 (lc1a/lc1b) 全維度交叉篩選。")

        # 1. 快速載入經典檢索範本
        st.markdown("##### 💡 經典法源檢索條件一鍵快選（含布林精準範本）：")
        lb_presets = [
            ("108 台上大 1719 (借名處分有權說)", "🏛️ 最高法院 (終審法院)", "108", "台上大", "1719", "借名登記", "有權處分", "", ""),
            ("布林範本 (借名＋信託＆1719－善意)", "🏛️ 最高法院 (終審法院)", "", "", "", "借名登記 ＋ 信託", "1719 － 善意受讓", "", ""),
            ("111 憲判字第 16 號 (警察臨檢救濟)", "🏛️ 憲法法院系統", "111", "憲判", "16", "警察職權", "正當法律程序", "臨檢救濟", "憲法第8條"),
            ("109 台上大 908 (侵權純經濟損失)", "🏛️ 最高法院 (終審法院)", "109", "台上大", "908", "損害賠償", "純經濟上損失", "過失侵權", "民法第184條"),
            ("臺南地院 106 亡 40 (重大災難死亡宣告)", "🏛️ 地方法院 (一審事實審)", "106", "亡", "40", "宣告死亡", "特別災難", "失蹤期間", "民法第8條"),
            ("108 台上大 897 (保險法 64 與民法 92)", "🏛️ 最高法院 (終審法院)", "108", "台上大", "897", "給付保險金", "解除契約", "詐欺撤銷", "保險法第64條")
        ]
        p_row1 = st.columns(3)
        p_row2 = st.columns(3)
        for p_idx, (p_lbl, p_ct, p_yr, p_wd, p_no, p_cause, p_hold, p_arg, p_law) in enumerate(lb_presets):
            target_col = p_row1[p_idx] if p_idx < 3 else p_row2[p_idx - 3]
            with target_col:
                if st.button(f"📌 {p_lbl}", key=f"btn_lb_preset_{p_idx}", use_container_width=True):
                    st.session_state["lb_court_system"] = p_ct
                    st.session_state["lb_input_year"] = p_yr
                    st.session_state["lb_sel_jword"] = p_wd if p_wd in LAWBANK_COMMON_CASE_WORDS else "全部字別 (不限)"
                    st.session_state["lb_input_word"] = p_wd
                    st.session_state["lb_input_num"] = p_no
                    st.session_state["lb_input_cause"] = p_cause
                    st.session_state["lb_input_opinion"] = p_hold
                    st.session_state["lb_input_arg"] = p_arg
                    st.session_state["lb_input_statute"] = p_law
                    st.session_state["lb_did_search"] = True
                    st.rerun()

        st.markdown("---")

        # 2. 法源檢索表單
        col_c1, col_c2 = st.columns([1.5, 1])
        with col_c1:
            court_opts = list(LAWBANK_COURTS_TAXONOMY.keys())
            cur_court = st.session_state.get("lb_court_system", court_opts[0])
            cur_court_idx = court_opts.index(cur_court) if cur_court in court_opts else 0
            sel_court = st.selectbox("1. 🏛️ 法院體系與審級選單：", court_opts, index=cur_court_idx, key="lb_court_system")
        with col_c2:
            sel_case_type = st.radio("2. ⚖️ 裁判類別：", ["全部", "判決", "裁定", "大法官解釋"], horizontal=True, key="lb_case_type")

        # 裁判字號組合器 (jud_year, sel_judword, jud_no)
        st.markdown("**3. 🔖 裁判字號精準組合器 (LawBank Citation Composer)：**")
        w_c1, w_c2, w_c3, w_c4 = st.columns([1, 1.4, 1.4, 1.2])
        with w_c1:
            val_yr = st.session_state.get("lb_input_year", "")
            lb_year = st.text_input("民國年 (jud_year)：", value=val_yr, placeholder="例：108", key="lb_input_year")
        with w_c2:
            val_wd_sel = st.session_state.get("lb_sel_jword", LAWBANK_COMMON_CASE_WORDS[0])
            sel_idx = LAWBANK_COMMON_CASE_WORDS.index(val_wd_sel) if val_wd_sel in LAWBANK_COMMON_CASE_WORDS else 0
            sel_jword_choice = st.selectbox("常用字別下拉 (sel_judword)：", LAWBANK_COMMON_CASE_WORDS, index=sel_idx, key="lb_sel_jword")
        with w_c3:
            default_w = sel_jword_choice if sel_jword_choice != "全部字別 (不限)" else st.session_state.get("lb_input_word", "")
            lb_word = st.text_input("字別文字 (可自訂)：", value=default_w, placeholder="例：台上大、憲判", key="lb_input_word")
        with w_c4:
            val_no = st.session_state.get("lb_input_num", "")
            lb_num = st.text_input("裁判案號 (jud_no)：", value=val_no, placeholder="例：1719", key="lb_input_num")

        # 法源四大實體法學檢索欄位
        st.markdown("**4. ⚖️ 法源四大實體法學檢索欄位：**")
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

        # 檢索與重設按鈕
        col_btn_search, col_btn_clear = st.columns([3, 1])
        with col_btn_search:
            btn_exec_lb = st.button("🚀 執行法源多維度精準檢索", type="primary", use_container_width=True, key="btn_exec_lawbank_search")
        with col_btn_clear:
            if st.button("✖️ 清除檢索條件", use_container_width=True, key="btn_clear_lb_all"):
                for k in ["lb_court_system", "lb_input_year", "lb_sel_jword", "lb_input_word", "lb_input_num", "lb_input_cause", "lb_input_opinion", "lb_input_arg", "lb_input_statute", "lawbank_search_results", "lb_did_search"]:
                    st.session_state.pop(k, None)
                st.rerun()

        # 觸發檢索
        do_search = btn_exec_lb or st.session_state.pop("lb_did_search", False)
        if do_search:
            with st.spinner("正在以法源規格多維度檢索本機 1,256 筆權威判解庫..."):
                try:
                    results = search_precedents_lawbank_style(
                        court_system=sel_court,
                        jud_year=lb_year,
                        jud_word=lb_word,
                        jud_no=lb_num,
                        case_cause=lb_cause,
                        main_holding=lb_opinion,
                        argument_issue=lb_argument,
                        cited_laws=lb_statute,
                        case_type=sel_case_type,
                        top_k=50
                    )
                    st.session_state["lawbank_search_results"] = results
                except Exception as e:
                    st.error(f"法源多維檢索失敗: {e}")

        # 檢索結果展示
        if "lawbank_search_results" in st.session_state:
            lb_results = st.session_state["lawbank_search_results"]
            st.divider()
            st.markdown(f"### 📋 法源規格檢索結果清單 (共命中 {len(lb_results)} 筆裁判)")

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
                st.info("💡 未找到完全符合條件之裁判。建議可放寬字別或關鍵字再次檢索！")
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

                        b_c1, b_c2, b_c3, b_c4 = st.columns([1.5, 1.5, 1.2, 1.2])
                        with b_c1:
                            if st.button("⚡ AI 判決深度摘要", key=f"btn_lb_sum_{idx}", use_container_width=True):
                                st.session_state["target_summary_case_id"] = c_id
                                st.session_state["m5_sub_mode_idx"] = 3
                                st.rerun()
                        with b_c2:
                            if st.button("🔄 帶入案例橫向比對", key=f"btn_lb_cmp_{idx}", use_container_width=True):
                                st.session_state["target_compare_case_a"] = c_id
                                st.session_state["m5_sub_mode_idx"] = 4
                                st.rerun()
                        with b_c3:
                            st.link_button("📚 法源全文", f"https://www.lawbank.com.tw/treatise/pl_search.aspx?keyword={c_id}", use_container_width=True)
                        with b_c4:
                            st.link_button("⚡ 法律人直查", f"https://lawplayer.com/search?keyword={c_id}", use_container_width=True)

    # ==================== 子功能 2: ⚡ 法律人 (LawPlayer) 極速熱搜與全國資料庫矩陣 ====================
    elif m5_active_tab == m5_sub_modes[1]:
        st.subheader("⚡ 法律人 (LawPlayer) 極速熱搜與全國法學資料庫矩陣")
        st.caption("比照「法律人 LawPlayer」秒級熱搜與全域跨庫導航，支援高頻爭點晶片快選、雙向自然語言搜尋、本機 1,256 筆裁判與六法法條即時命中，並跨庫直通全國 8 大權威司法與法學文獻系統！")

        # 法律人熱搜晶片
        st.markdown("##### 🔥 法律人熱搜爭點與標籤快選（點擊直接秒速搜尋）：")
        lp_hot_tags = [
            "民法 184 (侵權行為)", "釋字 748 (同性婚姻)", "111 憲判字第 16 號 (臨檢救濟)",
            "108 台上大 1719 (借名處分)", "109 台上大 908 (純經濟損失)", "刑法 19 (原因自由行為)",
            "刑法 339 (詐欺取財罪)", "民法 179 (不當得利)", "民訴 277 (舉證責任分配)",
            "刑訴 158-4 (證據排除法則)", "公司法 185 (重大營業行為)", "保險法 64 (據實說明義務)",
            "民法 87 (通謀虛偽意思表示)", "行政程序法 117 (違法處分撤銷)", "刑法 31 (共同正犯與身分犯)", "民法 244 (撤銷詐害債權)"
        ]

        cols_per_row = 4
        for r_i in range(0, len(lp_hot_tags), cols_per_row):
            t_cols = st.columns(cols_per_row)
            for c_i in range(cols_per_row):
                tag_idx = r_i + c_i
                if tag_idx < len(lp_hot_tags):
                    tag_name = lp_hot_tags[tag_idx]
                    with t_cols[c_i]:
                        if st.button(f"🏷️ {tag_name}", key=f"btn_lp_tag_{tag_idx}", use_container_width=True):
                            clean_tag = re.sub(r'[\(\)（）]', '', tag_name)
                            st.session_state["lp_search_query"] = clean_tag
                            st.session_state["lp_exec_search"] = True
                            st.rerun()

        st.markdown("---")

        # 法律人風格搜尋列
        cur_lp_val = st.session_state.get("lp_search_query", "")
        lp_query_input = st.text_input(
            "⚡ 法律人極速全域搜尋框（支援關鍵字、判決字號、法條或自然語言案例事實）：",
            value=cur_lp_val,
            placeholder="例如：民法 184、借名登記、108台上大1719、原因自由行為、撤銷詐害債權...",
            key="lp_search_input"
        )

        col_lp_btn1, col_lp_btn2 = st.columns([3, 1])
        with col_lp_btn1:
            btn_lp_search = st.button("⚡ 啟動法律人極速跨庫查找", type="primary", use_container_width=True, key="btn_exec_lp_search")
        with col_lp_btn2:
            if st.button("✖️ 清除搜尋", use_container_width=True, key="btn_clear_lp_search"):
                st.session_state.pop("lp_search_query", None)
                st.session_state.pop("lp_search_hits", None)
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
                        hits = engine.unified_legal_search(query=target_q)
                        st.session_state["lp_search_hits"] = hits
                        st.session_state["lp_search_query"] = target_q
                    except Exception as e:
                        st.error(f"法律人檢索失敗: {e}")

        # 法律人搜尋結果與全國資料庫矩陣
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

                        btn_c1, btn_c2, btn_c3, btn_c4 = st.columns([1.5, 1.5, 1.2, 1.2])
                        with btn_c1:
                            if st.button(f"⚡ AI 判決摘要", key=f"btn_lp_sum_{p_idx}", use_container_width=True):
                                st.session_state["target_summary_case_id"] = c_id
                                st.session_state["m5_sub_mode_idx"] = 3
                                st.rerun()
                        with btn_c2:
                            if st.button(f"🔄 案例橫向比對", key=f"btn_lp_cmp_{p_idx}", use_container_width=True):
                                st.session_state["target_compare_case_a"] = c_id
                                st.session_state["m5_sub_mode_idx"] = 4
                                st.rerun()
                        with btn_c3:
                            st.link_button("📚 法源直查", f"https://www.lawbank.com.tw/treatise/pl_search.aspx?keyword={c_id}", use_container_width=True)
                        with btn_c4:
                            st.link_button("⚡ 法律人直查", f"https://lawplayer.com/search?keyword={c_id}", use_container_width=True)

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
                    st.session_state["m5_sub_mode_idx"] = 2
                    st.session_state["ai_query_auto_exec"] = True
                    st.rerun()
            with col_jmp2:
                if st.button("⚖️ 帶入進行【法源多維度細緻檢索】", use_container_width=True):
                    st.session_state["lb_input_cause"] = active_q
                    st.session_state["m5_sub_mode_idx"] = 0
                    st.session_state["lb_did_search"] = True
                    st.rerun()

    # ==================== 子功能 3: 🤖 AI 智慧爭點深度剖析與二試上位卷 IRAC 大典 ====================
    elif m5_active_tab == m5_sub_modes[2]:
        st.subheader("🤖 AI 智慧法學爭點剖析與二試上位卷 IRAC 大典")
        st.caption("引領司律考生直通二試上位卷！結合本機 1,256 筆權威判解庫與 Gemini 法學推論模型，自動輸出【法條構成要件】、【爭點所在】、【憲法法庭/大法庭/判例實務見解】、【學說肯否二說】及【俐落開標涵攝 IRAC 示範】。")

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

        # 考點快選
        available_sub_topics = get_subject_topics_taxonomy(q_subject)
        if available_sub_topics:
            sub_topic_options = ["-- 💡 快選此考科高頻核心爭點（點選自動帶入） --"] + list(available_sub_topics.keys())
            sel_preset_q_topic = st.selectbox(
                f"依【{q_subject.split(' ')[0]}】快選必考爭點：",
                sub_topic_options,
                key=f"sel_query_preset_topic_{q_subject}"
            )
            if sel_preset_q_topic and sel_preset_q_topic != "-- 💡 快選此考科高頻核心爭點（點選自動帶入） --":
                st.session_state["ai_query_input_text"] = available_sub_topics[sel_preset_q_topic]

        # 法源布林邏輯精確搜尋範本快選
        st.caption("💡 **法源式布林邏輯精確搜尋**：支援 `＆`（且）、`＋`（或）、`－`（排除）、`( )`（優先組合）：")
        b_c1, b_c2, b_c3 = st.columns(3)
        with b_c1:
            if st.button("📌 (借名登記 ＋ 信託) ＆ (108台上大1719 － 善意)", key="btn_bool_ex1", use_container_width=True):
                st.session_state["ai_query_input_text"] = "(借名登記 ＋ 信託) ＆ (108台上大字1719 － 善意受讓)"
                st.rerun()
        with b_c2:
            if st.button("📌 (洗錢防制法 ＋ 詐欺) ＆ (人頭帳戶 － 幫助犯)", key="btn_bool_ex2", use_container_width=True):
                st.session_state["ai_query_input_text"] = "(洗錢防制法 ＋ 詐欺) ＆ (人頭帳戶 － 幫助犯)"
                st.rerun()
        with b_c3:
            if st.button("📌 (民法184 ＋ 侵權) ＆ (純經濟損失 － 故意)", key="btn_bool_ex3", use_container_width=True):
                st.session_state["ai_query_input_text"] = "(民法184 ＋ 侵權行為) ＆ (純粹經濟上損失 － 故意)"
                st.rerun()

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
                with st.spinner("AI 司法典試顧問正在跨庫比對本機 1,256 筆裁判並提煉 IRAC 深度法理報告..."):
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

                        btn_c1, btn_c2 = st.columns(2)
                        with btn_c1:
                            if st.button(f"⚡ AI 判決摘要", key=f"btn_irac_sum_{m_idx}", use_container_width=True):
                                st.session_state["target_summary_case_id"] = c_id
                                st.session_state["m5_sub_mode_idx"] = 3
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
                    st.session_state["app_mode"] = mode_options[0]
                    st.rerun()
            with act_col2:
                if st.button("📖 【一鍵帶入高分擬答生成】針對此爭點撰寫申論答題", use_container_width=True, key="btn_imp_ans_m5"):
                    st.session_state["m4_target_question"] = res.get("query", "")
                    st.session_state["app_mode"] = mode_options[3]
                    st.rerun()

    # ==================== 子功能 4: 📜 AI 判決摘要精析 ====================
    elif m5_active_tab == m5_sub_modes[3]:
        st.subheader("📜 AI 判決深度摘要精析")
        st.caption("精準解構各級法院裁判書，嚴格提煉六大核心結構：【主文】、【案例事實】、【案件爭點】、【雙方所述】、【法院心證】及【個人評析與相似判決對照】。")

        # 快速挑選熱門案例
        st.markdown("##### 💡 經典權威裁判快速帶入：")
        quick_cases = [
            ("借名處分效力", "最高法院 108 年度台上大字第 1719 號民事大法庭裁定"),
            ("警察臨檢救濟", "憲法法庭 111年憲判字第16號判決"),
            ("侵權純經濟損失", "最高法院 109 年度台上大字第 908 號民事大法庭裁定"),
            ("特別災難死亡宣告", "臺灣臺南地方法院106年度亡字第40號"),
            ("管轄與舉證責任", "台北地院100年更一字9號"),
            ("最新民事事實審", "臺灣高等法院民事判決115年度上字第620號")
        ]
        q_cols = st.columns(len(quick_cases))
        for qc_idx, (qc_lbl, qc_id) in enumerate(quick_cases):
            with q_cols[qc_idx]:
                if st.button(f"📌 {qc_lbl}", key=f"btn_qc_{qc_idx}", use_container_width=True):
                    st.session_state["target_summary_case_id"] = qc_id
                    st.session_state.pop("judgment_summary_result", None)

        all_precedents_tags = ["-- 📚 從本機 1,256 筆權威庫中挑選裁判 --"] + get_all_precedent_options()
        
        current_case_id_val = st.session_state.get("target_summary_case_id", "")
        default_tag_idx = 0
        if current_case_id_val:
            for opt_idx, opt in enumerate(all_precedents_tags):
                if current_case_id_val in opt:
                    default_tag_idx = opt_idx
                    break

        sel_prec_tag = st.selectbox(
            "從本機權威裁判庫挑選（支援最高院大法庭、憲判字、高院、筆記地院判決）：",
            all_precedents_tags,
            index=default_tag_idx,
            key="sel_prec_for_summary"
        )
        if sel_prec_tag and sel_prec_tag != "-- 📚 從本機 1,256 筆權威庫中挑選裁判 --":
            current_case_id_val = sel_prec_tag.split(" ｜ ")[0].strip()

        col_c_in1, col_c_in2 = st.columns([2, 1])
        with col_c_in1:
            inp_case_id = st.text_input(
                "欲進行 AI 摘要之裁判案號 / 字號：",
                value=current_case_id_val,
                placeholder="例如：最高法院 108 年度台上大字第 1719 號、臺灣臺南地方法院 106 年度亡字第 40 號...",
                key="inp_summary_case_id"
            )
        with col_c_in2:
            inp_case_sub = st.selectbox(
                "所屬考科領域（選填）：",
                ["民事法 (民總/債/物/身分)", "刑事法 (刑總/刑分)", "公法 (憲法/行政法)", "商事法 (公司/證交/保險)", "智慧財產權法", "跨領域綜合實務"],
                key="inp_summary_case_sub"
            )

        with st.expander("📝 自訂貼上裁判書全文或主文事實（若為庫外判決或特定段落，可貼於此以獲取最精準心證分析）", expanded=False):
            inp_custom_jud_text = st.text_area(
                "裁判書內文或判旨段落：",
                height=140,
                placeholder="貼上裁判書全文、主文、事實與理由段落...",
                key="inp_summary_custom_text"
            )

        col_b_sum, col_b_clr = st.columns([3, 1])
        with col_b_sum:
            btn_start_summary = st.button("🚀 啟動 AI 判決深度摘要生成", type="primary", use_container_width=True, key="btn_exec_jud_summary")
        with col_b_clr:
            if st.button("✖️ 清除摘要", use_container_width=True, key="btn_clr_jud_summary"):
                st.session_state.pop("judgment_summary_result", None)
                st.session_state["target_summary_case_id"] = ""
                st.rerun()

        if btn_start_summary:
            if not inp_case_id.strip() and not inp_custom_jud_text.strip():
                st.warning("請先輸入裁判案號或貼上裁判文字！")
            else:
                target_id = inp_case_id.strip() or "自訂裁判書節錄"
                with st.spinner(f"AI 司法研究官正在調閱並深度解構【{target_id}】之主文、事實、爭點、雙方所述與法院心證..."):
                    try:
                        engine = LegalIssueQueryEngine()
                        sum_res = engine.summarize_judgment(
                            case_id=target_id,
                            judgment_text=inp_custom_jud_text,
                            subject=inp_case_sub
                        )
                        st.session_state["judgment_summary_result"] = sum_res
                        st.session_state["target_summary_case_id"] = target_id
                    except Exception as se:
                        st.error(f"摘要產出失敗: {se}")

        if "judgment_summary_result" in st.session_state:
            s_res = st.session_state["judgment_summary_result"]
            s_md = s_res.get("markdown_result", "")
            s_id = s_res.get("case_id", "")

            st.divider()
            st.subheader(f"🏛️ 【{s_id}】AI 判決精華深度摘要報告")

            # 外部查閱按鈕
            ext_u = s_res.get("external_search_urls", {})
            if ext_u:
                st.caption("權威資料庫全文直連：")
                u_c1, u_c2, u_c3 = st.columns(3)
                with u_c1:
                    st.link_button("⚖️ 七法 Lawsnote 全文檢索", f"https://www.lawsnote.com/search?keyword={s_id}", use_container_width=True)
                with u_c2:
                    st.link_button("🏛️ 司法院裁判書系統全文", f"https://judgment.judicial.gov.tw/FJUD/default.aspx?k={s_id}", use_container_width=True)
                with u_c3:
                    st.link_button("📚 法源法律網檢索", f"https://www.lawbank.com.tw/treatise/pl_search.aspx?keyword={s_id}", use_container_width=True)

            # 渲染摘要內容
            st.markdown(s_md)

            st.divider()
            st.markdown("##### 🔗 本判決深度應用與跨功能聯動：")
            ac1, ac2, ac3 = st.columns(3)
            with ac1:
                st.download_button(
                    label=f"💾 下載本案 AI 摘要 (.md)",
                    data=s_md,
                    file_name=f"AI判決摘要_{re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '_', s_id)}.md",
                    mime="text/markdown",
                    use_container_width=True
                )
            with ac2:
                if st.button("🔄 帶入此判決進行【案例橫向比對】", use_container_width=True, key="btn_pass_to_cmp"):
                    st.session_state["target_compare_case_a"] = s_id
                    st.session_state["m5_sub_mode_idx"] = 4
                    st.rerun()
            with ac3:
                if st.button("📝 帶入試卷評分作為評分標準", use_container_width=True, key="btn_pass_sum_to_eval"):
                    st.session_state["question_text_content"] = f"【本案事實與法律爭點依據】：\n裁判字號：{s_id}\n請綜合上述爭議事實，分析當事人間之法律關係並予評析。"
                    st.session_state["rubric_text_content"] = s_md
                    st.session_state["imported_from_bank_label"] = f"AI判決摘要【{s_id}】"
                    st.session_state["app_mode"] = mode_options[0]
                    st.rerun()

    # ==================== 子功能 5: 🔄 案例橫向比對與分歧研析 ====================
    elif m5_active_tab == m5_sub_modes[4]:
        st.subheader("🔄 案例橫向比對與實務分歧研析 (Case Distinguishing)")
        st.caption("深度對比兩則裁判或大法庭裁定之【事實情境異同】、【當事人主張】、【法院心證核心對比】、【法律見解分歧 (肯否兩說)】及【司律二試案例區別作答心法】。")

        # 快速帶入經典對抗案例組
        st.markdown("##### 💡 經典爭議對照裁判組（一鍵載入比對）：")
        preset_pairs = [
            ("借名處分有權 vs 無權", "最高法院 108 年度台上大字第 1719 號民事大法庭裁定", "最高法院 96 年度台上字第 2851 號判決", "借名登記出名人未經同意處分標的物之效力"),
            ("臨檢盤查救濟途徑", "憲法法庭 111年憲判字第16號判決", "司法院釋字第535號解釋", "警察職權行使法臨檢盤查與異議救濟正當法律程序"),
            ("侵權純經濟損失保護", "最高法院 109 年度台上大字第 908 號民事大法庭裁定", "臺灣高等法院 102 年度上易字第 586 號判決", "民法第184條純粹經濟上損失之保護要件與過失涵攝"),
            ("死亡宣告特別災難要件", "臺灣臺南地方法院106年度亡字第40號", "最高法院110年度台上字第4015號", "民法第8條特別災難失蹤期間起算與公證力要件")
        ]
        p_cols = st.columns(len(preset_pairs))
        for pp_idx, (pp_lbl, pp_a, pp_b, pp_top) in enumerate(preset_pairs):
            with p_cols[pp_idx]:
                if st.button(f"⚖️ {pp_lbl}", key=f"btn_preset_cmp_{pp_idx}", use_container_width=True):
                    st.session_state["target_compare_case_a"] = pp_a
                    st.session_state["target_compare_case_b"] = pp_b
                    st.session_state["target_compare_topic"] = pp_top
                    st.session_state.pop("case_comparison_result", None)

        all_precedents_tags = ["-- 📚 從本機 1,256 筆權威庫中挑選裁判 --"] + get_all_precedent_options()

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
            if sel_tag_a and sel_tag_a != "-- 📚 從本機 1,256 筆權威庫中挑選裁判 --":
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
            if sel_tag_b and sel_tag_b != "-- 📚 從本機 1,256 筆權威庫中挑選裁判 --":
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
                st.link_button(f"🌐 七法直查【{ca_id}】", f"https://www.lawsnote.com/search?keyword={ca_id}", use_container_width=True)
            with cb_col2:
                st.link_button(f"🌐 七法直查【{cb_id}】", f"https://www.lawsnote.com/search?keyword={cb_id}", use_container_width=True)

            st.markdown(c_md)

            st.divider()
            st.markdown("##### 🔗 比對報告應用與後續演練：")
            cc_col1, cc_col2 = st.columns(2)
            with cc_col1:
                st.download_button(
                    label="💾 下載兩大案例橫向比對報告 (.md)",
                    data=c_md,
                    file_name=f"案例橫向比對_{re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '_', ca_id)}_vs_{re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '_', cb_id)}.md",
                    mime="text/markdown",
                    use_container_width=True
                )
            with cc_col2:
                if st.button("📝 帶入試卷評分作為進階對比評分標準", use_container_width=True, key="btn_pass_cmp_to_eval"):
                    st.session_state["question_text_content"] = f"【二試進階實例案例區別題目】：\n請就【{ca_id}】與【{cb_id}】所涉及之案件事實與法律見解分歧，深入剖析其法律爭點、各說立論與事實區別標準。"
                    st.session_state["rubric_text_content"] = c_md
                    st.session_state["imported_from_bank_label"] = f"案例橫向比對標準【{ca_id[:15]} vs {cb_id[:15]}】"
                    st.session_state["app_mode"] = mode_options[0]
                    st.rerun()

# ----------------- 模式: 地檢署起訴書 vs 法院判決書 (刑訴300・事實認定與論理比對) -----------------
elif app_mode == "⚖️ 地檢署起訴書 vs 法院判決書 (刑訴300・事實認定與論理比對)" or "起訴書" in app_mode:
    st.header("⚖️ 地檢署起訴書 vs 法院判決書「事實認定與論理比對」實戰引擎")
    st.caption("全台首創對標法源起訴書庫！深度剖析檢方起訴罪名、犯罪事實與法院合議庭最終判決之關鍵落差，嚴格檢驗刑事訴訟法第 300 條變更起訴法條、防禦權告知程序、證據排除與心證折衝，提煉二試上位卷踩分精華！")
    st.divider()

    st.markdown("##### 💡 經典權威代表性案例一鍵快選（即刻載入真實檢辯判決事實）：")
    p_cols = st.columns(len(BUILTIN_INDICTMENT_CASES))
    for c_idx, c_data in enumerate(BUILTIN_INDICTMENT_CASES):
        with p_cols[c_idx]:
            c_short_name = c_data['title'].split('：')[0]
            if st.button(f"📌 {c_short_name}", key=f"btn_ind_case_{c_idx}", use_container_width=True):
                st.session_state["ind_input_title"] = c_data["title"]
                st.session_state["ind_input_indictment"] = c_data["indictment_summary"]
                st.session_state["ind_input_judgment"] = c_data["judgment_summary"]
                st.session_state["ind_input_charge"] = c_data.get("charge", "")
                st.session_state["ind_input_court_charge"] = c_data.get("court_judgment_charge", "")
                st.toast(f"已成功載入：{c_short_name}", icon="📑")
                st.rerun()

    # 兩大輸入欄位
    col_ind, col_jud = st.columns(2)
    with col_ind:
        st.subheader("🏛️ 地檢署檢察官起訴書 (Indictment)")
        st.caption("案由、被告、犯罪要件事實陳述與所犯法條")
        val_ind = st.session_state.get("ind_input_indictment", BUILTIN_INDICTMENT_CASES[0]["indictment_summary"])
        ind_text = st.text_area("起訴書全文或事實節錄：", value=val_ind, height=350, key="txt_indictment_input")

    with col_jud:
        st.subheader("⚖️ 法院刑事裁判書 (Judgment)")
        st.caption("法院裁判主文、認定犯罪事實、心證論理與起訴法條變更說明")
        val_jud = st.session_state.get("ind_input_judgment", BUILTIN_INDICTMENT_CASES[0]["judgment_summary"])
        jud_text = st.text_area("判決書全文或理由節錄：", value=val_jud, height=350, key="txt_judgment_input")

    c_sub1, c_sub2 = st.columns([3, 1])
    with c_sub1:
        case_title_input = st.text_input("案件名稱或爭議核心主題：", value=st.session_state.get("ind_input_title", BUILTIN_INDICTMENT_CASES[0]["title"]), key="txt_ind_case_title")
    with c_sub2:
        btn_run_compare = st.button("🚀 啟動 AI 事實認定與論理比對", type="primary", use_container_width=True, key="btn_run_ind_jud_cmp")

    if btn_run_compare:
        if not ind_text.strip() or not jud_text.strip():
            st.warning("請確認起訴書與判決書內容皆不可為空！")
        else:
            with st.spinner("AI 刑事司法典試顧問正在逐項比對構成要件事實、刑訴第300條合法性與心證落差..."):
                try:
                    comparator = IndictmentJudgmentComparator()
                    cmp_res = comparator.compare(
                        indictment_text=ind_text,
                        judgment_text=jud_text,
                        case_title=case_title_input
                    )
                    st.session_state["last_ind_jud_res"] = cmp_res
                except Exception as ce:
                    st.error(f"比對分析失敗: {ce}")

    if "last_ind_jud_res" in st.session_state:
        cmp_res = st.session_state["last_ind_jud_res"]
        st.divider()
        st.markdown(f"### 📋 【{cmp_res.get('case_title', '')}】實務對照深度報告")
        st.markdown(cmp_res.get("markdown_result", ""))

        st.divider()
        st.subheader("🔗 實務成果一鍵轉化為司律考卷戰力：")
        exp_col1, exp_col2, exp_col3 = st.columns(3)
        with exp_col1:
            st.download_button(
                "📥 下載完整 Markdown 分析報告",
                data=cmp_res.get("markdown_result", ""),
                file_name=f"起訴書判決書比對_{re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '_', case_title_input)[:15]}.md",
                mime="text/markdown",
                use_container_width=True
            )
        with exp_col2:
            if st.button("📝 帶入試卷評分 (作為刑法刑訴評分標準)", use_container_width=True, key="btn_ind_to_eval"):
                st.session_state["question_text_content"] = f"【起訴書 vs 判決書實例申論題】：\n{ind_text[:800]}..."
                st.session_state["rubric_text_content"] = cmp_res.get("markdown_result", "")
                st.session_state["imported_from_bank_label"] = f"檢察實務對照【{case_title_input[:15]}】"
                st.session_state["app_mode"] = mode_options[0]
                st.rerun()
        with exp_col3:
            if st.button("📖 帶入高分擬答生成 (撰寫刑訴答題)", use_container_width=True, key="btn_ind_to_ans"):
                st.session_state["m4_target_question"] = f"某甲涉犯案件，檢察官起訴事實與法院審理心證如下：\n【起訴事實】：{ind_text[:500]}\n【法院認定】：{jud_text[:500]}\n試問：法院得否逕行變更起訴法條判決？其程序與實體要件為何？"
                st.session_state["app_mode"] = mode_options[3]
                st.rerun()

# ----------------- 模式: 一鍵 AI 裁判與長篇函釋要旨自動精鍊 (法源 AI 摘要旗艦) -----------------
elif app_mode == "📑 一鍵 AI 裁判與長篇函釋要旨自動精鍊 (法源 AI 摘要旗艦)" or "AI 摘要" in app_mode or "AI裁判" in app_mode or "AI 裁判" in app_mode:
    st.header("📑 一鍵 AI 裁判與長篇函釋核心要旨自動精鍊系統")
    st.caption("完美對標法源法律網 2025/2026 最新主推「AI摘要」旗艦功能！支援數萬字長篇裁判書、最高法院大法庭裁定、憲法法庭判決、金管會/經濟部/法務部部會長篇函釋，一鍵秒級萃取六大標準化法學精髓！")
    st.divider()

    st.markdown("##### 💡 經典權威判解與重大行政函釋一鍵快選（即刻體驗）：")
    d_cols = st.columns(len(BUILTIN_LANDMARK_DOCS))
    for d_idx, doc_item in enumerate(BUILTIN_LANDMARK_DOCS):
        with d_cols[d_idx]:
            d_short_label = doc_item['doc_type'].split(' ')[1] if ' ' in doc_item['doc_type'] else doc_item['doc_type']
            if st.button(f"📌 {d_short_label}", key=f"btn_sum_doc_{d_idx}", use_container_width=True):
                st.session_state["sum_input_title"] = doc_item["title"]
                st.session_state["sum_input_type"] = doc_item["doc_type"]
                st.session_state["sum_input_text"] = doc_item["text"]
                st.toast(f"已載入：{doc_item['title'][:15]}...", icon="📜")
                st.rerun()

    col_d1, col_d2 = st.columns([3, 1])
    with col_d1:
        default_d_title = st.session_state.get("sum_input_title", BUILTIN_LANDMARK_DOCS[0]["title"])
        doc_title_in = st.text_input("文書名稱 / 案號字號：", value=default_d_title, key="txt_sum_doc_title")
    with col_d2:
        type_options = ["🏛️ 最高法院/高院裁判書", "📜 憲法法庭判決/釋字", "📑 中央部會行政函釋 (經濟部/金管會)", "📋 行政訴願決定書", "🎓 法學期刊名家評釋論文"]
        default_d_type = st.session_state.get("sum_input_type", type_options[0])
        type_idx = type_options.index(default_d_type) if default_d_type in type_options else 0
        doc_type_in = st.selectbox("文書種類：", type_options, index=type_idx, key="sel_sum_doc_type")

    default_d_text = st.session_state.get("sum_input_text", BUILTIN_LANDMARK_DOCS[0]["text"])
    doc_full_text = st.text_area(
        "請貼上欲進行 AI 摘要之長篇裁判全文、大法庭裁定理由或主管機關行政函釋：",
        value=default_d_text,
        height=320,
        placeholder="在此貼上數千至數萬字之法學裁判或公報釋令全文...",
        key="txt_sum_full_text"
    )

    b_col1, b_col2 = st.columns([3, 1])
    with b_col1:
        btn_run_summarize = st.button("⚡ 啟動法源級 AI 核心要旨深度精鍊", type="primary", use_container_width=True, key="btn_run_legal_summarizer")
    with b_col2:
        if st.button("✖️ 清除內容", use_container_width=True, key="btn_clear_sum_input"):
            st.session_state["sum_input_text"] = ""
            st.session_state["sum_input_title"] = ""
            st.session_state.pop("last_ai_sum_res", None)
            st.rerun()

    if btn_run_summarize:
        if not doc_full_text.strip():
            st.warning("請先貼上裁判全文或行政函釋！")
        else:
            with st.spinner("AI 大法官書記處法官正在解構案情、主文心證、關鍵法理與二試上位金句..."):
                try:
                    summarizer = AILegalSummarizer()
                    sum_res = summarizer.summarize(
                        doc_text=doc_full_text,
                        doc_type=doc_type_in,
                        title=doc_title_in
                    )
                    st.session_state["last_ai_sum_res"] = sum_res
                except Exception as se:
                    st.error(f"AI 摘要失敗: {se}")

    if "last_ai_sum_res" in st.session_state:
        sum_res = st.session_state["last_ai_sum_res"]
        st.divider()
        st.markdown(f"### 📑 【{sum_res.get('title', '')}】AI 法源級核心要旨精鍊報告")
        st.markdown(sum_res.get("markdown_result", ""))

        st.divider()
        st.subheader("🔗 摘要成果一鍵轉化為司律考卷戰力：")
        s_act1, s_act2, s_act3 = st.columns(3)
        with s_act1:
            st.download_button(
                "📥 下載完整 Markdown 摘要報告",
                data=sum_res.get("markdown_result", ""),
                file_name=f"AI摘要_{re.sub(r'[^0-9a-zA-Z\u4e00-\u9fa5]', '_', doc_title_in)[:15]}.md",
                mime="text/markdown",
                use_container_width=True
            )
        with s_act2:
            if st.button("📝 帶入試卷評分 (作為評分標準)", use_container_width=True, key="btn_sum_to_eval"):
                st.session_state["question_text_content"] = f"【核心爭點題目】：\n請就【{doc_title_in}】之案例事實與爭點深入申論其法律效果與實務見解。"
                st.session_state["rubric_text_content"] = sum_res.get("markdown_result", "")
                st.session_state["imported_from_bank_label"] = f"AI裁判摘要標準【{doc_title_in[:15]}】"
                st.session_state["app_mode"] = mode_options[0]
                st.rerun()
        with s_act3:
            if st.button("📖 帶入高分擬答生成", use_container_width=True, key="btn_sum_to_ans"):
                st.session_state["m4_target_question"] = f"請就【{doc_title_in}】所涉及之核心法律爭點，依 IRAC 架構撰寫標準上位卷擬答。"
                st.session_state["app_mode"] = mode_options[3]
                st.rerun()

# ----------------- 模式 6: 智慧六法與條文判解綜合標註 (法條・沿革・爭點・筆記) -----------------
elif app_mode == "⚖️ 智慧六法與條文判解綜合標註 (法條・沿革・爭點・筆記)":
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
        st.caption("💡 **法源布林精準搜尋**：支援 `＆`（且）、`＋`（或）、`－`（排除）、`( )`（優先組合）。例：`(侵權行為 ＋ 債務不履行) ＆ (純粹經濟 － 故意)`")

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

            badge_amend = " ｜ 🆕 【最新修正施行】" if art.get("is_latest_amendment") else ""
            badge_prec = f" ｜ 🏛️ 【收錄 {len(precedents)} 筆大法庭/憲判字】" if precedents else ""
            badge_orders = f" ｜ 📋 【{len(key_regulations)} 部法規命令】" if key_regulations else ""
            badge_rulings = f" ｜ 📜 【{len(admin_rulings)} 筆主管函釋】" if admin_rulings else ""
            badge_legis = f" ｜ 🕰️ 【{total_amends_display} 次修法對照】" if total_amends_display > 0 else ""
            badge_notes = f" ｜ 📝 【精準命中 {len(notes)} 份個人筆記】" if notes else ""

            with st.expander(f"📖 【{lname} {ano}】{badge_amend}{badge_prec}{badge_orders}{badge_rulings}{badge_legis}{badge_notes}", expanded=(idx < 2 or art.get("is_latest_amendment"))):
                if art.get("is_latest_amendment"):
                    st.success(f"🆕 **此條文為立法院最新三讀通過並經總統府公布之修正條文！** (施行日期：{art.get('modified_date', '最新公布')})")
                    if art.get("amendment_reason"):
                        st.markdown(f"🏛️ **官方立法理由：** {art.get('amendment_reason')}")
                    if art.get("exam_points"):
                        st.markdown(f"✍️ **國考作答熱點：** {art.get('exam_points')}")
                st.markdown(f"> **📜 條文全文**：\n> {content}")

                tab_prec, tab_orders, tab_rulings, tab_legis, tab_notes, tab_ai = st.tabs([
                    f"🏛️ 權威司法判解 ({len(precedents)} 筆)",
                    f"📋 關聯法規命令與細則 ({len(key_regulations)} 部・點閱全文)",
                    f"📜 主管機關行政函釋 ({len(admin_rulings)} 筆・經濟部/智財局/金管會等)",
                    f"🕰️ 立法理由與歷史條文 ({total_amends_display} 次修法對照)",
                    f"📝 關聯個人讀書筆記 ({len(notes)} 份)",
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
                                    st.session_state["target_summary_case_id"] = p.get("case_id", "")
                                    st.session_state["target_summary_subject"] = lname
                                    st.session_state["m5_sub_mode_idx"] = 3
                                    st.session_state["app_mode"] = mode_options[4]
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
                        st.caption("本機權威判解庫中目前無直接標註此條文之大法庭裁定，可前往【統一法學檢索樞紐】或點擊第 6 個分頁由 AI 進行歷審精選裁判與學說補強。")

                with tab_orders:
                    st.markdown(f"#### 📋 【{lname}】之關聯法規命令、施行法與施行細則（支援逐條點閱與全文瀏覽）")
                    if key_regulations:
                        st.caption(f"已串接行政院及主管部會（經濟部、金管會、智慧財產局、勞動部、法務部）發布之法規命令與細則全文。點擊下方各命令卡片即可展開閱讀完整條文！")
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
                                with btn_col2:
                                    if reg_details and reg_details.get("url"):
                                        st.link_button(f"🌐 前往全國法規資料庫官方查看《{reg_name}》", reg_details["url"])
                    else:
                        st.info("此法規母法目前無直接對應之核心法規命令，或直接以母法本體為規範依據。")
                        
                    # 任意調閱全國 10,452 部行政命令任意法規
                    with st.expander(f"🔍 任意調閱全台 10,452 部其他行政法規命令與施行細則全文 (ChOrder.json)"):
                        all_orders_map = get_chorder_regulations_map()
                        kw_custom_reg = st.text_input(f"輸入想查閱之法規命令或細則名稱（例如：專利法施行細則、公開發行公司、勞工請假...）：", key=f"kw_custom_reg_{idx}")
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

                with tab_rulings:
                    st.markdown(f"#### 📜 【{lname} {ano}】權威主管機關行政函釋庫")
                    st.caption("深度整合 **經濟部商業司**（公司登記/公司法）、**經濟部智慧財產局 TIPO**（專利/商標/著作權）、**金融監督管理委員會**（證期局/銀行局）、**法務部法律字**（民事實體/行政程序法）、**勞動部勞動字**（勞動基準法）等中央主管機關之具拘束力行政指導與解釋令函！")

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
                    if st.button(f"🔄 智慧檢索/爬取此條文主管機關最新函釋（經濟部/智財局/金管會/法務部）", key=f"btn_crawl_ruling_{idx}"):
                        with st.spinner(f"正在連線中央主管機關資料庫與 Gemini 3.x Flash，為【{lname} {ano}】爬取最新行政函釋與解釋令..."):
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

                with tab_notes:
                    if notes:
                        st.markdown(f"#### 📝 個人讀書筆記精準命中清單（共 {len(notes)} 份高相關筆記）")
                        st.caption("系統已依據法典編章架構、條號區間與實體法考點關鍵字嚴格過濾，排除非相關章節：")
                        for n in notes:
                            reason = n.get("match_reason", "考科編章關聯")
                            with st.container():
                                st.markdown(f"**📄 《{n['filename']}》** (`{n.get('size_kb', 0)}` KB)")
                                st.info(f"🎯 **精準命中依據/章節考點**：{reason}")
                                st.markdown("---")
                    else:
                        st.info(f"💡 您的個人讀書筆記庫中，目前無直接對應【{lname} {ano}】之專屬章節筆記。系統已為您嚴格過濾掉其他不相關章節（如身分法、其他各論），確保筆記精準不冗餘。")
                        # 亦提供考生手動查閱全部該法考科筆記之彈性入口
                        raw_notes_for_law = get_article_annotations(law_name=lname, article_no="").get("notes", [])
                        if raw_notes_for_law:
                            with st.expander(f"📂 展開查閱【{lname}】全部筆記目錄（共 {len(raw_notes_for_law)} 份，手動對照）", expanded=False):
                                for rn in raw_notes_for_law[:15]:
                                    st.caption(f"- 📄 《{rn['filename']}》 ({rn.get('size_kb', 0)} KB)")

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
elif app_mode == "📥 手寫筆記蒸餾與 SFT 模型微調大庫":
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
                        if st.button("🔄 同步 Google Drive 最新筆記", key="btn_sync_sft_notes"):
                            with st.spinner("正在同步..."):
                                c = sync_all_drive_notes_to_samsung_notes()
                                st.success(f"同步完成！新增/更新 {c} 份筆記。")
                                st.rerun()
            else:
                st.info("💡 目前 Google Drive 尚無筆記檔案。")
                if st.button("🔄 一鍵自 Google Drive「資源」目錄同步所有法學筆記"):
                    with st.spinner("正在同步..."):
                        c = sync_all_drive_notes_to_samsung_notes()
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
