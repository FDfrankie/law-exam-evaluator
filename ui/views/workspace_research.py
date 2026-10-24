"""
工作區 3：統一法學檢索、裁判精鍊與審級比對 (Workspace Research)
整合原 Mode 5 (統一法學檢索樞紐) 與 Mode 7 (AI 裁判精鍊與開放資料大庫)。
支援布林邏輯多庫檢索、審級脈絡比對、大法庭/原判例專區與司法院開放資料批次匯入。
"""

import os
import io
import re
import json
import time
import tempfile
import urllib.parse
from pathlib import Path
import streamlit as st

from config import (
    DATA_DIR, RAW_DATA_DIR, GOOGLE_DRIVE_DATA_DIR,
    get_gemini_api_key, DEFAULT_GEMINI_MODEL, GEMINI_FALLBACK_MODELS,
    get_gemini_models_to_try,
    MODE_HOME, MODE_EVAL, MODE_GEN, MODE_BANK, MODE_ANS,
    MODE_SEARCH, MODE_QA, MODE_SUMMARIZER, MODE_SIX_CODES, MODE_SFT
)
from core.legal_query_engine import (
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
from core.legal_summarizer import (
    BooleanQueryParser,
    evaluate_boolean_query,
    AILegalSummarizer,
    lookup_case_by_abbreviation,
    find_legal_doc_by_citation
)
from core.core_issues_taxonomy import (
    MASTER_CURATED_ISSUES,
    LAW_DOMAIN_TAXONOMY
)
from ui.components import render_inline_action_pills

def render_workspace():
    """渲染工作區 3：裁判檢索與精鍊"""
    st.title("⚖️ 統一法學檢索樞紐與 AI 裁判精鍊")
    st.caption("支援布林邏輯精確篩選、審級歷審脈絡比對、重大原判例專區與長篇裁判要旨自動精鍊。")
    render_inline_action_pills()

    dest_subtab = st.session_state.pop("research_subtab_target", 0)

    tab_search, tab_summarizer = st.tabs([
        "🔍 統一法學檢索樞紐與審級脈絡",
        "📑 AI 裁判要旨精鍊與大庫擴充"
    ])

    with tab_search:
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
        st.session_state["m5_sub_mode_idx"] = m5_sub_modes.index(m5_active_tab) if m5_active_tab in m5_sub_modes else 0

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
                            st.session_state["app_mode"] = MODE_SUMMARIZER
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
                                    st.session_state["app_mode"] = MODE_SUMMARIZER
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
                                    st.session_state["app_mode"] = MODE_SUMMARIZER
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
                        st.session_state["app_mode"] = MODE_SUMMARIZER
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
                                    st.session_state["app_mode"] = MODE_SUMMARIZER
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
                        st.session_state["app_mode"] = MODE_ANS
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

    with tab_summarizer:
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

        # ----------------- 模式 6: 智慧六法與條文判解綜合標註 (法條・沿革・爭點・筆記) -----------------
