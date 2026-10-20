import streamlit as st
import os
import json
import re
from legal_qa_engine import (
    LegalQAEngine,
    LEGAL_CONSULTATION_DOMAINS,
    USER_STANDPOINTS,
    OUTPUT_MODES,
    QUERY_TYPES,
    calculate_vehicle_depreciation,
    calculate_severance_pay,
    calculate_marital_property_division,
    calculate_inheritance_shares,
    calculate_statutory_interest
)
from views.constants import MODE_SIX_CODES, MODE_SEARCH

def render_mode_qa():
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


