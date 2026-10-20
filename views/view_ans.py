import streamlit as st
from exam_generator import LawExamGenerator
from views.constants import MODE_EVAL

def render_mode_ans():
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
                        st.session_state["app_mode"] = MODE_EVAL
                        st.rerun()
                except Exception as e:
                    st.error(f"出題失敗: {e}")


