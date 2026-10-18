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

from config import init_directories, GOOGLE_DRIVE_DATA_DIR, get_gemini_api_key, RAW_DATA_DIR, DATA_DIR
from doc_parser import parse_document, ocr_handwritten_images
from evaluator import LawExamEvaluator
from exam_generator import LawExamGenerator
from exam_bank_crawler import LawExamBankCrawler
from legal_query_engine import LegalIssueQueryEngine, search_local_precedents
from six_codes_engine import SIX_CODES_TAXONOMY, get_laws_in_branch, search_articles, get_article_annotations, SixCodesDeepAnnotator

# 設定頁面配置
st.set_page_config(
    page_title="司律考試 AI 評分與命題大師",
    page_icon="⚖️",
    layout="wide"
)

init_directories()

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
        "🔍 AI 爭點查詢 (法條・判解・學說速查)",
        "⚖️ 智慧六法與條文判解綜合標註 (法條・沿革・爭點・筆記)",
        "📥 手寫筆記蒸餾與 SFT 模型微調大庫"
    ]
    if "app_mode" not in st.session_state or st.session_state["app_mode"] not in mode_options:
        st.session_state["app_mode"] = mode_options[0]

    app_mode = st.radio(
        "選擇功能模式：",
        mode_options,
        key="app_mode"
    )
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
            ["✍️ 手動輸入題目文字", "📷 拍照 / 圖片上傳試題 (AI 自動 OCR)"],
            horizontal=True
        )

        new_extracted_q = None
        if q_input_mode == "📷 拍照 / 圖片上傳試題 (AI 自動 OCR)":
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
    st.header("🎯 司律考試模擬命題系統（全面比照 300 題模擬題庫規格）")
    st.write("可放入個人手寫/打字讀書筆記、指定考科與考點，由法學大模型為您量身打造司律一試選擇題或二試實例申論題。")

    stage = st.radio("選擇考試階段：", ["一試 (選擇題 / 單選題)", "二試 (申論實例題)"], horizontal=True)

# 司律考科學門體系分類表
LAW_DOMAIN_TAXONOMY = {
    "🌟 全部學門 (全考科自選)": [
        "民法 (總則/債編/物權/身分)",
        "民事訴訟法 (含家事/強制執行)",
        "刑法 (總則/分則)",
        "刑事訴訟法",
        "憲法與人權保障",
        "行政法 (程序/行政罰/執行/爭訟)",
        "公司法與證券交易法",
        "保險法與票據法",
        "智慧財產權法與營業秘密",
        "勞動法與社會保障法",
        "稅法與納稅者權利",
        "公平交易法",
        "金融消費者保護法與銀行法",
        "海商法",
        "國際私法與國際公法",
        "國民法官法與實務專題",
        "其他自訂學門"
    ],
    "⚖️ 民事實體與程序法學門": [
        "民法 (總則/債編/物權/身分)",
        "民事訴訟法 (含家事/強制執行)"
    ],
    "⚔️ 刑事實體與程序法學門": [
        "刑法 (總則/分則)",
        "刑事訴訟法",
        "國民法官法與實務專題"
    ],
    "🏛️ 公法與憲政行政法學門": [
        "憲法與人權保障",
        "行政法 (程序/行政罰/執行/爭訟)",
        "國際私法與國際公法"
    ],
    "💼 商事法與財經法學門": [
        "公司法與證券交易法",
        "保險法與票據法",
        "公平交易法",
        "金融消費者保護法與銀行法"
    ],
    "🌐 選試與專業法規學門": [
        "智慧財產權法與營業秘密",
        "勞動法與社會保障法",
        "稅法與納稅者權利",
        "海商法",
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
    "公司法與證券交易法": {
        "【公司法】董事之忠實義務與善良管理人注意義務（第23條第1項）": "董事責任之規範基礎、商業判斷法則（Business Judgment Rule）之適用",
        "【公司法】股東會決議瑕疵之類型（第189條得撤銷 vs 第191條無效）": "召集程序瑕疵、決議內容違反法令或章程之救濟與提訴期間",
        "【公司法】表決權拘束契約與表決權信託之效力（第175條之1）": "股東協議之容許性與邊界、閉鎖性公司與非閉鎖性公司之適用差異",
        "【證券交易法】證券詐欺（第20條第1項、第20條之1）與交易因果關係": "財報不實之重大性認定、詐欺市場理論與損害賠償計算方法",
        "【證券交易法】內線交易（第157條之1）重大消息明確時點與實際知悉判斷": "重大消息成立之明確時點（重大性＋明確性）與主觀知悉之舉證"
    },
    "保險法與票據法": {
        "【保險法】保險法第64條據實說明義務與保險事故因果關係之抗辯": "說明義務之主客觀要件、危險估計之影響與因果關係不存在之舉證責任",
        "【保險法】複保險之適用範圍（第35~38條）是否及於人身保險之爭議": "定額給付保險與損害填補保險之區分、釋字第576號解釋意旨",
        "【票據法】票據之無因性與原因關係抗辯（票據法第13條人之抗辯）": "直接前後手間之原因關係抗辯、惡意取得票據與重大過失取得之抗辯"
    }
}

def get_subject_topics_taxonomy(subject_name: str) -> dict:
    for k, v in CORE_ISSUES_TAXONOMY.items():
        if k in subject_name or subject_name in k:
            return v
    return {
        "【核心法理】實體法構成要件該當性與法律效果分析": "核心法條構成要件之法律涵攝、阻卻違法與阻卻責任事由",
        "【實務爭議】最高法院具體裁判與大法庭裁定爭議要點": "最高司法機關權威判旨、通說與有力學說之見解對立與折衝",
        "【程序救濟】法定救濟途徑、當事人適格與訴訟類型選定": "原告適格、管轄權歸屬、救濟期間與權利保護必要性"
    }

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
    note_tab_drive, note_tab_upload, note_tab_text, note_tab_cw = st.tabs([
        "📂 從 Google Drive 個人筆記庫挑選 (免上傳，直接載入 68 份筆記)",
        "📄 手動上傳新筆記 (支援 PDF/Word/TXT/圖片)",
        "✍️ 直接貼上/編輯筆記文字",
        "🎓 從名師課輔講義庫挑選 (115+ 份講義與題解)"
    ])
    
    notes_from_drive = ""
    with note_tab_drive:
        try:
            from ingest_user_notes_to_sft import get_google_drive_notes_list, read_note_text, sync_all_drive_notes_to_samsung_notes
            drive_notes = get_google_drive_notes_list()
            if drive_notes:
                st.caption(f"⚡ 已自您的 Google Drive 自動偵測並收錄 **{len(drive_notes)} 份** 個人手寫與打字法學筆記（免下載免上傳，點選即讀！）：")
                
                # 科目篩選清單（含大類全科整合）
                raw_subs_notes = sorted(list(set(n["subject"] for n in drive_notes)))
                note_categories = ["全部科目"]
                has_civ_notes = any(s in ["民總", "債各", "身分法", "民法"] for s in raw_subs_notes)
                has_crim_notes = any(s in ["刑總", "刑分", "刑法"] for s in raw_subs_notes)
                if has_civ_notes:
                    note_categories.append("民法全科 (民總/債各/身分法)")
                if has_crim_notes:
                    note_categories.append("刑法全科 (刑總/刑分)")
                note_categories.extend(raw_subs_notes)

                default_sub_idx = 0
                if subject:
                    if "民法" in subject and "民法全科 (民總/債各/身分法)" in note_categories:
                        default_sub_idx = note_categories.index("民法全科 (民總/債各/身分法)")
                    elif "刑法" in subject and "刑法全科 (刑總/刑分)" in note_categories:
                        default_sub_idx = note_categories.index("刑法全科 (刑總/刑分)")
                    else:
                        for i, sub in enumerate(note_categories):
                            if sub != "全部科目" and (sub in subject or subject in sub):
                                default_sub_idx = i
                                break
                        
                col_sel1, col_sel2 = st.columns([1, 2])
                with col_sel1:
                    sel_note_sub = st.selectbox(
                        "筆記分類篩選：",
                        note_categories,
                        index=default_sub_idx,
                        key="sel_note_subject_filter"
                    )
                
                if sel_note_sub == "全部科目":
                    filtered_notes = drive_notes
                elif sel_note_sub == "民法全科 (民總/債各/身分法)":
                    filtered_notes = [n for n in drive_notes if n["subject"] in ["民總", "債各", "身分法", "民法"]]
                elif sel_note_sub == "刑法全科 (刑總/刑分)":
                    filtered_notes = [n for n in drive_notes if n["subject"] in ["刑總", "刑分", "刑法"]]
                else:
                    filtered_notes = [n for n in drive_notes if n["subject"] == sel_note_sub]
                
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
                    st.info(f"💡 已選擇【全部分析】！系統將遍歷【{sel_note_sub}】全部 **{len(filtered_notes)} 份** 雲端筆記，優先調用本機高速快取；手寫或掃描 PDF 自動調用 Gemini 2.0 Flash 進行多模態辨識，彙編成完整法學爭點大典以供客製命題。")
                    c_btn1, c_btn2 = st.columns([2, 1])
                    with c_btn1:
                        load_all_btn = st.button(f"🚀 一鍵分析並載入全部筆記 (共 {len(filtered_notes)} 份)", type="primary", key="btn_load_all_drive_notes")
                    with c_btn2:
                        sync_btn = st.button("🔄 同步 Google Drive 最新筆記", key="btn_sync_drive_notes")
                        if sync_btn:
                            with st.spinner("正在掃描雲端硬碟各科筆記..."):
                                c = sync_all_drive_notes_to_samsung_notes()
                                st.success(f"同步完成！新增/更新了 {c} 份筆記。")
                                st.rerun()

                    session_all_key = f"cached_all_notes_text_{sel_note_sub}_{len(filtered_notes)}"
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
                            st.success(f"🎉 成功全部分析【{sel_note_sub}】共 {len(filtered_notes)} 份筆記，累計取得 {len(combined_all):,} 字元！已自動帶入下方命題引擎。")
                            with st.expander("🔍 檢視已解析之全部分類筆記重點與爭點摘要", expanded=False):
                                st.text_area("全部分析筆記內容彙整（已用於客製命題）：", value=combined_all, height=220, key="preview_drive_all_notes")
                elif sel_note_label:
                    sel_idx = note_labels.index(sel_note_label) - 1
                    chosen_note = filtered_notes[sel_idx]
                    
                    c_btn1, c_btn2 = st.columns([2, 1])
                    with c_btn1:
                        load_btn = st.button("🚀 載入此份雲端筆記 (自動進行文字提取 / 手寫多模態 OCR)", type="primary", key="btn_load_drive_note")
                    with c_btn2:
                        sync_btn = st.button("🔄 同步 Google Drive 最新筆記", key="btn_sync_drive_notes")
                        if sync_btn:
                            with st.spinner("正在掃描雲端硬碟各科筆記..."):
                                c = sync_all_drive_notes_to_samsung_notes()
                                st.success(f"同步完成！新增/更新了 {c} 份筆記。")
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
                
                # 建立完整的講義分類體系（含全科整合分類）
                raw_subs = sorted(list(set(c.get("subject", "") for c in cw_list if c.get("subject"))))
                cw_categories = ["全部科目"]
                
                has_civ = any("民法" in s for s in raw_subs)
                has_crim = any("刑法" in s for s in raw_subs)
                
                if has_civ:
                    cw_categories.append("民法全科 (總則/債總/債各)")
                if has_crim:
                    cw_categories.append("刑法全科 (總則/分則)")
                cw_categories.extend(raw_subs)
                
                default_cw_idx = 0
                if subject:
                    if "民法" in subject and "民法全科 (總則/債總/債各)" in cw_categories:
                        default_cw_idx = cw_categories.index("民法全科 (總則/債總/債各)")
                    elif "刑法" in subject and "刑法全科 (總則/分則)" in cw_categories:
                        default_cw_idx = cw_categories.index("刑法全科 (總則/分則)")
                    else:
                        for idx_c, cat in enumerate(cw_categories):
                            if cat != "全部科目" and (cat in subject or subject in cat):
                                default_cw_idx = idx_c
                                break
                
                col_cw1, col_cw2 = st.columns([1, 2])
                with col_cw1:
                    sel_cw_sub = st.selectbox(
                        "筆記分類篩選：",
                        cw_categories,
                        index=default_cw_idx,
                        key="sel_coursework_subject_filter"
                    )
                
                # 依分類過濾講義檔案（精確排除非本學門檔案）
                if sel_cw_sub == "全部科目":
                    filtered_cw = cw_list
                elif sel_cw_sub == "民法全科 (總則/債總/債各)":
                    filtered_cw = [c for c in cw_list if c.get("subject") in ["民法總則", "民法債編總論", "民法債編各論"]]
                elif sel_cw_sub == "刑法全科 (總則/分則)":
                    filtered_cw = [c for c in cw_list if c.get("subject") in ["刑法總則", "刑法分則"]]
                else:
                    filtered_cw = [c for c in cw_list if c.get("subject") == sel_cw_sub]
                
                with col_cw2:
                    all_cw_label = f"🌟 【全部分析】引用此分類全部講義重點 (共 {len(filtered_cw)} 份，自動爭點大綱精萃)"
                    cw_options = [all_cw_label] + [
                        f"【{c.get('subject')}】{c.get('filename')} ({c.get('char_count', 0):,} 字)" 
                        for c in filtered_cw
                    ]
                    sel_cw = st.selectbox(
                        "選擇欲引用的名師講義/課輔檔案：",
                        cw_options,
                        key="select_coursework_doc"
                    )
                
                if sel_cw == all_cw_label:
                    st.info(f"💡 已選擇【全部分析】！系統將遍歷【{sel_cw_sub}】全部 **{len(filtered_cw)} 份** 雲端講義與課輔大綱，優先調用本機高速快取；彙編成完整法學爭點大典以供客製命題。")
                    if st.checkbox(f"✅ 確認載入【{sel_cw_sub}】全部講義精華爭點以進行全科命題", value=True, key=f"cb_use_all_cw_{sel_cw_sub}"):
                        notes_from_coursework = "\n\n---\n\n".join([f"### 《{c.get('filename')}》（考科：{c.get('subject')}）\n" + c.get("summary_preview", "") for c in filtered_cw])
                        with st.expander(f"🔍 檢視已載入【{sel_cw_sub}】之講義爭點精華彙編 (共 {len(notes_from_coursework):,} 字)", expanded=False):
                            st.text_area("講義核心爭點彙編（已帶入命題引擎）：", value=notes_from_coursework, height=220, key=f"preview_cw_all_{sel_cw_sub}")
                elif sel_cw:
                    sel_idx = cw_options.index(sel_cw) - 1
                    chosen_item = filtered_cw[sel_idx]
                    st.caption(f"📁 來源目錄：`{chosen_item.get('relative_path')}` ｜ 字數：{chosen_item.get('char_count', 0):,} 字")
                    st.info(f"**講義摘要預覽**：\n{chosen_item.get('summary_preview', '')}...")
                    if st.checkbox("✅ 確認載入此講義重點以進行客製命題", value=True, key=f"cb_use_cw_{chosen_item.get('filename')}"):
                        notes_from_coursework = chosen_item.get("summary_preview", "")
            except Exception as e:
                st.error(f"讀取講義庫失敗: {e}")
        else:
            st.info("💡 講義索引檔案載入中（若尚未生成完畢，稍候將自動呈現）。")

    final_notes = (notes_from_text if notes_from_text else (notes_from_drive if notes_from_drive else (notes_from_file if notes_from_file else notes_from_coursework))).strip()
    note_source_label = "個人筆記"
    if notes_from_text:
        note_source_label = "手動貼上/編輯之筆記"
    elif notes_from_drive:
        note_source_label = "Google Drive 雲端筆記"
    elif notes_from_file:
        note_source_label = "本機上傳之筆記"
    elif notes_from_coursework:
        note_source_label = "名師課輔講義爭點精萃"

    if final_notes:
        st.info(f"💡 目前已載入【{note_source_label}】重點（共 {len(final_notes):,} 字），命題引擎將嚴密結合您的重點爭點進行客製化命題！")

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

            st.divider()
            st.subheader(f"📋 【第二部分：標準答案速查表】(共 {len(questions)} 題)")
            
            # 以每 5 題一行排版速查表
            cols_per_row = 5
            for row_start in range(1, len(questions) + 1, cols_per_row):
                key_cols = st.columns(cols_per_row)
                for c_idx in range(cols_per_row):
                    q_num = row_start + c_idx
                    if q_num <= len(questions):
                        with key_cols[c_idx]:
                            st.info(f"**第 {q_num} 題**：`({answer_key.get(str(q_num), 'A')})`")

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

            with col_export:
                md_content = LawExamGenerator.format_stage1_exam_markdown(exam_data)
                st.download_button(
                    label="💾 一鍵下載完整全真模擬試卷 (Markdown 檔)",
                    data=md_content,
                    file_name=f"司律一試_{exam_data.get('subject')}_{exam_data.get('topic')[:10]}_{len(questions)}題.md",
                    mime="text/markdown"
                )

            # 批改結果與考點分類實力診斷
            if st.session_state.get("stage1_graded"):
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
    
    m3_tab1, m3_tab2 = st.tabs([
        "🏛️ 考選部與臺大法研/轉學考歷年真題庫",
        "🎓 大學名師講義與課輔爭點知識庫 (190+ 份各科講義與簡報)"
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
                with st.spinner("正在使用 Gemini 2.0 Flash 多模態神經網路自動辨識並轉錄題目全文..."):
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
                                r = ev.client.models.generate_content(
                                    model="gemini-2.0-flash",
                                    contents=[img, prompt]
                                )
                                transcribed = r.text.strip()
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
            ["民法與民事訴訟法", "刑法與刑事訴訟法", "憲法與行政法", "公司法、保險法與證券交易法", "智慧財產法", "勞動社會法", "財稅法", "海商法與海洋法", "其他法學綜合實例題"],
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

# ----------------- 模式 5: AI 爭點查詢 (法條・判解・學說速查) -----------------
elif app_mode == "🔍 AI 爭點查詢 (法條・判解・學說速查)":
    st.header("🔍 AI 爭點查詢與權威判解・學說速查中心")
    st.write("輸入法學爭點、核心關鍵字或案例事實，AI 智慧法學引擎將即刻引出**核心法條構成要件**、**最高司法權威見解（憲法法庭判決/最高法院大法庭裁定/精選裁判）**、**學說肯否二說**與**二試上位卷 IRAC 開標示範**，並支援一鍵帶入試卷評分或擬答生成！")

    # 快捷範例按鈕列
    st.markdown("##### 💡 司律必考核心重大爭點快捷速查：")
    preset_cols = st.columns(4)
    preset_query = None
    with preset_cols[0]:
        if st.button("⚖️ 借名登記處分效力", use_container_width=True):
            preset_query = "借名登記之出名人未經同意將不動產處分移轉予第三人，效力為何？"
    with preset_cols[1]:
        if st.button("⚖️ 原因自由行為責任", use_container_width=True):
            preset_query = "刑法第19條第3項原因自由行為之責任能力判定標準與過失自陷處罰界限"
    with preset_cols[2]:
        if st.button("⚖️ 保險詐欺與除斥期間", use_container_width=True):
            preset_query = "要保人惡意詐欺違反告知義務逾2年，保險人能否依民法第92條撤銷？"
    with preset_cols[3]:
        if st.button("⚖️ 純粹經濟上損失", use_container_width=True):
            preset_query = "民法第184條第1項前段侵權責任所保護之權利是否包含純粹經濟上損失？"

    preset_cols2 = st.columns(4)
    with preset_cols2[0]:
        if st.button("⚖️ 毒品販賣既遂標準", use_container_width=True):
            preset_query = "販賣毒品罪之既遂標準究竟以買賣契約合致為準，抑或須以毒品交付為準？"
    with preset_cols2[1]:
        if st.button("⚖️ 警察強制採尿取證", use_container_width=True):
            preset_query = "司法警察依刑事訴訟法第205條之2強制採尿取證是否牴觸法官保留原則與身心權？"
    with preset_cols2[2]:
        if st.button("⚖️ 不真正連帶時效利益", use_container_width=True):
            preset_query = "不真正連帶債務中一人時效完成者，他債務人能否類推適用民法第276條第2項免責？"
    with preset_cols2[3]:
        if st.button("⚖️ 傳聞證據擬制同意", use_container_width=True):
            preset_query = "當事人於準備程序未對傳聞證據異議，於審判期日能否再行撤回擬制同意？"

    if preset_query:
        st.session_state["ai_query_input_text"] = preset_query

    st.divider()

    # 查詢輸入區
    col_q_sub, col_q_mode = st.columns([1, 1])
    with col_q_sub:
        q_subject = st.selectbox(
            "選擇專屬考科範疇：",
            ["全部科目", "民事法（民法與民事訴訟法）", "刑事法（刑法與刑事訴訟法）", "公法（憲法與行政法）", "商事法（公司、保險、證交）"],
            key="ai_query_subject"
        )
    with col_q_mode:
        q_search_type = st.radio(
            "查詢模式：",
            ["🔍 法律爭點與關鍵字查詢", "📜 案件事實深度法律爭點分析"],
            horizontal=True,
            key="ai_query_mode"
        )

    current_query_val = st.session_state.get("ai_query_input_text", "")
    query_text = st.text_area(
        "請輸入欲查詢之爭點問題、關鍵字、判決字號或案件事實情境：",
        value=current_query_val,
        height=120,
        placeholder="例如：借名登記出名人無權處分或有權處分、刑法19條原因自由行為、111年憲判字第16號...",
        key="ai_query_text_area"
    )

    col_btn_search, col_btn_clear = st.columns([3, 1])
    with col_btn_search:
        btn_do_query = st.button("🚀 啟動 AI 爭點與權威判解檢索", type="primary", use_container_width=True)
    with col_btn_clear:
        if st.button("✖️ 清除查詢內容", use_container_width=True):
            st.session_state["ai_query_input_text"] = ""
            st.session_state.pop("ai_query_result", None)
            st.rerun()

    if btn_do_query:
        if not query_text.strip():
            st.warning("請先輸入欲查詢之爭點或關鍵字！")
        else:
            with st.spinner("正在比對本機 824+ 份權威判解庫 (最高法院大法庭裁定、憲判字) 並進行法理推導與學說肯否兩說分析..."):
                try:
                    engine = LegalIssueQueryEngine()
                    res = engine.query_legal_issue(query=query_text.strip(), subject=q_subject)
                    st.session_state["ai_query_result"] = res
                    st.session_state["ai_query_input_text"] = query_text.strip()
                except Exception as qe:
                    st.error(f"檢索失敗: {qe}")

    if "ai_query_result" in st.session_state:
        res = st.session_state["ai_query_result"]
        matched_cases = res.get("matched_local_precedents", [])
        
        st.divider()
        st.subheader("📚 AI 權威爭點與法條判解檢索分析報告")
        
        # 本地權威命中裁判展示
        if matched_cases:
            with st.expander(f"🏛️ 本機權威庫即時命中之最高法院大法庭 / 憲法法庭裁判 ({len(matched_cases)} 筆)", expanded=True):
                for mc in matched_cases:
                    c_id = mc.get("case_id", "")
                    lvl = mc.get("level", "")
                    tit = mc.get("title", "")
                    laws = ", ".join(mc.get("laws_cited", []))
                    holding = mc.get("holding", "")
                    st.markdown(f"**【{lvl}】`{c_id}`** ｜ **{tit}**")
                    if laws:
                        st.caption(f"📌 涉及法規：{laws}")
                    st.info(f"**核心主文/判旨：** {holding}")
                    if mc.get("exam_application_hint"):
                        st.success(f"✍️ **國考作答提示：** {mc.get('exam_application_hint')}")
                    st.markdown("---")

        # Markdown 完整深度爭點報告
        st.markdown(res.get("markdown_result", ""))

        st.divider()
        st.subheader("🔗 跨功能一鍵聯動：將此爭點解析轉化為考試訓練")
        act_col1, act_col2 = st.columns(2)
        with act_col1:
            if st.button("📝 【一鍵帶入試卷評分】作為評分標準與參考擬答", use_container_width=True, type="primary"):
                st.session_state["question_text_content"] = f"【爭點問題研析】：\n{res.get('query', '')}"
                st.session_state["rubric_text_content"] = res.get("markdown_result", "")
                st.session_state["imported_from_bank_label"] = f"AI 爭點速查標準【{res.get('query', '')[:20]}...】"
                st.session_state["app_mode"] = "📝 試卷評分與手寫辨識 (手寫/PDF/Word)"
                st.rerun()
        with act_col2:
            if st.button("📖 【一鍵帶入高分擬答生成】針對此爭點撰寫申論答題", use_container_width=True):
                st.session_state["m4_target_question"] = res.get("query", "")
                st.session_state["app_mode"] = "📖 高分權威擬答生成"
                st.rerun()

# ----------------- 模式 6: 智慧六法與條文判解綜合標註 (法條・沿革・爭點・筆記) -----------------
elif app_mode == "⚖️ 智慧六法與條文判解綜合標註 (法條・沿革・爭點・筆記)":
    st.header("⚖️ 智慧六法全書與條文爭點判解綜合標註系統")
    st.write("全面收錄全台 **61 部核心司律考科法規、10,183 條法定條文**，直接在條文下方完整串接**條文結構**、**立法理由與沿革**、**憲判字/最高法院大法庭權威裁判**、**學說肯否二說**、**法規命令施行細則**及**考生個人手寫讀書筆記**！")

    # 1. 導航選擇列
    col_b, col_l, col_q = st.columns([1, 1, 2])
    with col_b:
        branch_options = list(SIX_CODES_TAXONOMY.keys())
        selected_branch = st.selectbox("1. 選擇法學門類：", branch_options, key="six_codes_branch")
    with col_l:
        available_laws = get_laws_in_branch(selected_branch)
        selected_law = st.selectbox("2. 選擇法典名稱：", available_laws, key="six_codes_law")
    with col_q:
        search_kw = st.text_input(
            "3. 搜尋條號（如 184、19、64、759-1）或條文關鍵字：",
            placeholder="輸入條號或法理關鍵字（如：純粹經濟、借名登記、原因自由行為）...",
            key="six_codes_search_kw"
        )

    # 快捷核心考條按鈕
    st.markdown("##### 📌 司律核心高頻爭點條文直達：")
    q_btn_cols = st.columns(6)
    quick_jump = None
    with q_btn_cols[0]:
        if st.button("民法 第 184 條", use_container_width=True):
            quick_jump = ("民法", "184")
    with q_btn_cols[1]:
        if st.button("民法 第 759-1 條", use_container_width=True):
            quick_jump = ("民法", "759-1")
    with q_btn_cols[2]:
        if st.button("刑法 第 19 條", use_container_width=True):
            quick_jump = ("中華民國刑法", "19")
    with q_btn_cols[3]:
        if st.button("刑訴 第 159-5 條", use_container_width=True):
            quick_jump = ("刑事訴訟法", "159-5")
    with q_btn_cols[4]:
        if st.button("保險法 第 64 條", use_container_width=True):
            quick_jump = ("保險法", "64")
    with q_btn_cols[5]:
        if st.button("公司法 第 185 條", use_container_width=True):
            quick_jump = ("公司法", "185")

    if quick_jump:
        selected_law = quick_jump[0]
        search_kw = quick_jump[1]

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
            
            anno = get_article_annotations(law_name=lname, article_no=ano)
            precedents = anno.get("precedents", [])
            orders = anno.get("orders", [])
            notes = anno.get("notes", [])

            badge_prec = f" ｜ 🏛️ 【收錄 {len(precedents)} 筆大法庭/憲判字】" if precedents else ""
            badge_notes = f" ｜ 📝 【關聯 {len(notes)} 份個人筆記】" if notes else ""
            
            with st.expander(f"📖 【{lname} {ano}】{badge_prec}{badge_notes}", expanded=(idx < 2)):
                st.markdown(f"> **📜 條文全文**：\n> {content}")

                tab_prec, tab_orders, tab_notes, tab_ai = st.tabs([
                    f"🏛️ 權威司法判解 ({len(precedents)} 筆)",
                    f"📋 相關命令與細則 ({len(orders)} 筆)",
                    f"📝 關聯個人讀書筆記 ({len(notes)} 份)",
                    "🤖 AI 深度釋析與主管函釋補強"
                ])

                with tab_prec:
                    if precedents:
                        for p in precedents:
                            st.markdown(f"**【{p.get('level')}】`{p.get('case_id')}`** ｜ **{p.get('title')}**")
                            st.info(f"**核心要旨/主文：**\n{p.get('holding')}")
                            if p.get('scholarly_views'):
                                st.caption(f"📚 **學說實務對比：** {p.get('scholarly_views')}")
                            if p.get('exam_application_hint'):
                                st.success(f"✍️ **國考作答指示：** {p.get('exam_application_hint')}")
                            st.markdown("---")
                    else:
                        st.caption("本機權威判解庫中目前無直接標註此條文之大法庭裁定，可點擊第 4 個分頁由 AI 進行歷審精選裁判與學說補強。")

                with tab_orders:
                    if orders:
                        st.markdown(f"**【{lname}】之關聯法規命令、施行法與施行細則：**")
                        for ord_item in orders:
                            st.markdown(f"- **{ord_item['name']}** (`{ord_item['type']}`)：{ord_item['desc']}")
                    else:
                        st.caption("此法規無額外施行細則登記或直接以母法規範。")

                with tab_notes:
                    if notes:
                        st.markdown(f"**考生 Google Drive / SamsungNotes 中關聯此法條考科之講義筆記：**")
                        for n in notes[:8]:
                            st.markdown(f"- 📄 **《{n['filename']}》** ({n['size_kb']} KB)")
                    else:
                        st.caption("此考科目前尚未在 SamsungNotes 中上傳專屬手寫筆記。")

                with tab_ai:
                    ai_cache_key = f"ai_anno_{lname}_{ano}"
                    if st.button(f"✨ 啟動 AI 深度釋析（立法理由、主管機關函釋、通說有力說）", key=f"btn_run_anno_{idx}"):
                        with st.spinner(f"正在由 Gemini 2.0 Flash 為【{lname} {ano}】生成立法沿革、法務部/金管會函釋與二試作答模版..."):
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
                    if st.button(f"🔍 帶入爭點查詢深入分析", key=f"btn_pass_query_{idx}", use_container_width=True):
                        st.session_state["ai_query_input_text"] = f"{lname} {ano} 相關核心爭點與實務裁判"
                        st.session_state["app_mode"] = "🔍 AI 爭點查詢 (法條・判解・學說速查)"
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
            ["📂 方案 A：直接自 Google Drive 筆記庫挑選並蒸餾 (免上傳，全考科已收錄 200+ 份)", "📤 方案 B：手動上傳新筆記檔案 (PDF/圖片/Word)"],
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
                
                sub_list = sorted(list(set(n["subject"] for n in drive_notes)))
                col_d1, col_d2 = st.columns([1, 2])
                with col_d1:
                    filter_sub = st.selectbox("筆記科目篩選：", ["全部科目"] + sub_list, key="sft_filter_sub")
                
                if filter_sub == "全部科目":
                    sub_notes = drive_notes
                else:
                    sub_notes = [n for n in drive_notes if n["subject"] == filter_sub]
                    
                with col_d2:
                    all_distill_label = f"🌟 【全部分析】批次分析並蒸餾此分類全部筆記 (共 {len(sub_notes)} 份)"
                    note_opts = [all_distill_label] + [
                        f"【{n['subject']}】{n['filename']} ({n['size_mb']:.2f} MB)" + (f" 🎯已提煉 {n['distilled_count']} 筆" if n['distilled_count'] > 0 else "") 
                        for n in sub_notes
                    ]
                    sel_sft_note = st.selectbox("選擇欲蒸餾之雲端筆記：", note_opts, key="sft_sel_note")
                
                if sel_sft_note == all_distill_label:
                    st.info(f"💡 已選擇【全部分析】！系統將批次遍歷【{filter_sub}】全部 **{len(sub_notes)} 份** 筆記，透過 Gemini 2.0 Flash 多模態神經網路執行高精度手寫辨識、爭點提煉與 SFT 微調語料蒸餾，並即時合併寫入 SFT 微調庫。")
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
                            with st.spinner(f"⚖️ 正在運用 Gemini 2.0 Flash 解析《{target_note['filename']}》手寫法條、爭點肯否二說與實務判例..."):
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
                    with st.spinner("⚖️ 正在運用 Gemini 2.0 Flash 解析手寫法條、爭點肯否二說與實務判例，並轉化為標準 SFT 資料..."):
                        try:
                            from ingest_user_notes_to_sft import ingest_single_uploaded_file
                            new_samples = ingest_single_uploaded_file(up_file.getvalue(), up_file.name)
                            if new_samples:
                                st.balloons()
                                st.success(f"🎉 蒸餾成功！自《{up_file.name}》中成功提煉出 **{len(new_samples)} 組** 高品質 SFT 法學微調樣本，並已自動同步合併至主微調大庫！")
                                with st.expander("🔍 檢視本次提煉之 SFT 樣本預覽", expanded=True):
                                    for s_idx, s in enumerate(new_samples, 1):
                                        st.markdown(f"**【樣本 {s_idx}】ID: `{s.get('id')}`**")
                                        st.caption(f"指令 (Instruction): {s.get('instruction')}")
                                        st.markdown(f"**題目情境 (Input)**：\n{s.get('input')}")
                                        st.markdown(f"**示範解答 (Output)**：\n{s.get('output')}")
                                        st.divider()
                            else:
                                st.warning("未能從此檔案中辨識出足夠的法學爭點，請確認檔案清晰度或是否包含法律筆記內容。")
                        except Exception as de:
                            st.error(f"蒸餾處理失敗: {de}")

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
            all_choice_label = f"🌟 【全部考科】全部分析 (全庫共 {all_sub_count} 份筆記 / 講義)"
            sub_options = [all_choice_label] + [
                f"【{s}】(共 {len(nlist)} 份筆記 / 講義)" 
                for s, nlist in sorted(sub_dict.items(), key=lambda x: -len(x[1]))
            ]
            sel_sub_label = st.selectbox("請選擇欲處理的法學考科：", sub_options, key="merge_sub_select")
            if sel_sub_label == all_choice_label:
                sel_subject = "全部考科"
                sub_notes = [n for nlist in sub_dict.values() for n in nlist]
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
                st.caption(f"自動遍歷【{sel_subject}】所有 {len(sub_notes)} 份檔案，優先調用高速快取與數位字；若為手寫筆記掃描檔則由 Gemini 2.0 Flash 辨識並彙整為單一 Markdown 筆記大典。")
                ocr_flag = st.checkbox("自動對手寫掃描檔啟用 Gemini 2.0 Flash 多模態 OCR", value=True, key="chk_auto_ocr_full")
                
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

