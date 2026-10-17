"""
司律手寫試卷評分、出題與擬答系統 - Web 圖形介面 (Streamlit)
"""
import streamlit as st
from PIL import Image
from config import init_directories, GOOGLE_DRIVE_DATA_DIR, get_gemini_api_key
from doc_parser import parse_document
from evaluator import LawExamEvaluator
from exam_generator import LawExamGenerator

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
        ["📝 試卷評分與手寫辨識 (手寫/PDF/Word)", "🎯 司律模擬出題 (一試/二試)", "📖 高分權威擬答生成"]
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
        st.success("🟢 AI 核心引擎已就緒 (Gemini 2.0 Flash)")
    st.info("支援檔案：手寫照片 (JPG/PNG)、掃描或文字 PDF、Word (.docx)")

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
            with st.spinner("⚖️ 正在運用 Gemini 2.0 Flash 進行手寫辨識、三段論法邏輯檢驗與爭點比對..."):
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
elif app_mode == "🎯 司律模擬出題 (一試/二試)":
    st.header("🎯 司律考試模擬命題系統（支援個人筆記出題）")
    st.write("可放入個人讀書筆記、指定考科與考點，由法學大模型為您量身打造司律一試選擇題或二試實例申論題。")

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
        topic = st.text_input("出題核心主題/考點（若有筆記亦可留空或輸入重點關鍵字）：", placeholder="例如：借名登記、侵權純經濟損失、原因自由行為...")

    st.markdown("#### 📚 放入我的個人筆記 / 爭點講義（選填）")
    note_tab1, note_tab2 = st.tabs(["📄 上傳筆記檔案 (PDF / Word / TXT / MD)", "✍️ 直接貼上筆記文字"])
    
    notes_from_file = ""
    with note_tab1:
        uploaded_note_file = st.file_uploader("上傳個人筆記檔案：", type=["pdf", "docx", "txt", "md"], key="note_uploader")
        if uploaded_note_file is not None:
            try:
                from doc_parser import parse_document
                parsed_text, _ = parse_document(uploaded_note_file.read(), uploaded_note_file.name)
                notes_from_file = parsed_text
                st.success(f"已讀取筆記《{uploaded_note_file.name}》，擷取到 {len(parsed_text):,} 字元！")
            except Exception as pe:
                st.error(f"檔案解析失敗: {pe}")

    notes_from_text = ""
    with note_tab2:
        notes_from_text = st.text_area("直接貼上法學筆記、實務見解或考點爭議重點：", height=120, placeholder="例如：貼上王澤鑑老師權益歸屬說論點、最高法院108台上大字1719號裁定重點摘要...")

    final_notes = (notes_from_file + "\n" + notes_from_text).strip()
    if final_notes:
        st.info(f"💡 目前已載入個人筆記重點（共 {len(final_notes):,} 字），命題引擎將嚴密結合您的筆記重點進行客製化命題！")

    if stage == "一試 (選擇題 / 單選題)":
        q_count = st.slider("出題數量：", min_value=1, max_value=5, value=2)
        if st.button("🎲 生成一試測驗題", type="primary"):
            target_topic = topic.strip() if topic.strip() else "核心實務爭點與法規構成要件"
            with st.spinner("正在依據考科與筆記設計司律一試題目與選項..."):
                try:
                    gen = LawExamGenerator()
                    questions = gen.generate_stage1_exam(
                        subject=subject,
                        topic=target_topic,
                        count=q_count,
                        notes_content=final_notes if final_notes else None
                    )
                    
                    exam_export_md = f"# 【{subject}】司律一試模擬測驗卷\n\n主題考點：{target_topic}\n\n"
                    for i, q in enumerate(questions, 1):
                        st.markdown(f"### 第 {i} 題")
                        st.write(q.get("question"))
                        exam_export_md += f"### 第 {i} 題\n{q.get('question')}\n\n"
                        
                        opts = q.get("options", {})
                        for opt_key, opt_val in opts.items():
                            st.write(f"**({opt_key})** {opt_val}")
                            exam_export_md += f"- ({opt_key}) {opt_val}\n"
                            
                        with st.expander("查看解答與解析"):
                            st.success(f"**正確答案：({q.get('answer')})**")
                            st.markdown(q.get("explanation"))
                            exam_export_md += f"\n**【正確答案】**：({q.get('answer')})\n**【解析】**：{q.get('explanation')}\n\n---\n\n"
                        st.divider()

                    st.download_button(
                        label="💾 下載本回一試模擬測驗卷 (Markdown)",
                        data=exam_export_md,
                        file_name=f"司律一試_{subject}_{target_topic[:10]}.md",
                        mime="text/markdown"
                    )
                except Exception as e:
                    st.error(f"出題失敗: {e}")

    else:
        if st.button("🎲 生成二試申論題", type="primary"):
            target_topic = topic.strip() if topic.strip() else "年度重大爭議實例與實務大法庭爭點"
            with st.spinner("正在擬定二試實例案例事實與子題..."):
                try:
                    gen = LawExamGenerator()
                    res = gen.generate_stage2_exam(
                        subject=subject,
                        topic=target_topic,
                        notes_content=final_notes if final_notes else None
                    )
                    st.subheader(f"【{res.get('subject', subject)}】實例申論題 (總分：{res.get('total_points', 50)} 分)")
                    st.markdown("#### 案例事實：")
                    st.write(res.get("question_facts", ""))
                    st.markdown("#### 請回答下列問題：")
                    for sub in res.get("sub_questions", []):
                        st.write(f"- **{sub}**")
                    with st.expander("查看核心爭點與評分指標"):
                        for cr in res.get("core_issues", []):
                            st.write(f"- {cr}")
                        st.info(f"**評分關鍵：**\n{res.get('scoring_criteria', '')}")

                    # 一鍵生成擬答按鈕
                    full_q_text = f"【案例事實】：\n{res.get('question_facts', '')}\n\n【問題】：\n" + "\n".join(res.get("sub_questions", []))
                    if st.button("💡 針對本題生成榜首級示範擬答 (IRAC)"):
                        with st.spinner("榜首法學名師正在撰寫嚴謹三段論法擬答..."):
                            ans = gen.generate_model_answer(question=full_q_text, subject=subject)
                            st.markdown("### 🏆 閱卷高分示範擬答：")
                            st.markdown(ans)
                except Exception as e:
                    st.error(f"出題失敗: {e}")

# ----------------- 模式 3: 擬答生成 -----------------
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
