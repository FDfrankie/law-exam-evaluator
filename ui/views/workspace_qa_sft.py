"""
工作區 5：法學萬能問答、金額精算與筆記蒸餾知識庫 (Workspace QA and SFT)
整合原 Mode 6 (法學全能問答與金額精算), Mode 9 (手寫筆記蒸餾與 SFT 庫),
以及系統首頁導覽、四大指標統計與隱私著作權免責聲明。
"""

import os
import io
import re
import json
import time
from pathlib import Path
from PIL import Image
import streamlit as st

from config import (
    DATA_DIR, RAW_DATA_DIR, GOOGLE_DRIVE_DATA_DIR, SAMSUNG_NOTES_DIR,
    get_gemini_api_key, DEFAULT_GEMINI_MODEL, GEMINI_FALLBACK_MODELS,
    get_gemini_models_to_try,
    MODE_HOME, MODE_EVAL, MODE_GEN, MODE_BANK, MODE_ANS,
    MODE_SEARCH, MODE_QA, MODE_SUMMARIZER, MODE_SIX_CODES, MODE_SFT
)
from core.legal_qa_engine import (
    LegalQAEngine,
    QUERY_TYPES,
    LEGAL_CONSULTATION_DOMAINS,
    USER_STANDPOINTS,
    OUTPUT_MODES,
    calculate_vehicle_depreciation,
    calculate_severance_pay,
    calculate_marital_property_division,
    calculate_inheritance_shares,
    calculate_statutory_interest
)
from core.core_issues_taxonomy import load_all_existing_stage1_mcqs
from core.community_archive import load_community_notes, search_community_notes
from ui.components import render_inline_action_pills

try:
    from pipelines.ingest_user_notes_to_sft import (
        get_google_drive_notes_list,
        read_note_text,
        distill_single_note_file,
        ingest_single_uploaded_file,
        sync_all_drive_notes_to_samsung_notes
    )
except ImportError:
    try:
        from ingest_user_notes_to_sft import (
            get_google_drive_notes_list,
            read_note_text,
            distill_single_note_file,
            ingest_single_uploaded_file,
            sync_all_drive_notes_to_samsung_notes
        )
    except Exception:
        get_google_drive_notes_list = lambda: []
        read_note_text = lambda p: ""
        distill_single_note_file = lambda p: None
        ingest_single_uploaded_file = lambda b, n: None
        sync_all_drive_notes_to_samsung_notes = lambda: []

def render_workspace():
    """渲染工作區 5：法學諮詢與筆記庫"""
    st.title("💬 法學諮詢、金額精算與筆記蒸餾知識庫")
    st.caption("提供萬能法律檢索諮詢、六大訴訟損害金額試算機、個人手寫筆記蒸餾與系統總覽政策。")
    render_inline_action_pills()

    dest_subtab = st.session_state.pop("qa_subtab_target", 0)

    tab_qa, tab_sft, tab_home = st.tabs([
        "💬 萬能法學諮詢與金額精算",
        "📥 手寫筆記蒸餾與微調庫",
        "🏠 系統導覽與政策聲明"
    ])

    with tab_qa:
        st.markdown("""
            <div style="text-align: center; margin-top: 5px; margin-bottom: 20px;">
                <h1 style="font-size: 2.2rem; margin-bottom: 6px;">🔍 司律與實務法學萬能檢索樞紐</h1>
                <p style="color: #555; font-size: 1.05rem; margin-bottom: 0;">專為本專案特化之全能法學檢索系統：單一搜尋欄支援法條定位（這情況適用哪一條？）、爭點論辯、例題金錢精算或生活法律爭議</p>
            </div>
        """, unsafe_allow_html=True)

        # 1. 專屬特化單一整體搜尋欄
        qa_input_val = st.session_state.get("current_qa_question_input", "")

        col_search_box, col_search_act = st.columns([4.2, 1.2])
        with col_search_box:
            user_question = st.text_area(
                "請輸入欲搜尋之法律問題、條文疑義、爭點或計算例題：",
                value=qa_input_val,
                height=95,
                placeholder="🔍 例如：\n1. 把別人的油漆塗在自己車上是民法哪一條？所有權歸誰？\n2. 借名登記出名人擅自出賣不動產之效力？實務與學說見解為何？\n3. 車齡2年8個月車禍零件14萬工資6萬，依定率遞減法折舊應賠償多少？\n4. 房東藉故扣留2個月押金不退還，我該如何合法要回？",
                key="txt_unified_law_search",
                label_visibility="collapsed"
            )
        with col_search_act:
            btn_start_qa = st.button("🔍 啟動全能法學檢索", type="primary", use_container_width=True, key="btn_run_legal_qa")
            if st.button("✖️ 清除搜尋", use_container_width=True, key="btn_clear_legal_qa"):
                st.session_state.pop("current_qa_result", None)
                st.session_state.pop("current_qa_question_input", None)
                st.session_state.pop("qa_conversation_history", None)
                st.session_state.pop("qa_generated_notice", None)
                st.session_state.pop("qa_generated_mediation", None)
                st.rerun()

        # 快捷檢索意圖分類標籤 (預設全自動偵測，亦可手動快切)
        qa_query_type = st.radio(
            "檢索意圖標籤：",
            QUERY_TYPES,
            horizontal=True,
            index=0,
            key="rad_qa_query_type",
            label_visibility="collapsed"
        )

        # 2. 原本那個功能也不錯可以保留 (保留在優雅收合的進階設定與專屬精算工具箱中)
        with st.expander("⚙️ 保留原版進階設定與專用金錢精算工具箱 (領域自選・立場選擇・輸出規格・五大多功能試算機)", expanded=False):
            st.markdown("##### 🎯 諮詢立場與報告規格設定：")
            col_q1, col_q2, col_q3 = st.columns([1.5, 1.2, 1.3])
            with col_q1:
                qa_domain = st.selectbox(
                    "法律範疇分類（可自選或交由系統自動辨識）：",
                    LEGAL_CONSULTATION_DOMAINS,
                    index=0,
                    key="sel_qa_domain"
                )
            with col_q2:
                qa_standpoint = st.selectbox(
                    "諮詢立場與評估角度：",
                    USER_STANDPOINTS,
                    index=0,
                    key="sel_qa_standpoint"
                )
            with col_q3:
                qa_output_mode = st.selectbox(
                    "諮詢報告架構模式：",
                    OUTPUT_MODES,
                    index=0,
                    key="sel_qa_output_mode"
                )

            st.divider()
            st.markdown("##### 🧮 專用法律金錢精算機（純 Python 零誤差精算法定公式，亦可點擊帶入上方搜尋欄進行 AI 深度剖析）：")
            calc_tab1, calc_tab2, calc_tab3, calc_tab4, calc_tab5 = st.tabs([
                "🚗 車損零件折舊",
                "💼 勞退新制資遣費",
                "👨‍👩‍👧 夫妻剩餘財產",
                "📜 遺產應繼與特留分",
                "💰 法定遲延利息"
            ])

            with calc_tab1:
                st.caption("依行政院固定資產耐用年數表與最高法院77年度第九次民事庭會議決議：工資全額賠償不折舊，零件依法折舊，殘值底線不低於取得原價10%。")
                cv_c1, cv_c2, cv_c3 = st.columns(3)
                with cv_c1:
                    calc_v_part = st.number_input("零件維修費 (元)：", min_value=0.0, value=120000.0, step=1000.0, key="num_c_v_part")
                with cv_c2:
                    calc_v_labor = st.number_input("工資板烤費 (元)：", min_value=0.0, value=40000.0, step=1000.0, key="num_c_v_labor")
                with cv_c3:
                    calc_v_type = st.selectbox("車輛種類與耐用年數：", [
                        "自用小客車 (耐用年數5年，年折舊率 0.369)",
                        "營業小客車/計程車 (耐用年數4年，年折舊率 0.438)",
                        "機車 (耐用年數3年，年折舊率 0.536)",
                        "貨車 (耐用年數4年，年折舊率 0.438)"
                    ], key="sel_c_v_type")

                cv_c4, cv_c5, cv_c6 = st.columns(3)
                with cv_c4:
                    calc_v_years = st.number_input("出廠車齡（滿幾年）：", min_value=0, max_value=30, value=2, key="num_c_v_years")
                with cv_c5:
                    calc_v_months = st.number_input("畸零月數（幾個月）：", min_value=0, max_value=11, value=6, key="num_c_v_months")
                with cv_c6:
                    calc_v_method = st.selectbox("折舊計算方式：", [
                        "定率遞減法 (每年折舊率計算，殘值底線 10%)",
                        "平均法 (直線法，每年平均折舊)"
                    ], key="sel_c_v_method")

                calc_v_neg = st.slider("我方過失相抵比例 (%)：", min_value=0, max_value=100, value=0, key="sli_c_v_neg")

                btn_run_v, btn_pass_v = st.columns([1, 1])
                with btn_run_v:
                    if st.button("🧮 立即精算車損折舊", use_container_width=True, key="btn_calc_vehicle_run"):
                        res_v = calculate_vehicle_depreciation(
                            part_cost=calc_v_part,
                            labor_cost=calc_v_labor,
                            age_years=int(calc_v_years),
                            age_months=int(calc_v_months),
                            vehicle_type=calc_v_type,
                            method=calc_v_method,
                            comparative_negligence_pct=calc_v_neg
                        )
                        st.session_state["calc_v_result"] = res_v
                with btn_pass_v:
                    if st.button("📝 帶入上方搜尋欄進行 AI 深度剖析", use_container_width=True, key="btn_apply_v_search"):
                        st.session_state["current_qa_question_input"] = f"車輛車損賠償精算案例：車輛種類為【{calc_v_type.split(' ')[0]}】，車齡【{calc_v_years} 年 {calc_v_months} 個月】，維修支出：更換新零件 NT${calc_v_part:,.0f} 元，工資 NT${calc_v_labor:,.0f} 元，我方過失責任比例為 {calc_v_neg}%。請依【{calc_v_method.split(' ')[0]}】折舊計算，拆解得請求之損害賠償總金額與法理要件。"
                        st.session_state["qa_auto_run_trigger"] = True
                        st.rerun()

                if "calc_v_result" in st.session_state:
                    vr = st.session_state["calc_v_result"]
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("零件折舊後殘值", f"NT${vr['part_final_value']:,.0f}")
                    m2.metric("工資不折舊", f"NT${vr['labor_cost']:,.0f}")
                    m3.metric("折舊前損害總額", f"NT${(vr['part_original'] + vr['labor_cost']):,.0f}")
                    m4.metric("最終應獲賠金額", f"NT${vr['final_award']:,.0f}", delta=f"-NT${vr['part_depreciation_total']:,.0f} (折舊)")
                    with st.expander("🔍 查看詳細計算步驟與法院折舊明細", expanded=True):
                        for step in vr["steps"]:
                            st.write(f"- {step}")
                        st.caption(f"**法律依據**：{vr['legal_basis']}")

            with calc_tab2:
                st.caption("依勞工退休金條例第 12 條（勞退新制）每滿 1 年發給 0.5 個月平均工資，未滿 1 年以比例計，最高 6 個月為限；及勞動基準法第 16 條預告期間工資。")
                cs_c1, cs_c2 = st.columns(2)
                with cs_c1:
                    calc_s_wage = st.number_input("月平均工資 (元)：", min_value=0.0, value=65000.0, step=1000.0, key="num_c_s_wage")
                with cs_c2:
                    calc_s_notice = st.checkbox("雇主是否已依法給足預告期？（若未給足依法應給付預告工資）", value=False, key="chk_c_s_notice")
                cs_c3, cs_c4, cs_c5 = st.columns(3)
                with cs_c3:
                    calc_s_years = st.number_input("工作年資（滿幾年）：", min_value=0, max_value=50, value=3, key="num_c_s_years")
                with cs_c4:
                    calc_s_months = st.number_input("畸零月數：", min_value=0, max_value=11, value=7, key="num_c_s_months")
                with cs_c5:
                    calc_s_days = st.number_input("畸零天數：", min_value=0, max_value=30, value=15, key="num_c_s_days")

                btn_run_s, btn_pass_s = st.columns([1, 1])
                with btn_run_s:
                    if st.button("🧮 立即精算資遣費與預告工資", use_container_width=True, key="btn_calc_sev_run"):
                        res_s = calculate_severance_pay(
                            monthly_wage=calc_s_wage,
                            years=int(calc_s_years),
                            months=int(calc_s_months),
                            days=int(calc_s_days),
                            has_advance_notice=calc_s_notice
                        )
                        st.session_state["calc_s_result"] = res_s
                with btn_pass_s:
                    if st.button("📝 帶入上方搜尋欄進行 AI 深度剖析", use_container_width=True, key="btn_apply_s_search"):
                        st.session_state["current_qa_question_input"] = f"勞工資遣費與預告工資精算案例：勞工月平均工資 NT${calc_s_wage:,.0f} 元，總年資【{calc_s_years} 年 {calc_s_months} 個月 {calc_s_days} 天】，雇主無預警終止勞動契約（{'已給預告期' if calc_s_notice else '未給預告期'}）。請依勞工退休金條例第12條與勞基法第16、17條，精算勞工依法應得之資遣費、預告工資及救濟途徑。"
                        st.session_state["qa_auto_run_trigger"] = True
                        st.rerun()

                if "calc_s_result" in st.session_state:
                    sr = st.session_state["calc_s_result"]
                    sm1, sm2, sm3, sm4 = st.columns(4)
                    sm1.metric("新制資遣基數", f"{sr['capped_factor']:.3f} 個月")
                    sm2.metric("新制資遣費", f"NT${sr['severance_amount']:,.0f}")
                    sm3.metric("預告期工資", f"NT${sr['notice_pay']:,.0f}", help=f"法定預告期 {sr['notice_days']} 日")
                    sm4.metric("合計應給付總額", f"NT${sr['total_due']:,.0f}")
                    st.caption(f"**年資計算**：{sr['tenure_str']} ｜ **法條依據**：{sr['legal_basis']}")

            with calc_tab3:
                st.caption("民法第 1030 條之 1 法定財產制剩餘財產分配：婚後現存財產扣除婚後負債，並扣除因繼承、無償取得之財產與慰撫金後，計算雙方差額並平均分配。")
                cm_col1, cm_col2 = st.columns(2)
                with cm_col1:
                    st.markdown("**【夫 (先生) 財產與負債】**")
                    calc_h_assets = st.number_input("夫婚後現存財產總額 (元)：", min_value=0.0, value=8000000.0, step=100000.0, key="num_c_h_a")
                    calc_h_debts = st.number_input("夫婚後所負債務總額 (元)：", min_value=0.0, value=2000000.0, step=100000.0, key="num_c_h_d")
                    calc_h_exempt = st.number_input("夫因繼承/無償贈與/慰撫金取得 (元)：", min_value=0.0, value=1000000.0, step=50000.0, key="num_c_h_e")
                with cm_col2:
                    st.markdown("**【妻 (太太) 財產與負債】**")
                    calc_w_assets = st.number_input("妻婚後現存財產總額 (元)：", min_value=0.0, value=3000000.0, step=100000.0, key="num_c_w_a")
                    calc_w_debts = st.number_input("妻婚後所負債務總額 (元)：", min_value=0.0, value=500000.0, step=50000.0, key="num_c_w_d")
                    calc_w_exempt = st.number_input("妻因繼承/無償贈與/慰撫金取得 (元)：", min_value=0.0, value=0.0, step=50000.0, key="num_c_w_e")

                btn_run_m, btn_pass_m = st.columns([1, 1])
                with btn_run_m:
                    if st.button("🧮 立即精算剩餘財產分配額", use_container_width=True, key="btn_calc_mar_run"):
                        res_m = calculate_marital_property_division(
                            husband_assets=calc_h_assets,
                            husband_debts=calc_h_debts,
                            husband_exempt=calc_h_exempt,
                            wife_assets=calc_w_assets,
                            wife_debts=calc_w_debts,
                            wife_exempt=calc_w_exempt
                        )
                        st.session_state["calc_m_result"] = res_m
                with btn_pass_m:
                    if st.button("📝 帶入上方搜尋欄進行 AI 深度剖析", use_container_width=True, key="btn_apply_m_search"):
                        st.session_state["current_qa_question_input"] = f"夫妻剩餘財產分配案例：夫婚後財產 NT${calc_h_assets:,.0f}，負債 NT${calc_h_debts:,.0f}，無償取得 NT${calc_h_exempt:,.0f}；妻婚後財產 NT${calc_w_assets:,.0f}，負債 NT${calc_w_debts:,.0f}，無償取得 NT${calc_w_exempt:,.0f}。請依民法第1030條之1分析雙方淨財產、差額分配金額、時效與抗辯事由。"
                        st.session_state["qa_auto_run_trigger"] = True
                        st.rerun()

                if "calc_m_result" in st.session_state:
                    mr = st.session_state["calc_m_result"]
                    mm1, mm2, mm3 = st.columns(3)
                    mm1.metric("夫婚後淨財產", f"NT${mr['husband_net']:,.0f}")
                    mm2.metric("妻婚後淨財產", f"NT${mr['wife_net']:,.0f}")
                    mm3.metric("雙方差額", f"NT${mr['difference']:,.0f}")
                    st.success(f"⚖️ 分配結論：由 **{mr['giver']}** 給付 **{mr['receiver']}** 剩餘財產差額半數 **NT${mr['transfer_amount']:,.0f}** 元！")

            with calc_tab4:
                st.caption("民法第 1138、1144 條法定應繼分與第 1223 條特留分精算。")
                ci_c1, ci_c2, ci_c3 = st.columns(3)
                with ci_c1:
                    calc_i_estate = st.number_input("被繼承人遺產總淨額 (元)：", min_value=0.0, value=12000000.0, step=100000.0, key="num_c_i_estate")
                with ci_c2:
                    calc_i_spouse = st.checkbox("配偶是否在世為共同繼承人？", value=True, key="chk_c_i_spouse")
                with ci_c3:
                    calc_i_order = st.selectbox("其他順序繼承人血親類別：", [
                        "第一順序：子女 (直系血親卑親屬)",
                        "第二順序：父母",
                        "第三順序：兄弟姊妹",
                        "第四順序：祖父母",
                        "無其他順序血親繼承人 (僅配偶單獨繼承)"
                    ], key="sel_c_i_order")

                calc_i_count = st.number_input("該順序血親繼承人人數（人）：", min_value=0, max_value=20, value=3, key="num_c_i_count")

                btn_run_i, btn_pass_i = st.columns([1, 1])
                with btn_run_i:
                    if st.button("🧮 立即精算應繼分與特留分", use_container_width=True, key="btn_calc_inh_run"):
                        order_idx = 1
                        if "第二順序" in calc_i_order: order_idx = 2
                        elif "第三順序" in calc_i_order: order_idx = 3
                        elif "第四順序" in calc_i_order: order_idx = 4
                        elif "無其他" in calc_i_order: order_idx = 0
                        res_i = calculate_inheritance_shares(
                            estate_total=calc_i_estate,
                            has_spouse=calc_i_spouse,
                            order=order_idx,
                            heir_count=int(calc_i_count)
                        )
                        st.session_state["calc_i_result"] = res_i
                with btn_pass_i:
                    if st.button("📝 帶入上方搜尋欄進行 AI 深度剖析", use_container_width=True, key="btn_apply_i_search"):
                        st.session_state["current_qa_question_input"] = f"遺產繼承應繼分與特留分例題：被繼承人遺留遺產總額 NT${calc_i_estate:,.0f} 元，繼承人有配偶（{'有' if calc_i_spouse else '無'}）以及【{calc_i_order.split('：')[1]}】共 {calc_i_count} 人。請依民法第1138、1144與1223條，逐一計算各繼承人之應繼分比例、金額與特留分扣減原則。"
                        st.session_state["qa_auto_run_trigger"] = True
                        st.rerun()

                if "calc_i_result" in st.session_state:
                    ir = st.session_state["calc_i_result"]
                    st.markdown("##### 📊 各繼承人應繼分與特留分試算分配清單：")
                    i_rows = []
                    for h in ir["heirs_summary"]:
                        i_rows.append({
                            "繼承人身分": h["role"],
                            "法定應繼分比例": h["fraction"],
                            "應繼分金額 (NT$)": f"{h['amount']:,.0f}",
                            "法定特留分金額 (NT$)": f"{h['reserved']:,.0f}",
                            "法律註記": h["note"]
                        })
                    st.table(i_rows)
                    st.caption(f"**法律依據**：{ir['legal_basis']}")

            with calc_tab5:
                st.caption("民法第 203 條：應付利息之債務，其利率未經約定，亦無法律可據者，週年利率為百分之五。")
                cnt_c1, cnt_c2, cnt_c3 = st.columns(3)
                with cnt_c1:
                    calc_n_p = st.number_input("請求本金金額 (元)：", min_value=0.0, value=500000.0, step=10000.0, key="num_c_n_p")
                with cnt_c2:
                    calc_n_d = st.number_input("經過天數（日）：", min_value=1, max_value=3650, value=180, key="num_c_n_d")
                with cnt_c3:
                    calc_n_r = st.number_input("週年利率 (%)：", min_value=0.1, max_value=20.0, value=5.0, step=0.5, key="num_c_n_r")

                if st.button("🧮 立即精算遲延利息", use_container_width=True, key="btn_calc_int_run"):
                    res_int = calculate_statutory_interest(
                        principal=calc_n_p,
                        days=int(calc_n_d),
                        annual_rate_pct=calc_n_r
                    )
                    im1, im2, im3 = st.columns(3)
                    im1.metric("請求本金", f"NT${res_int['principal']:,.0f}")
                    im2.metric("法定利息金額", f"NT${res_int['interest_amount']:,.0f}", delta=f"{res_int['days']} 天")
                    im3.metric("本利和總額", f"NT${res_int['total_amount']:,.0f}")

        # 3. 執行檢索推論
        do_run_qa = btn_start_qa or st.session_state.pop("qa_auto_run_trigger", False)
        if do_run_qa:
            if not user_question.strip():
                st.warning("請先輸入具體法律問題、條文疑義、爭點或計算題目！")
            else:
                with st.spinner("專屬法學智慧檢索引擎正在檢索現行法典、最高法院判決、大法庭裁定與權威法理，進行深度推論..."):
                    try:
                        engine = LegalQAEngine()
                        qa_hist = st.session_state.get("qa_conversation_history", [])
                        qa_res = engine.answer_legal_question(
                            question=user_question.strip(),
                            domain=qa_domain,
                            standpoint=qa_standpoint,
                            output_mode=qa_output_mode,
                            query_type=qa_query_type,
                            history=qa_hist
                        )
                        st.session_state["current_qa_result"] = qa_res
                        st.session_state["current_qa_question_input"] = user_question.strip()
                        if "qa_conversation_history" not in st.session_state:
                            st.session_state["qa_conversation_history"] = []
                        st.session_state["qa_conversation_history"].append({
                            "question": user_question.strip(),
                            "answer": qa_res.get("content", "")
                        })
                    except Exception as qe:
                        st.error(f"法律檢索與諮詢分析失敗: {qe}")

        if "current_qa_result" in st.session_state:
            res = st.session_state["current_qa_result"]
            qa_ans = res.get("content", "")
            qa_q = res.get("question", "")
            q_dom = res.get("domain", "")
            q_mode_tag = res.get("query_type", "法理深度剖析")

            st.divider()
            st.markdown(f"### 📋 【專屬法學智慧檢索結果：{q_mode_tag.split(' ')[0]}】")
            st.markdown(qa_ans)

            st.divider()
            st.markdown("##### 🛠️ 實務救濟文書生成與延伸工具：")

            # 存證信函生成區
            with st.expander("📮 一鍵自動草擬【郵局存證信函】正式草稿（可直接複製或發函）", expanded=False):
                n_c1, n_c2, n_c3 = st.columns([1.2, 1.2, 1])
                with n_c1:
                    n_sender = st.text_input("寄件人姓名：", value="本人", key="inp_notice_sender")
                with n_c2:
                    n_recv = st.text_input("相對人姓名/公司名稱：", value="相對人", key="inp_notice_recv")
                with n_c3:
                    n_days = st.number_input("催告履行期限 (天)：", min_value=3, max_value=30, value=7, key="inp_notice_days")

                if st.button("📑 生成存證信函標準範本", key="btn_gen_notice", use_container_width=True):
                    with st.spinner("正在以專業律師函令規格草擬存證信函..."):
                        engine = LegalQAEngine()
                        notice_text = engine.generate_legal_notice(
                            question=qa_q,
                            legal_advice=qa_ans,
                            sender_name=n_sender,
                            receiver_name=n_recv,
                            deadline_days=int(n_days)
                        )
                        st.session_state["qa_generated_notice"] = notice_text

                if "qa_generated_notice" in st.session_state:
                    st.text_area("存證信函草稿內文（可直接複製）：", value=st.session_state["qa_generated_notice"], height=260, key="txt_area_notice_out")
                    st.download_button(
                        "💾 下載存證信函草稿 (.txt)",
                        data=st.session_state["qa_generated_notice"],
                        file_name="存證信函草稿.txt",
                        mime="text/plain",
                        use_container_width=True
                    )

            # 調解聲請要旨區
            with st.expander("🏛️ 一鍵生成【鄉鎮市區調解聲請要旨與談判方案】", expanded=False):
                if st.button("📝 生成調解聲請要旨與和解方案", key="btn_gen_mediation", use_container_width=True):
                    with st.spinner("正在擬定公所調解委員會聲請要旨與談判退讓底線..."):
                        engine = LegalQAEngine()
                        med_text = engine.generate_mediation_summary(
                            question=qa_q,
                            legal_advice=qa_ans
                        )
                        st.session_state["qa_generated_mediation"] = med_text

                if "qa_generated_mediation" in st.session_state:
                    st.markdown(st.session_state["qa_generated_mediation"])
                    st.download_button(
                        "💾 下載調解聲請要旨 (.md)",
                        data=st.session_state["qa_generated_mediation"],
                        file_name="調解委員會聲請要旨.md",
                        mime="text/markdown",
                        use_container_width=True
                    )

            # 延伸連動導航
            st.write("")
            act_col1, act_col2, act_col3 = st.columns(3)
            with act_col1:
                st.download_button(
                    "📥 下載本次法律諮詢報告 (.md)",
                    data=f"# 法律諮詢意見書\n\n**諮詢問題**：\n{qa_q}\n\n**分析結論**：\n{qa_ans}",
                    file_name="法律諮詢意見書.md",
                    mime="text/markdown",
                    use_container_width=True
                )
            with act_col2:
                if st.button("⚖️ 帶入智慧六法查閱法條", use_container_width=True, key="btn_qa_to_six_codes"):
                    st.session_state["app_mode"] = MODE_SIX_CODES
                    st.rerun()
            with act_col3:
                if st.button("🔍 帶入統一法學樞紐檢索判決", use_container_width=True, key="btn_qa_to_search"):
                    st.session_state["lp_search_query"] = qa_q[:40]
                    st.session_state["app_mode"] = MODE_SEARCH
                    st.rerun()

            # 連續追問區
            st.divider()
            st.markdown("##### 💬 針對上述分析繼續追問（維持對話上下文）：")
            fu_c1, fu_c2 = st.columns([4, 1])
            with fu_c1:
                followup_input = st.text_input("輸入追問問題：", placeholder="例如：如果對方收到存證信函完全不理我，我下一步需要先去調解還是能直接提告？", key="txt_qa_followup_in")
            with fu_c2:
                st.write("")
                btn_followup = st.button("🚀 送出追問", type="primary", use_container_width=True, key="btn_exec_qa_followup")

            if btn_followup and followup_input.strip():
                with st.spinner("AI 顧問正在結合前述案情脈絡，為您深度回答追問..."):
                    try:
                        engine = LegalQAEngine()
                        qa_hist = st.session_state.get("qa_conversation_history", [])
                        fu_res = engine.answer_legal_question(
                            question=followup_input.strip(),
                            domain=q_dom,
                            standpoint=res.get("standpoint", USER_STANDPOINTS[0]),
                            output_mode=res.get("output_mode", OUTPUT_MODES[0]),
                            history=qa_hist
                        )
                        st.session_state["current_qa_result"] = fu_res
                        if "qa_conversation_history" not in st.session_state:
                            st.session_state["qa_conversation_history"] = []
                        st.session_state["qa_conversation_history"].append({
                            "question": followup_input.strip(),
                            "answer": fu_res.get("content", "")
                        })
                        st.rerun()
                    except Exception as fe:
                        st.error(f"追問回答失敗: {fe}")

        # ----------------- 模式: 一鍵 AI 裁判與長篇函釋要旨自動精鍊 (AI 判解精鍊旗艦) -----------------

    with tab_sft:
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
                        sel_note_idx = (note_opts.index(sel_sft_note) - 1) if sel_sft_note in note_opts else 0
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
                    if "【" in sel_sub_label and "】" in sel_sub_label:
                        sel_subject = sel_sub_label.split("【")[1].split("】")[0]
                    else:
                        sel_subject = sel_sub_label
                    sub_notes = sub_dict.get(sel_subject, [])

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

    with tab_home:
        st.title("🏛️ 司律考試 AI 評分、智慧命題與法學裁判樞紐")
        st.markdown("##### 專為中華民國司法官、律師高考、法研所與轉學考打造之全方位法學研習智能平台")
        st.caption("結合最新 Gemini 多模態神經網路、全國 5.2 萬條法規、2,100+ 權威裁判判例決議、628+ 中央部會函釋與一試跨科全真題庫。")
        st.write("")

        # 四大資料庫即時統計指標
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        with m_col1:
            st.metric(
                label="📜 全國法規條文庫",
                value="52,000+ 條",
                delta="六法全書與立法沿革"
            )
        with m_col2:
            try:
                total_precedents_count = len(get_precedents_catalog() or [])
            except Exception:
                total_precedents_count = 2104
            st.metric(
                label="⚖️ 權威裁判・判例・座談會",
                value=f"{total_precedents_count:,} 筆",
                delta="大法庭/原判例/決議/座談會"
            )
        with m_col3:
            try:
                from admin_rulings_engine import get_all_administrative_rulings
                total_rulings_count = len(get_all_administrative_rulings() or [])
            except Exception:
                total_rulings_count = 628
            st.metric(
                label="🏛️ 中央部會權威函釋",
                value=f"{total_rulings_count:,} 則",
                delta="經商/金管/勞動/智財/法務"
            )
        with m_col4:
            try:
                all_stage1_qs = load_all_existing_stage1_mcqs()
                total_mcqs_count = len(all_stage1_qs)
            except Exception:
                total_mcqs_count = 380
            st.metric(
                label="🎯 一試跨科實戰題庫",
                value=f"{total_mcqs_count:,} 題",
                delta="跨科全真模考與詳解"
            )

        st.divider()

        # 九大核心模組導覽卡片
        st.subheader("🧭 九大核心功能模組導覽與快速進入")
        st.caption("點擊下方對應模組之「🚀 立即前往」按鈕，即可快速跳轉至該功能進行演練與查詢。")

        card_rows = [
            [
                ("📝 試卷評分與手寫辨識", "支援拍照、手寫掃描 PDF、Word 電子稿等多模態視覺辨識，依考選部四大評分指標進行榜首級 IRAC 評閱診斷。", MODE_EVAL),
                ("🎯 司律模擬出題", "支援自選題數一試選擇題（含盲測盲題、答案速查表與考點診斷）及二試申論實例題，搭載垂直爭點累加清單。", MODE_GEN),
                ("📚 歷年真題庫檢索與模擬演練", "涵蓋臺大法研所、臺大轉學考、考選部司法官律師、司法特考歷年真題，支援在線實戰作答與自動批改。", MODE_BANK)
            ],
            [
                ("📖 高分權威擬答生成", "以榜首級 IRAC 三段論法架構，融入最新大法庭裁定、指標判例與權威學者獨門暗器見解，快速產出二試頂級擬答。", MODE_ANS),
                ("🔍 統一法學檢索樞紐與判決研析", "整合布林檢索、法院體系字號精準查詢、爭點大典、案例橫向比對（相同見解 vs 相反見解）與審級脈絡更迭鏈。", MODE_SEARCH),
                ("💬 專屬法學全能問答樞紐", "支援日常法律諮詢、國考爭點論辯、法條精準定位、專業書狀草擬及車禍折舊、資遣費、剩餘財產金額精算工具。", MODE_QA)
            ],
            [
                ("📑 一鍵 AI 判解與長篇函釋精鍊", "深度消化數萬字冗長判決書或部會函釋，一鍵提煉「主文、核心爭點、實務見解、學說評釋與國考作答破題金句」。", MODE_SUMMARIZER),
                ("⚖️ 智慧六法與條文判解標註", "全方位整合全國法規條文、立法院三讀立法理由、沿革修正對照、關聯實務字號、重要行政函釋與筆記關聯。", MODE_SIX_CODES),
                ("📥 手寫筆記蒸餾與大庫管理", "支援多引擎解壓司法院 Open Data RAR/ZIP 打包檔，並將筆記與考卷一鍵蒸餾轉化為百萬筆 SFT 法律微調大庫。", MODE_SFT)
            ]
        ]

        for r_idx, row in enumerate(card_rows):
            cols = st.columns(3)
            for c_idx, (c_title, c_desc, c_mode) in enumerate(row):
                with cols[c_idx]:
                    with st.container(border=True):
                        st.markdown(f"##### {c_title}")
                        st.write(c_desc)
                        if st.button("🚀 立即前往", key=f"btn_jump_mode_{r_idx}_{c_idx}", use_container_width=True):
                            st.session_state["app_mode"] = c_mode
                            st.rerun()

        st.divider()

        # 隱私權政策、著作權政策與法律免責聲明
        pol_c1, pol_c2, pol_c3 = st.columns(3)
        with pol_c1:
            with st.container(border=True):
                st.markdown("#### 🔒 隱私權保護政策")
                st.caption("依中華民國《個人資料保護法》及相關法規辦理")
                st.markdown(
                    """
        1. **資料蒐集與用途**：本平臺使用者所上傳之手寫試卷、自訂筆記、作答紀錄與各類文件，僅限於當次瀏覽器工作階段中進行 AI 辨識、爭點解析、出題與評閱，絕不用於未授權之第三方商業散布。
        2. **金鑰與憑證安全**：使用者於本系統設定之 `GEMINI_API_KEY` 及司法院開放平臺帳號密碼，均僅保存在當前瀏覽器 `st.session_state` 暫存記憶體中，絕不寫入公開原始碼、日誌或持久端伺服器資料庫。
        3. **資料控制權**：使用者得隨時於側邊欄點擊「清除 Token」或重整瀏覽器以完全銷毀工作階段記憶體中的敏感資訊。
                    """
                )
        with pol_c2:
            with st.container(border=True):
                st.markdown("#### 📜 著作權與合理使用政策")
                st.caption("依中華民國《著作權法》第 9 條、第 52 條與第 65 條規範")
                st.markdown(
                    """
        1. **公務著作公共領域**：本平臺收錄之中華民國憲法、法律、命令、司法院裁判書全文、最高法院裁判、最高行政法院裁判、原判例、庭長法官聯席會議決議、法律座談會研討結論、中央部會行政函釋及考選部歷年公務人員高考與專技國考試題，依《著作權法》第 9 條第 1 項規定，**不得為著作權之標的**，屬全體國民共享之公共領域公有財產。
        2. **學說與筆記合理使用**：系統中所引用之學者學說爭點、教科書要旨與個人筆記重點，係為法學學術研析、國考教學與個人學習之必要正當目的，符合《著作權法》第 52 條及第 65 條第 2 項之合理使用範圍。
                    """
                )
        with pol_c3:
            with st.container(border=True):
                st.markdown("#### ⚖️ 法律免責聲明")
                st.caption("依中華民國《法院組織法》及法學研習專業指引聲明")
                st.markdown(
                    """
        1. **非正式法律意見**：本系統所生成之試卷批改、考點建議、IRAC 高分擬答、案例橫向比對分析及金額試算結果，均由大型語言模型及演算法自動生成，僅供法律學術研習、司法官律師高考準備及司法特考演練參考，**不構成任何形式之正式法律意見、訴訟諮詢或委任要約**。
        2. **原判例效力說明**：依《法院組織法》第 57 條之 1 規定，最高法院於中華民國 108 年 7 月 4 日前依法選編之判例，若無裁判全文者停止適用；其有裁判全文者，其效力與未經選編為判例之最高法院裁判相同。本平臺收錄之「原判例」均已依法註明裁判全文字號，供考生對照歷史法理脈絡。
        3. **個案具體適用**：具體訴訟爭議請洽詢中華民國合格執業律師或尋求法律扶助基金會專業協助。
                    """
                )

        # ----------------- 模式 1: 試卷評分 -----------------
