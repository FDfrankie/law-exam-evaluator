"""
工作區 1：試卷評分、歷屆真題庫與高分擬答 (Workspace Grading)
整合原 Mode 1 (試卷評分), Mode 3 (歷屆真題庫), Mode 4 (高分擬答)
具備 KPI Metric Cards、左右雙欄 Side-by-Side 對照與 IRAC 診斷。
"""

import os
import io
import re
import json
import time
import tempfile
from pathlib import Path
from PIL import Image
import streamlit as st

from config import (
    MODE_HOME, MODE_EVAL, MODE_GEN, MODE_BANK, MODE_ANS,
    MODE_SEARCH, MODE_QA, MODE_SUMMARIZER, MODE_SIX_CODES, MODE_SFT,
    DATA_DIR, RAW_DATA_DIR, GOOGLE_DRIVE_DATA_DIR,
    get_gemini_api_key, DEFAULT_GEMINI_MODEL
)
from core.evaluator import LawExamEvaluator
from core.exam_generator import LawExamGenerator
from core.doc_parser import parse_document, ocr_handwritten_images
from core.community_archive import (
    archive_uploaded_question, archive_uploaded_note,
    load_community_questions, search_community_questions
)
from core.core_issues_taxonomy import load_all_drive_notes
try:
    from core.exam_bank_crawler import LawExamBankCrawler
except ImportError:
    LawExamBankCrawler = None

from ui.components import (
    render_kpi_metrics,
    render_side_by_side_diff,
    render_safe_pdf_viewer,
    render_inline_action_pills
)

def render_workspace():
    """渲染工作區 1：試卷批改與擬答"""
    st.title("📝 試卷評分、歷屆真題與權威擬答")
    st.caption("支援手寫/PDF/Word 多模態評閱、真題庫跨校檢索與上位卷 IRAC 權威擬答生成。")
    render_inline_action_pills()

    # 檢查是否有自其他模組跳轉帶入的指定子分頁
    dest_subtab = st.session_state.pop("grading_subtab_target", 0)

    # 頂部三大子功能分頁
    tab_eval, tab_bank, tab_ans = st.tabs([
        "📝 試卷評分與手寫辨識",
        "📚 歷屆真題庫檢索與演練",
        "📖 高分權威擬答生成"
    ])

    with tab_eval:
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

                        # 評分結果面板 (現代化 KPI Metric Cards 與 左右雙欄 Side-by-Side 對照)
                        render_kpi_metrics(
                            total_score=result.get('total_score', 0),
                            grade_level=result.get("grade_level", "上位卷 (前 15%)"),
                            issue_score=result.get('issue_spotting_score', 0),
                            irac_score=result.get('legal_reasoning_score', 0),
                            subsumption_score=result.get('precedent_scholarship_score', 0) + result.get('subsumption_score', 0)
                        )
                        render_side_by_side_diff(
                            user_ocr_text=result.get("transcribed_text", combined_text or ""),
                            benchmark_model_text=result.get("model_benchmark_revision", "") or result.get("detailed_critique", "")
                        )

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

    with tab_bank:
        st.header("📚 全台法學歷年真題庫與名師講義精華檢索")

        drive_notes = load_all_drive_notes()
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
                            st.session_state["app_mode"] = MODE_SEARCH
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

    with tab_ans:
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
