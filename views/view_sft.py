import streamlit as st
import os
import sys
import json
import re
import time
import tempfile
import shutil
import subprocess
import zipfile
from pathlib import Path

from config import DATA_DIR, GOOGLE_DRIVE_DATA_DIR
from ingest_user_notes_to_sft import (
    get_google_drive_notes_list,
    read_note_text,
    sync_all_drive_notes_to_samsung_notes,
    distill_single_note_file,
    merge_subject_pdfs,
    extract_subject_text_corpus,
    get_chapter_sort_key,
    ingest_single_uploaded_file
)
from community_archive_engine import (
    archive_uploaded_question,
    archive_uploaded_note,
    load_community_questions,
    load_community_notes,
    search_community_questions,
    search_community_notes
)
from views.common import load_all_drive_notes
from views.constants import MODE_SFT

def render_mode_sft():
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

