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

from config import init_directories, GOOGLE_DRIVE_DATA_DIR, get_gemini_api_key, RAW_DATA_DIR
from doc_parser import parse_document, ocr_handwritten_images
from evaluator import LawExamEvaluator
from exam_generator import LawExamGenerator
from exam_bank_crawler import LawExamBankCrawler

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
    app_mode = st.radio(
        "選擇功能模式：",
        [
            "📝 試卷評分與手寫辨識 (手寫/PDF/Word)",
            "🎯 司律模擬出題 (一試/二試 & 手寫筆記客製命題)",
            "📚 歷年真題庫檢索與模擬演練 (法研所 / 轉學考 / 司法官律師 / 司法特考)",
            "📖 高分權威擬答生成"
        ]
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
        question_text = st.text_area(
            "請輸入考試題目內容：",
            height=200,
            placeholder="例如：甲向乙借款新臺幣1000萬元，並將其所有之A屋設定普通抵押權予乙以供擔保..."
        )
        rubric_text = st.text_area(
            "評分標準 / 參考擬答 (選填，留空則由 AI 自律法學知識庫推導)：",
            height=120,
            placeholder="可貼入補習班爭點、評分大綱或最高法院判決字號..."
        )

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

    col_sub1, col_sub2 = st.columns(2)
    with col_sub1:
        subjects_list = [
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
        ]
        subject_choice = st.selectbox("考試科目：", subjects_list)
        if subject_choice == "其他自訂學門":
            subject = st.text_input("請輸入自訂科目名稱：", value="民事法學")
        else:
            subject = subject_choice.split(" ")[0]

    with col_sub2:
        topic = st.text_input("出題核心主題/考點（若有上傳筆記亦可留空或輸入重點關鍵字）：", placeholder="例如：借名登記、侵權純經濟損失、原因自由行為...")

    st.markdown("#### 📚 放入我的個人筆記 / 爭點講義（支援手寫 PDF 與圖片）")
    note_tab1, note_tab2 = st.tabs(["📄 上傳筆記檔案 (手寫/打字 PDF、Word、圖片)", "✍️ 直接貼上/編輯筆記文字"])
    
    notes_from_file = ""
    with note_tab1:
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
    with note_tab2:
        default_val = notes_from_file if notes_from_file else ""
        notes_from_text = st.text_area(
            "直接貼上或補充法學筆記、實務見解或考點爭議重點：",
            value=default_val,
            height=140,
            placeholder="例如：貼上王澤鑑老師權益歸屬說論點、最高法院108台上大字1719號裁定重點摘要..."
        )

    final_notes = (notes_from_text if notes_from_text else notes_from_file).strip()
    if final_notes:
        st.info(f"💡 目前已載入個人筆記重點（共 {len(final_notes):,} 字），命題引擎將嚴密結合您的筆記重點進行客製化命題！")

    if stage == "一試 (選擇題 / 單選題)":
        st.markdown("#### ⚙️ 一試出題參數設定（比照 300 題模擬題庫規格）")
        qcol1, qcol2 = st.columns(2)
        with qcol1:
            q_mode = st.selectbox(
                "題型結構模式：",
                ["標準單選題 (案例情境盲測)", "綜合案例實事實務題組題 (跨子題)", "全真綜合模考卷 (混合題型)"]
            )
        with qcol2:
            q_count_option = st.selectbox(
                "出題題數：",
                ["5 題 (隨堂測驗)", "10 題 (標準單元測)", "15 題 (強化題組)", "20 題 (大型模考卷)", "30 題 (全真模擬題庫)", "自訂題數"]
            )
            if q_count_option == "自訂題數":
                q_count = st.number_input("請輸入自訂題數 (1~50 題)：", min_value=1, max_value=50, value=5)
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

            st.divider()
            st.subheader(f"📝 【第一部分：全真試題區】（盲測情境實力）")
            st.caption("提示：題幹已全面隱匿法條條號與裁判字號，請直接依具體事實判斷最正確選項。")

            user_answers = {}
            for q in questions:
                q_no = q.get("question_no")
                cat = q.get("category", "")
                cat_display = f" `{cat}`" if cat else ""
                
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
                    score = 0
                    for q_num_str, correct_ans in answer_key.items():
                        if user_answers.get(q_num_str) == correct_ans:
                            score += 1
                    total_q = len(questions)
                    pct = int(score / total_q * 100) if total_q > 0 else 0
                    st.balloons()
                    st.success(f"測驗批改完成！答對：{score} / {total_q} 題（得分率：{pct}%）")

            with col_export:
                md_content = LawExamGenerator.format_stage1_exam_markdown(exam_data)
                st.download_button(
                    label="💾 一鍵下載完整全真模擬試卷 (Markdown 檔)",
                    data=md_content,
                    file_name=f"司律一試_{exam_data.get('subject')}_{exam_data.get('topic')[:10]}_{len(questions)}題.md",
                    mime="text/markdown"
                )

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
            if st.button("🏆 生成榜首級示範擬答 (IRAC 三段論法)", type="primary"):
                with st.spinner("榜首法學講座名師正在撰寫嚴謹三段論法擬答..."):
                    gen = LawExamGenerator()
                    ans = gen.generate_model_answer(question=full_q_text, subject=subject)
                    st.markdown("### 🏆 閱卷高分示範擬答：")
                    st.markdown(ans)

# ----------------- 模式 3: 歷年真題庫檢索 -----------------
elif app_mode == "📚 歷年真題庫檢索與模擬演練 (法研所 / 轉學考 / 司法官律師 / 司法特考)":
    st.header("📚 全台法學歷年真題庫檢索與模擬演練")
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

                # 榜首擬答與題型演練按鈕
                bcol1, bcol2 = st.columns(2)
                with bcol1:
                    if st.button(f"💡 針對本題生成榜首級高分示範擬答 (IRAC)", key=f"ans_btn_{e_id}"):
                        with st.spinner("法學大模型正在為本真題撰寫上位卷完美擬答..."):
                            gen = LawExamGenerator()
                            model_ans = gen.generate_model_answer(question=text, subject=subj)
                            st.markdown("### 🏆 示範擬答全文：")
                            st.markdown(model_ans)

                with bcol2:
                    if st.button(f"🎯 依此真題進行題型演繹與變形出題", key=f"remake_btn_{e_id}"):
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

# ----------------- 模式 4: 擬答生成 -----------------
elif app_mode == "📖 高分權威擬答生成":
    st.header("📖 司律二試 - 高分示範擬答生成器")
    st.write("針對二試爭議題目，自動撰寫具備榜首水準的開標、大前提、實務學說對比與事實涵攝完美擬答。")

    target_q = st.text_area(
        "請貼上申論題題目：",
        height=200,
        placeholder="請貼入完整的二試題目..."
    )

    if st.button("✨ 生成極致高分擬答", type="primary"):
        if not target_q.strip():
            st.warning("請先輸入題目！")
        else:
            with st.spinner("法學專家正在撰寫嚴謹三段論法擬答..."):
                try:
                    gen = LawExamGenerator()
                    ans = gen.generate_model_answer(question=target_q)
                    st.markdown(ans)
                except Exception as e:
                    st.error(f"出題失敗: {e}")
