import streamlit as st
import os
import json
import re
from pathlib import Path

from config import DATA_DIR, RAW_DATA_DIR
from exam_generator import LawExamGenerator
from community_archive_engine import (
    load_community_questions,
    search_community_questions,
    archive_uploaded_question
)
from ingest_user_notes_to_sft import read_note_text
from views.common import load_all_drive_notes, reset_stage1_exam_state
from views.constants import MODE_EVAL, MODE_SEARCH

try:
    from exam_bank_crawler import LawExamBankCrawler
except Exception:
    class LawExamBankCrawler:
        def __init__(self):
            p = Path(DATA_DIR) / 'raw_exams' / 'exams_catalog.json'
            self.catalog = json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
        def run_all(self, max_pages=2):
            pass

def render_mode_bank():
    drive_notes = load_all_drive_notes()
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
                            st.session_state["app_mode"] = MODE_EVAL
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
                                st.session_state["app_mode"] = MODE_EVAL
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
                            st.session_state["app_mode"] = MODE_EVAL
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
                            st.session_state["app_mode"] = MODE_EVAL
                            st.rerun()
                    with c_act2:
                        if st.button(f"🏆 生成榜首級示範擬答 (IRAC)", key=f"btn_model_ans_{q_id}"):
                            with st.spinner("榜首名師正在撰寫嚴謹三段論法擬答..."):
                                gen = LawExamGenerator()
                                m_ans = gen.generate_model_answer(question=q_text, subject=q_subj)
                                st.markdown("##### 🏆 閱卷高分示範擬答：")
                                st.markdown(m_ans)


