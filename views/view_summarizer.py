import streamlit as st
import os
import json
import re
import time
from config import DATA_DIR
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
from views.constants import MODE_EVAL, MODE_ANS

def render_mode_summarizer():
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
                st.session_state["app_mode"] = MODE_EVAL
                st.rerun()
        with s_act3:
            if st.button("📖 帶入高分擬答生成", use_container_width=True, key="btn_sum_to_ans"):
                m4_q_text = f"請就【{active_title}】所涉及之核心法律爭點，依 IRAC 架構撰寫標準上位卷擬答。"
                st.session_state["m4_target_question"] = m4_q_text
                st.session_state["m4_text_area_input"] = m4_q_text
                st.session_state["app_mode"] = MODE_ANS
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


