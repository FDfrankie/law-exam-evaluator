import streamlit as st
import os
import json
import re
import time
import base64
from pathlib import Path

from six_codes_engine import (
    SIX_CODES_TAXONOMY,
    get_laws_in_branch,
    search_articles,
    get_article_annotations,
    SixCodesDeepAnnotator,
    get_law_legislative_history,
    get_article_legislative_details,
    synthesize_article_legislative_details,
    clear_six_codes_cache,
    load_six_codes_data
)
from six_codes_updater import update_law_amendments, load_amendments_history
from admin_rulings_engine import (
    get_law_key_regulations,
    get_regulation_full_details,
    get_admin_rulings_for_article,
    get_all_administrative_rulings,
    crawl_and_synthesize_admin_rulings,
    get_chorder_regulations_map,
    LANDMARK_ADMIN_RULINGS,
    load_crawled_admin_rulings
)
from views.constants import MODE_SUMMARIZER, MODE_SEARCH, MODE_EVAL, MODE_ANS

def render_mode_six_codes():
    st.header("⚖️ 智慧六法全書與條文爭點判解綜合標註系統")
    st.write("全面收錄全台 **2,053 部國家法律、法規命令與施行細則，共 62,342 條法定條文，及 600+ 則中央部會權威行政函釋**，直接在條文下方完整串接**條文結構**、**立法理由與沿革**、**憲判字/最高法院大法庭權威裁判**、**學說肯否二說**、**法規命令施行細則全文點閱**、**主管機關權威函釋**及**考生個人手寫讀書筆記**！")

    # 1. 導航選擇列
    col_b, col_l, col_q = st.columns([1, 1, 2])
    with col_b:
        branch_options = list(SIX_CODES_TAXONOMY.keys())
        default_br = st.session_state.get("six_codes_branch", branch_options[0])
        br_idx = branch_options.index(default_br) if default_br in branch_options else 0
        selected_branch = st.selectbox("1. 選擇法學門類：", branch_options, index=br_idx, key=f"sel_br_widget_{default_br}")
        st.session_state["six_codes_branch"] = selected_branch
    with col_l:
        available_laws = get_laws_in_branch(selected_branch)
        default_law = st.session_state.get("six_codes_law", available_laws[0] if available_laws else "")
        law_idx = available_laws.index(default_law) if default_law in available_laws else 0
        selected_law = st.selectbox("2. 選擇法典名稱：", available_laws, index=law_idx, key=f"sel_law_widget_{default_law}")
        st.session_state["six_codes_law"] = selected_law
    with col_q:
        default_kw = st.session_state.get("six_codes_search_kw", "")
        search_kw = st.text_input(
            "3. 搜尋條號（如 184、19、64、759-1）或條文關鍵字：",
            value=default_kw,
            placeholder="輸入條號或法理關鍵字（如：純粹經濟、借名登記、原因自由行為）...",
            key=f"search_kw_widget_{st.session_state.get('six_codes_kw_rev', 0)}"
        )
        st.session_state["six_codes_search_kw"] = search_kw
        st.caption("💡 **專業布林精準搜尋**：支援 `＆`（且）、`＋`（或）、`－`（排除）、`( )`（優先組合）。例：`(侵權行為 ＋ 債務不履行) ＆ (純粹經濟 － 故意)`")

    # 🌟 新功能：更新六法按鈕（按下去之後六法會自動聯網更新最近的修法，同步至本機大典）
    up_col1, up_col2 = st.columns([3, 1])
    with up_col1:
        st.caption(f"💡 目前法學大庫已收錄 **{selected_law}**。若立法院近期三讀通過修正條文，點擊右方按鈕即可自動連線全國法規會與立法院公報更新！")
    with up_col2:
        if st.button(f"🔄 更新六法（【{selected_law}】最新修法）", use_container_width=True, key=f"btn_update_law_{selected_law}"):
            with st.spinner(f"正在聯網比對並更新【{selected_law}】最新公布條文與立法理由..."):
                update_res = update_law_amendments(selected_law)
                clear_six_codes_cache()
                st.session_state[f"last_amendment_res_{selected_law}"] = update_res
                st.toast(f"✅ 【{selected_law}】修法資料更新完成！", icon="🎉")

    if st.session_state.get(f"last_amendment_res_{selected_law}"):
        last_res = st.session_state.get(f"last_amendment_res_{selected_law}")
        with st.expander(f"🆕 【{selected_law}】最新修法更新報告 ｜ 📅 {last_res.get('latest_amendment_date', '最新修正公布')}", expanded=True):
            st.markdown(f"**🌟 修法重點摘要：** {last_res.get('summary', '')}")
            st.caption(f"更新狀態：`{last_res.get('status')}` ｜ 本次更新條文數：`{last_res.get('amended_count', 0)}` 條")
            for am_item in last_res.get("amended_articles", []):
                st.markdown(f"##### 📌 {am_item.get('article_no')}")
                st.info(f"**最新施行條文全文：**\n{am_item.get('new_content', '')}")
                if am_item.get('amendment_reason'):
                    st.markdown(f"🏛️ **立法院官方立法理由：**\n{am_item.get('amendment_reason')}")
                if am_item.get('exam_points'):
                    st.success(f"✍️ **司律二試國考作答熱點：**\n{am_item.get('exam_points')}")
                st.markdown("---")

    # 若當前選擇者為法規命令或細則，提示授權母法並提供快速返回母法按鈕
    if any(s in selected_law for s in ["辦法", "細則", "準則", "規則", "規程", "標準"]):
        parent_candidate = None
        for p_cand in ["公司法", "證券交易法", "民法", "專利法", "商標法", "著作權法", "勞動基準法", "行政程序法", "民事訴訟法", "刑事訴訟法"]:
            if p_cand in selected_law:
                parent_candidate = p_cand
                break
        if not parent_candidate:
            if "公司" in selected_law: parent_candidate = "公司法"
            elif "證券" in selected_law or "董事會" in selected_law: parent_candidate = "公司法"
            elif "專利" in selected_law: parent_candidate = "專利法"
            elif "商標" in selected_law: parent_candidate = "商標法"
            elif "著作" in selected_law: parent_candidate = "著作權法"
            elif "勞動" in selected_law or "請假" in selected_law: parent_candidate = "勞動基準法"

        if parent_candidate:
            bc_col1, bc_col2 = st.columns([3, 1])
            with bc_col1:
                st.info(f"📘 您目前正在研讀法規命令/施行細則：**《{selected_law}》**（授權母法為【{parent_candidate}】）")
            with bc_col2:
                if st.button(f"🔙 返回母法【{parent_candidate}】", use_container_width=True):
                    st.session_state["six_codes_law"] = parent_candidate
                    st.session_state["six_codes_search_kw"] = ""
                    st.session_state["six_codes_kw_rev"] = st.session_state.get("six_codes_kw_rev", 0) + 1
                    st.rerun()

    # 完整法律/法規命令立法沿革與歷次修正紀錄 (共 XX 次修正公報)
    law_hist_info = get_law_legislative_history(selected_law)
    total_amendments = law_hist_info.get("total_amendments", 0)
    timeline = law_hist_info.get("timeline", [])

    if total_amendments > 0:
        first_date = timeline[0].get("date", "") if timeline else ""
        latest_date = timeline[-1].get("date", "") if timeline else ""
        date_summary = f"（{first_date} 制定公布 ➔ {latest_date} 最新修正）" if first_date and latest_date else ""
        with st.expander(f"📜 【{selected_law}】完整立法沿革與歷次修正公報 ｜ 🏛️ 共歷經 {total_amendments} 次制定/修正公布 {date_summary}", expanded=False):
            st.markdown(f"#### 📜 《{selected_law}》法定沿革與歷次修正公報資料庫")
            st.caption(f"法規類別：`{law_hist_info.get('category', '全國法規')}` ｜ 法規性質：`{law_hist_info.get('type', '法律')}` ｜ 全國法規代碼 (PCode)：`{law_hist_info.get('pcode', 'N/A')}`")

            hist_kw = st.text_input(f"在《{selected_law}》歷次沿革公報中搜尋（如年份、條號、總統令號、修正要點）：", key=f"hist_kw_{selected_law}")
            filtered_timeline = timeline
            if hist_kw:
                filtered_timeline = [t for t in timeline if hist_kw in t.get("content", "") or hist_kw in t.get("date", "") or hist_kw in t.get("decree", "")]
                st.caption(f"找到 {len(filtered_timeline)} 筆符合「{hist_kw}」之修正紀錄：")

            with st.container(height=350):
                for t in reversed(filtered_timeline):
                    seq_badge = f"第 {t['seq']} 次修正" if t['seq'] > 1 else "制定發布"
                    st.markdown(f"**🏷️ 【{seq_badge}】📅 {t['date']} ｜ {t['decree']} ｜ `{t['action']}`**")
                    st.info(t['content'])
                    st.markdown("---")

    # 跨部會中央主管機關行政函釋快速檢索專區
    with st.expander("🏛️ 中央主管機關行政函釋（經濟部/智財局/金管會/法務部/勞動部/財政部）跨部會速查庫 (已收錄 600+ 則)", expanded=False):
        st.markdown("全面收錄中央主管機關之具拘束力行政指導、令函與重要解釋。您可直接依主管部會或關鍵字查詢：")
        all_rulings_pool = get_all_administrative_rulings()
        agencies_filter = ["全部機關", "經濟部商業司", "經濟部商業發展署", "經濟部智慧財產局", "金融監督管理委員會", "法務部", "勞動部", "財政部賦稅署"]
        c_a1, c_a2 = st.columns([1, 2])
        with c_a1:
            sel_agency = st.selectbox("主管機關篩選：", agencies_filter, key="browse_agency_filter")
        with c_a2:
            search_ruling_kw = st.text_input("輸入函釋字號、法條或關鍵字（如：大同條款、生成式AI、內線交易、合理保密措施...）：", key="browse_ruling_kw")

        filtered_rulings = all_rulings_pool
        if sel_agency != "全部機關":
            filtered_rulings = [r for r in filtered_rulings if sel_agency in r.get("agency", "")]
        if search_ruling_kw:
            filtered_rulings = [r for r in filtered_rulings if search_ruling_kw in r.get("doc_number", "") or search_ruling_kw in r.get("title", "") or search_ruling_kw in r.get("holding", "") or search_ruling_kw in r.get("law_name", "")]

        st.caption(f"共篩選出 **{len(filtered_rulings)} 筆** 主管機關行政函釋：")
        with st.container(height=350):
            for r in filtered_rulings:
                st.markdown(f"**🏢 【{r.get('agency')}】`{r.get('doc_number')}` ｜ {r.get('law_name')} {r.get('article_target', '')}**")
                st.markdown(f"**🌟 {r.get('title')}** (📅 {r.get('date')})")
                if r.get('exam_point_hint'):
                    st.caption(f"✍️ **國考作答提示：** {r.get('exam_point_hint')}")
                st.markdown("---")

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

            anno = get_article_annotations(law_name=lname, article_no=ano, content=content)
            precedents = anno.get("precedents", [])
            notes = anno.get("notes", [])

            # 整合預載之核心法規命令與六法中所有關聯命令（包含公司登記辦法、公開發行公司董事會議事辦法等）
            raw_key_regs = get_law_key_regulations(lname)
            raw_mapped_orders = anno.get("orders", [])

            key_regulations = []
            seen_reg_names = set()
            for r in raw_key_regs:
                r_name = r.get("name")
                if r_name and r_name not in seen_reg_names:
                    seen_reg_names.add(r_name)
                    key_regulations.append(r)

            for o in raw_mapped_orders:
                o_name = o.get("name")
                if o_name and o_name not in seen_reg_names:
                    seen_reg_names.add(o_name)
                    o_arts = o.get("articles", [])
                    key_regulations.append({
                        "name": o_name,
                        "type": o.get("type", "法規命令"),
                        "desc": o.get("desc", ""),
                        "article_count": o.get("articles_count", len(o_arts)),
                        "articles": o_arts,
                        "details": {
                            "name": o_name,
                            "category": o.get("category", "中央行政部會"),
                            "modified_date": o.get("modified_date", ""),
                            "url": "",
                            "total_articles": len(o_arts),
                            "articles": [{"no": a.get("article_no", ""), "content": a.get("content", "")} for a in o_arts]
                        } if o_arts else get_regulation_full_details(o_name)
                    })

            admin_rulings = anno.get("admin_rulings", []) or get_admin_rulings_for_article(lname, ano)

            legis_data = anno.get("legislative_details", {}) or get_article_legislative_details(lname, ano, content)
            curated_amends = legis_data.get("curated_amendments", [])
            timeline_hits = legis_data.get("timeline_hits", [])
            total_amends_display = len(curated_amends) if curated_amends else len(timeline_hits)

            questions = anno.get("questions", [])
            handouts = anno.get("handouts", [])

            combined_materials = handouts + notes

            badge_amend = " ｜ 🆕 【最新修正施行】" if art.get("is_latest_amendment") else ""
            badge_prec = f" ｜ 🏛️ 【收錄 {len(precedents)} 筆大法庭/憲判字】" if precedents else ""
            badge_orders_rulings = f" ｜ 📋 【{len(key_regulations)} 部法規/細則 ＋ {len(admin_rulings)} 筆主管函釋】" if (key_regulations or admin_rulings) else ""
            badge_legis = f" ｜ 🕰️ 【{total_amends_display} 次修法對照】" if total_amends_display > 0 else ""
            badge_materials = f" ｜ 📘 【收錄 {len(combined_materials)} 份名師講義與個人讀書筆記】" if combined_materials else ""

            exp_label = f"📖 【{lname} {ano}】{badge_amend}{badge_prec}{badge_orders_rulings}{badge_legis}{badge_materials}"
            with st.expander(exp_label, expanded=bool(idx < 2 or art.get("is_latest_amendment"))):
                if art.get("is_latest_amendment"):
                    st.success(f"🆕 **此條文為立法院最新三讀通過並經總統府公布之修正條文！** (施行日期：{art.get('modified_date', '最新公布')})")
                    if art.get("amendment_reason"):
                        st.markdown(f"🏛️ **官方立法理由：** {art.get('amendment_reason')}")
                    if art.get("exam_points"):
                        st.markdown(f"✍️ **國考作答熱點：** {art.get('exam_points')}")
                st.markdown(f"> **📜 條文全文**：\n> {content}")

                tab_prec, tab_orders_rulings, tab_legis, tab_materials, tab_ai = st.tabs([
                    f"🏛️ 權威司法判解 ({len(precedents)} 筆)",
                    f"📋 關聯法規命令、施行細則與主管機關行政函釋 ({len(key_regulations)} 部法規・{len(admin_rulings)} 筆函釋)",
                    f"🕰️ 立法理由與歷史條文 ({total_amends_display} 次修法對照)",
                    f"📘 關聯名師講義與個人手寫讀書筆記 ({len(combined_materials)} 份・線上閱讀 PDF)",
                    "🤖 AI 深度釋析與作答模版"
                ])

                with tab_prec:
                    if precedents:
                        for p_idx, p in enumerate(precedents):
                            st.markdown(f"**【{p.get('level')}】`{p.get('case_id')}`** ｜ **{p.get('title')}**")
                            st.info(f"**核心要旨/主文：**\n{p.get('holding')}")
                            if p.get('scholarly_views'):
                                st.caption(f"📚 **學說實務對比：** {p.get('scholarly_views')}")
                            if p.get('exam_application_hint'):
                                st.success(f"✍️ **國考作答指示：** {p.get('exam_application_hint')}")

                            c_p1, c_p2 = st.columns(2)
                            with c_p1:
                                if st.button(f"⚡ 產出本判決 AI 深度摘要", key=f"btn_tab_sum_{idx}_{p_idx}", use_container_width=True):
                                    st.session_state["sum_citation_search"] = p.get("case_id", "")
                                    st.session_state["citation_rev"] = st.session_state.get("citation_rev", 0) + 1
                                    st.session_state["app_mode"] = MODE_SUMMARIZER
                                    st.rerun()
                            with c_p2:
                                if st.button(f"🔄 帶入進行案例橫向比對", key=f"btn_tab_cmp_{idx}_{p_idx}", use_container_width=True):
                                    st.session_state["target_compare_case_a"] = p.get("case_id", "")
                                    st.session_state["target_compare_topic"] = f"{lname} {ano} 相關裁判見解分歧"
                                    st.session_state["m5_sub_mode_idx"] = 4
                                    st.session_state["app_mode"] = MODE_SEARCH
                                    st.rerun()
                            st.markdown("---")
                    else:
                        st.caption("本機權威判解庫中目前無直接標註此條文之大法庭裁定，可前往【統一法學檢索樞紐】或由 AI 進行歷審精選裁判與學說補強。")

                with tab_orders_rulings:
                    st.markdown(f"#### 📋 【{lname} {ano}】關聯法規命令、施行細則與主管機關行政函釋")
                    st.caption("全面整合 **授權法規命令與細則全文點閱**、**主管機關行政指導與解釋令函**，以及**跨法典法律/命令快速直通聯結**！")

                    # 第一區塊：關聯法規命令與施行細則
                    st.markdown("##### 📘 一、授權法規命令、施行細則與相關關聯法規全文")
                    if key_regulations:
                        st.caption(f"已串接行政院及主管部會發布之法規命令與細則全文。點擊下方各命令卡片即可展開閱讀完整條文：")
                        for r_idx, reg in enumerate(key_regulations):
                            reg_name = reg["name"]
                            reg_type = reg["type"]
                            reg_desc = reg["desc"]
                            art_count = reg.get("article_count", 0)
                            reg_details = reg.get("details")

                            badge_count = f"共 {art_count} 條全文" if art_count > 0 else "施行細則"
                            with st.expander(f"📘 《{reg_name}》 (`{reg_type}`) ｜ 📚 {badge_count}", expanded=(r_idx == 0 and idx == 0)):
                                st.markdown(f"**規範主旨/適用範圍**：\n{reg_desc}")
                                if reg.get("key_articles_hint"):
                                    st.info(f"💡 **國考與實務核心考點條文**：\n{reg['key_articles_hint']}")

                                raw_arts = (reg_details.get("articles") if reg_details else None) or reg.get("articles") or []
                                arts = []
                                for a in raw_arts:
                                    a_no = a.get("no") or a.get("article_no") or ""
                                    a_c = a.get("content") or ""
                                    if a_no or a_c:
                                        arts.append({"no": a_no, "content": a_c})

                                if arts:
                                    st.markdown(f"##### 📖 《{reg_name}》條文全文點閱系統 (共收錄 {len(arts)} 條)")

                                    read_mode = st.radio(
                                        f"條文檢視模式 ({reg_name})：",
                                        ["🔍 依條號選取詳細研讀", "📜 展開瀏覽全法規所有條文", "🔎 條文內關鍵字搜尋"],
                                        horizontal=True,
                                        key=f"reg_mode_{idx}_{r_idx}"
                                    )

                                    if read_mode == "🔍 依條號選取詳細研讀":
                                        art_options = [f"{a['no']} - {a['content'][:35]}..." if len(a['content']) > 35 else f"{a['no']} - {a['content']}" for a in arts]
                                        chosen_art_str = st.selectbox(
                                            f"請選擇欲研讀之條號：",
                                            options=art_options,
                                            key=f"sel_art_{idx}_{r_idx}"
                                        )
                                        chosen_idx = art_options.index(chosen_art_str)
                                        target_art = arts[chosen_idx]
                                        st.markdown(f"**【{target_art['no']}】**")
                                        st.info(target_art['content'])
                                    elif read_mode == "📜 展開瀏覽全法規所有條文":
                                        with st.container(height=350):
                                            for a in arts:
                                                st.markdown(f"**{a['no']}**")
                                                st.markdown(f"> {a['content']}")
                                                st.markdown("---")
                                    elif read_mode == "🔎 條文內關鍵字搜尋":
                                        sub_kw = st.text_input(f"輸入在《{reg_name}》內搜尋之文字：", key=f"sub_kw_{idx}_{r_idx}")
                                        if sub_kw:
                                            hit_arts = [a for a in arts if sub_kw in a['no'] or sub_kw in a['content']]
                                            st.caption(f"在《{reg_name}》中找到 {len(hit_arts)} 條包含「{sub_kw}」之條文：")
                                            for a in hit_arts:
                                                st.markdown(f"**{a['no']}**")
                                                st.markdown(f"> {a['content']}")
                                                st.markdown("---")
                                        else:
                                            st.caption("請輸入關鍵字以即時過濾法規命令條文。")

                                # 跳轉與外鏈按鈕列
                                btn_col1, btn_col2 = st.columns([1, 1])
                                with btn_col1:
                                    if st.button(f"📖 在六法主檢索區開啟《{reg_name}》全文", key=f"btn_jump_order_{idx}_{r_idx}", type="primary"):
                                        st.session_state["six_codes_law"] = reg_name
                                        for br_name, br_laws in SIX_CODES_TAXONOMY.items():
                                            if reg_name in br_laws:
                                                st.session_state["six_codes_branch"] = br_name
                                                break
                                        st.session_state["six_codes_search_kw"] = ""
                                        st.session_state["six_codes_kw_rev"] = st.session_state.get("six_codes_kw_rev", 0) + 1
                                        st.rerun()
                                Dangerously_url = reg_details.get("url") if reg_details else ""
                                with btn_col2:
                                    if Dangerously_url:
                                        st.link_button(f"🌐 前往全國法規資料庫官方查看《{reg_name}》", Dangerously_url)
                    else:
                        st.info("此法規母法目前無直接對應之核心法規命令，或直接以母法本體為規範依據。")

                    # 任意快速直通調閱全國 2,053 部法律與 10,452 部行政命令 (任意調閱與連結其他法律)
                    with st.expander(f"🔗 快速連結與直通調閱其他法律或行政命令全文 (支援全台 2,053 部法律與 10,452 部法規命令)", expanded=False):
                        st.caption("可在此直接搜尋並一鍵切換調閱任何相關法律（如：性侵害犯罪防治法、刑法、兒童及少年福利與權益保障法）或行政命令：")
                        col_rel1, col_rel2 = st.columns([3, 1])
                        with col_rel1:
                            try:
                                _, _, law_map = load_six_codes_data()
                                all_law_names = sorted(list(law_map.keys()))
                            except Exception:
                                all_law_names = []
                            kw_rel_law = st.text_input("輸入欲聯結之法律名稱關鍵字：", placeholder="例如：性侵害犯罪防治法、個人資料保護法、刑法...", key=f"kw_rel_law_{idx}")
                        with col_rel2:
                            st.write("")
                            st.write("")
                            matched_rel_laws = [l for l in all_law_names if kw_rel_law.strip() and kw_rel_law.strip() in l][:20] if kw_rel_law.strip() else []

                        if matched_rel_laws:
                            sel_rel_law = st.selectbox("選擇欲切換研讀之關聯法律：", matched_rel_laws, key=f"sel_rel_law_{idx}")
                            if st.button(f"🚀 一鍵開啟《{sel_rel_law}》條文全文", key=f"btn_switch_rel_law_{idx}", type="primary"):
                                st.session_state["six_codes_law"] = sel_rel_law
                                for br_name, br_laws in SIX_CODES_TAXONOMY.items():
                                    if sel_rel_law in br_laws:
                                        st.session_state["six_codes_branch"] = br_name
                                        break
                                st.session_state["six_codes_search_kw"] = ""
                                st.session_state["six_codes_kw_rev"] = st.session_state.get("six_codes_kw_rev", 0) + 1
                                st.rerun()

                        # 行政命令部分
                        all_orders_map = get_chorder_regulations_map()
                        kw_custom_reg = st.text_input(f"或輸入行政命令/細則名稱（例如：專利法施行細則、公開發行公司、勞工請假...）：", key=f"kw_custom_reg_{idx}")
                        if kw_custom_reg:
                            matched_regs = [k for k in all_orders_map.keys() if kw_custom_reg in k][:15]
                            if matched_regs:
                                selected_custom_reg = st.selectbox(f"找到相符法規命令：", matched_regs, key=f"sel_custom_reg_{idx}")
                                c_details = get_regulation_full_details(selected_custom_reg)
                                if c_details:
                                    st.success(f"已載入《{c_details['name']}》（主管部會：{c_details['category']}，共 {c_details['total_articles']} 條）")
                                    with st.container(height=300):
                                        for a in c_details["articles"]:
                                            st.markdown(f"**{a['no']}**")
                                            st.markdown(f"> {a['content']}")
                                            st.markdown("---")
                            else:
                                st.warning("未找到相符之法規命令名稱。")

                    st.markdown("---")

                    # 第二區塊：主管機關權威行政函釋庫
                    st.markdown("##### 📜 二、主管機關權威行政函釋庫 (經濟部/智財局/金管會/法務部/衛福部/勞動部)")
                    st.caption("深度整合主管機關具拘束力之行政指導、函令解釋與實務爭點法律見解：")

                    if admin_rulings:
                        for r_item in admin_rulings:
                            agency_badge = r_item.get("agency", "主管機關")
                            doc_no = r_item.get("doc_number", "函釋字號")
                            r_date = r_item.get("date", "")
                            r_title = r_item.get("title", "")
                            r_holding = r_item.get("holding", "")
                            r_analysis = r_item.get("content_analysis", "")
                            r_hint = r_item.get("exam_point_hint", "")

                            st.markdown(f"##### 🏢 【{agency_badge}】`{doc_no}` ｜ 📅 {r_date}")
                            st.markdown(f"**🌟 函釋主旨**：**{r_title}**")
                            st.info(f"**核心要旨（Holding）：**\n{r_holding}")
                            if r_analysis:
                                with st.expander("📖 查看機關詳細行政法理釋析與法令依據", expanded=False):
                                    st.markdown(r_analysis)
                            if r_hint:
                                st.success(f"✍️ **司律國考上位卷作答引述指引：**\n{r_hint}")
                            st.markdown("---")
                    else:
                        st.info(f"目前本地快取中暫無針對【{lname} {ano}】之預載專屬函釋。您可以立即點擊下方按鈕，由 AI 聯網智慧檢索並補強最新函釋！")

                    # 智慧爬取與補強按鈕
                    crawl_key = f"crawl_rulings_{lname}_{ano}"
                    if st.button(f"🔄 智慧檢索/爬取此條文主管機關最新函釋", key=f"btn_crawl_ruling_{idx}"):
                        with st.spinner(f"正在連線中央主管機關資料庫，為【{lname} {ano}】爬取最新行政函釋與解釋令..."):
                            try:
                                crawled = crawl_and_synthesize_admin_rulings(law_name=lname, article_no=ano, content=content)
                                st.session_state[crawl_key] = crawled
                                st.success(f"🎉 成功爬取並新增 {len(crawled)} 筆主管機關權威函釋！已同步永久寫入本地行政函釋資料庫。")
                                st.rerun()
                            except Exception as ce:
                                st.error(f"函釋爬取失敗: {ce}")

                    if crawl_key in st.session_state:
                        c_list = st.session_state[crawl_key]
                        for c in c_list:
                            st.markdown(f"##### 🏢 【{c.get('agency')}】`{c.get('doc_number')}` ｜ 📅 {c.get('date')}")
                            st.markdown(f"**🌟 函釋主旨**：**{c.get('title')}**")
                            st.info(f"**核心要旨：**\n{c.get('holding')}")
                            if c.get("content_analysis"):
                                st.markdown(f"**法理分析：**\n{c.get('content_analysis')}")
                            if c.get("exam_point_hint"):
                                st.success(f"✍️ **作答指引：** {c.get('exam_point_hint')}")

                with tab_legis:
                    st.markdown(f"#### 📜 【{lname} {ano}】立法意旨、歷次修法理由與歷史新舊條文對照庫")
                    st.caption("完整串接立法院法律提案公報、法律覆議與總統修正公布令，呈現原始立法意旨、歷次修正說明與條文新舊文字變革！")

                    intent = legis_data.get("legislative_intent", "")
                    summary_reasons = legis_data.get("summary_reasons", "")

                    if intent:
                        st.success(f"**🎯 原始立法意旨與核心保護法益：**\n\n{intent}")
                    if summary_reasons:
                        st.info(f"**💡 歷次修正總綱與規範演革重心：**\n\n{summary_reasons}")

                    if curated_amends:
                        st.markdown(f"##### 🕰️ 歷次修法理由全文與新舊條文對照表 (收錄 {len(curated_amends)} 次重大修正)")
                        for a_idx, amend in enumerate(curated_amends):
                            with st.expander(f"📅 【{amend.get('date')}】{amend.get('gazette', '')} ｜ 🌟 {amend.get('key_changes', '條文修正')}", expanded=(a_idx == 0)):
                                p_text = amend.get("previous_text", "")
                                c_text = amend.get("current_text", "")
                                if p_text or c_text:
                                    st.markdown("**⚖️ 新舊法條文文字對照：**")
                                    col_old, col_new = st.columns(2)
                                    with col_old:
                                        st.markdown("**🕰️ 修正前歷史條文（舊法）**")
                                        st.caption(p_text if p_text else "（初次制定或舊無此條）")
                                    with col_new:
                                        st.markdown("**📜 修正後施行條文（新法）**")
                                        st.caption(c_text if c_text else content)

                                st.markdown(f"**📜 立法院三讀官方修正理由全文：**\n{amend.get('reason')}")
                                if amend.get("exam_impact"):
                                    st.success(f"✍️ **司律國考新舊法適用要點：**\n{amend.get('exam_impact')}")
                                st.markdown("---")
                    elif not intent and not summary_reasons:
                        st.info(f"💡 目前本地精選庫中暫無針對【{lname} {ano}】之預載深度立法理由。您可以查看下方官方公報沿革，或點擊下方按鈕由 AI 智慧萃取歷次修正理由與新舊條文對照！")

                    if timeline_hits:
                        st.markdown(f"##### 🏛️ 本條於全法沿革中之歷次修正發布令（全國法規資料庫官方紀錄共 {len(timeline_hits)} 次）")
                        with st.container(height=260):
                            for h in timeline_hits:
                                seq_tag = f"第 {h['seq']} 次修正" if h['seq'] > 1 else "制定公布"
                                st.markdown(f"**🏷️ 【{seq_tag}】📅 {h['date']} ｜ {h['decree']} ｜ `{h['action']}`**")
                                st.caption(h['content'])
                                st.markdown("---")

                    # AI 智慧萃取/擴充按鈕
                    leg_ai_key = f"ai_legis_{lname}_{ano}"
                    if st.button(f"✨ 啟動 AI 深度萃取立法理由與歷次新舊條文對照（立法院公報與法規資料庫）", key=f"btn_ai_legis_{idx}"):
                        with st.spinner(f"正在連線 Gemini 3.x Flash 為【{lname} {ano}】萃取立法院三讀修正理由、修法背景與新舊法對照表..."):
                            try:
                                synthesized = synthesize_article_legislative_details(lname, ano, content)
                                st.session_state[leg_ai_key] = synthesized
                                st.success("🎉 成功提煉並更新本條立法理由與新舊法對照表！已同步持久化保存。")
                                st.rerun()
                            except Exception as le_err:
                                st.error(f"立法理由提煉失敗: {le_err}")

                    if leg_ai_key in st.session_state:
                        ai_res = st.session_state[leg_ai_key]
                        if ai_res.get("legislative_intent") and not intent:
                            st.success(f"**🎯 原始立法意旨：**\n{ai_res['legislative_intent']}")
                        if ai_res.get("curated_amendments") and not curated_amends:
                            for a in ai_res["curated_amendments"]:
                                st.markdown(f"**📅 【{a.get('date')}】{a.get('gazette', '')}**")
                                st.info(f"**修正理由：**\n{a.get('reason')}")
                                if a.get("previous_text"):
                                    st.caption(f"**舊條文：**\n{a.get('previous_text')}")
                                if a.get("exam_impact"):
                                    st.success(f"**新舊法適用要點：**\n{a.get('exam_impact')}")

                with tab_materials:
                    st.markdown(f"#### 📘 關聯名師授課講義與個人手寫讀書筆記（共 {len(combined_materials)} 份）")
                    st.caption("已將課輔講義、名師授課體系教材與個人手寫筆記全面整合，並內建 **PDF 即時在線閱讀器**，點擊即可直接於頁面內翻閱閱讀或下載！")

                    if combined_materials:
                        for m_idx, mat in enumerate(combined_materials):
                            m_tag = mat.get("tag", "【講義筆記】")
                            m_fn = mat.get("filename", "")
                            m_reason = mat.get("match_reason", "考科章節關聯")
                            m_path = mat.get("path", "")
                            m_size = mat.get("size_kb", 0)

                            with st.container():
                                st.markdown(f"**📄 `{m_tag}` 《{m_fn}》** (`{m_size}` KB)")
                                st.info(f"🎯 **關聯章節與考點標註**：{m_reason}")

                                # 內嵌 PDF 線上閱讀與下載
                                if m_path and Path(m_path).exists() and m_fn.lower().endswith(".pdf"):
                                    viewer_exp_key = f"exp_pdf_{idx}_{m_idx}"
                                    with st.expander(f"👁️ 點此直接在線展開閱讀 PDF 講義 / 手寫筆記全文（無需跳出）", expanded=False):
                                        try:
                                            with open(m_path, "rb") as f_pdf:
                                                pdf_bytes = f_pdf.read()
                                            b64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
                                            pdf_display = f'<iframe src="data:application/pdf;base64,{b64_pdf}" width="100%" height="600" type="application/pdf" style="border: 1px solid #ddd; border-radius: 8px;"></iframe>'
                                            st.markdown(pdf_display, unsafe_allow_html=True)
                                            st.download_button(
                                                label=f"💾 下載此份 PDF ({m_fn})",
                                                data=pdf_bytes,
                                                file_name=m_fn,
                                                mime="application/pdf",
                                                key=f"dl_pdf_{idx}_{m_idx}"
                                            )
                                        except Exception as pe:
                                            st.warning(f"PDF 讀取提示: {pe}")
                                            if Path(m_path).exists():
                                                with open(m_path, "rb") as fp:
                                                    st.download_button(f"💾 下載《{m_fn}》至本機閱讀", fp, file_name=m_fn, key=f"dl_fb_{idx}_{m_idx}")
                                elif m_path and Path(m_path).exists():
                                    with open(m_path, "rb") as fp:
                                        st.download_button(f"💾 下載《{m_fn}》", fp, file_name=m_fn, key=f"dl_non_pdf_{idx}_{m_idx}")

                                st.markdown("---")
                    else:
                        st.info(f"💡 目前您的資料庫中暫無直接對應【{lname} {ano}】之專屬課輔講義或個人讀書筆記。您可前往【模式 9：手寫筆記蒸餾與 SFT 模型微調大庫】上傳並自動歸納您的專屬讀書筆記！")

                with tab_ai:
                    ai_cache_key = f"ai_anno_{lname}_{ano}"
                    if st.button(f"✨ 啟動 AI 深度釋析（立法理由、主管機關函釋、通說有力說）", key=f"btn_run_anno_{idx}"):
                        with st.spinner(f"正在由 Gemini Flash 為【{lname} {ano}】生成立法沿革、法務部/金管會函釋與二試作答模版..."):
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
                        st.session_state["app_mode"] = MODE_EVAL
                        st.rerun()
                with act2:
                    if st.button(f"🔍 帶入法學檢索樞紐", key=f"btn_pass_query_{idx}", use_container_width=True):
                        st.session_state["ai_query_input_text"] = f"{lname} {ano} 相關核心爭點與實務裁判"
                        st.session_state["lp_search_query"] = f"{lname} {ano}"
                        st.session_state["lb_input_statute"] = f"{lname}第{ano}條"
                        st.session_state["m5_sub_mode_idx"] = 1
                        st.session_state["app_mode"] = MODE_SEARCH
                        st.rerun()
                with act3:
                    if st.button(f"📖 針對此法條出題/擬答", key=f"btn_pass_ans_{idx}", use_container_width=True):
                        st.session_state["m4_target_question"] = f"請針對【{lname} {ano}】之構成要件與實務重大爭議，設計一則二試案例題並給予上位卷擬答。\n條文：{content}"
                        st.session_state["app_mode"] = MODE_ANS
                        st.rerun()


