import streamlit as st
import os
import json
import re
import urllib.parse
from config import DATA_DIR
try:
    from legal_query_engine import (
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
except Exception:
    pass
from core_issues_taxonomy import (
    get_taxonomy_chapters_for_subject,
    get_curated_issues_by_chapter,
    get_total_curated_issues_count
)
from views.constants import MODE_SUMMARIZER, MODE_EVAL, MODE_ANS

def render_mode_search():
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
    st.session_state["m5_sub_mode_idx"] = m5_sub_modes.index(m5_active_tab)

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
                        st.session_state["app_mode"] = MODE_SUMMARIZER  # 切換至 AI 判解精鍊旗艦
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
                    st.session_state["app_mode"] = MODE_EVAL
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
                    st.session_state["app_mode"] = MODE_EVAL
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
                        st.session_state["app_mode"] = MODE_EVAL
                        st.rerun()



