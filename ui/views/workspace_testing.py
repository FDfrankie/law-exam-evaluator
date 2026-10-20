"""
工作區 2：司律模擬命題與盲測演練 (Workspace Testing)
涵蓋一試客製選擇題、二試高難度申論題、手寫筆記客製出題、
垂直累加考點清單，以及 300+ 題全真跨科實戰題庫盲測。
"""

import os
import io
import re
import json
import random
from pathlib import Path
import streamlit as st

from config import (
    DATA_DIR, RAW_DATA_DIR, SAMSUNG_NOTES_DIR,
    get_gemini_api_key, DEFAULT_GEMINI_MODEL, GEMINI_FALLBACK_MODELS
)
from core.exam_generator import LawExamGenerator
from core.core_issues_taxonomy import (
    LAW_DOMAIN_TAXONOMY,
    get_subject_topics_taxonomy,
    load_all_existing_stage1_mcqs,
    load_all_drive_notes
)
from ui.components import render_inline_action_pills

def render_workspace():
    """渲染工作區 2：模擬命題與盲測"""
    st.title("🎯 司律模擬命題與實戰演練")
    st.caption("結合名師體系爭點大庫、個人手寫筆記與 300+ 題全真跨科題庫，全方位檢測考生實戰實力。")
    render_inline_action_pills()

    st.header("🎯 司律考試模擬命題系統（一試選擇 / 二試申論實例題）")
    st.write("可放入個人手寫/打字讀書筆記、指定考科與考點，由法學大模型為您量身打造司律一試選擇題或二試實例申論題。")

    stage = st.radio("選擇考試階段：", ["一試 (選擇題 / 單選題)", "二試 (申論實例題)"], horizontal=True)

    col_sub1, col_sub2 = st.columns([1, 1])
    with col_sub1:
        st.markdown("##### 🏛️ 第一步：選擇考試學門與科目")
        domain_choice = st.selectbox(
            "考科學門體系分類篩選：",
            list(LAW_DOMAIN_TAXONOMY.keys()),
            key="sel_exam_domain_filter"
        )
        subjects_list = LAW_DOMAIN_TAXONOMY.get(domain_choice) or list(LAW_DOMAIN_TAXONOMY.values())[0]
        subject_choice = st.selectbox("考試科目：", subjects_list, key="sel_exam_subject_choice")
        if subject_choice == "其他自訂學門":
            subject = st.text_input("請輸入自訂科目名稱：", value="民事法學")
        else:
            subject = subject_choice.split(" ")[0]

    with col_sub2:
        st.markdown("##### 🎯 第二步：設定核心考點爭點與客製化出題範圍")
        list_key = f"exam_vertical_items_list_{subject}"
        if list_key not in st.session_state:
            st.session_state[list_key] = []

        available_topics_map = get_subject_topics_taxonomy(subject)
        topic_options = ["-- 💡 點此下拉挑選核心考點加入命題列表 --"] + list(available_topics_map.keys())
        selected_topic_choice = st.selectbox(
            f"依【{subject}】點選核心考點爭點（選取後自動累加至下方列表）：",
            options=topic_options,
            key=f"sel_topic_dropdown_{subject}"
        )
        if selected_topic_choice != topic_options[0]:
            t_desc = available_topics_map.get(selected_topic_choice, selected_topic_choice)
            full_item_str = f"{selected_topic_choice}（{t_desc}）"
            if full_item_str not in st.session_state[list_key]:
                st.session_state[list_key].append(full_item_str)
            st.rerun()

        with st.expander("🛠️ 客製化命題範圍設定與自訂考點新增（章節・法條・專案主題）", expanded=False):
            col_sc1, col_sc2, col_sc3 = st.columns([1.2, 1.8, 1])
            with col_sc1:
                scope_mode = st.selectbox(
                    "命題範圍類型：",
                    ["📜 特定法條/條文區間", "📚 特定編次/章節專題", "🏛️ 實務見解專題", "✏️ 自訂命題範圍"],
                    key=f"sel_scope_type_{subject}"
                )
            with col_sc2:
                custom_scope_in = st.text_input(
                    "指定客製化範圍明細：",
                    placeholder="例如：民法第179~198條債各、刑法第12~31條犯罪論...",
                    key=f"inp_custom_scope_{subject}"
                )
            with col_sc3:
                st.write("")
                if st.button("➕ 加入列表", use_container_width=True, key=f"btn_add_scope_{subject}"):
                    if custom_scope_in.strip():
                        item_s = f"【{scope_mode}】：{custom_scope_in.strip()}"
                        if item_s not in st.session_state[list_key]:
                            st.session_state[list_key].append(item_s)
                        st.rerun()

            col_adhoc_in, col_adhoc_btn = st.columns([3, 1])
            with col_adhoc_in:
                adhoc_in = st.text_input(
                    "自訂考點關鍵字：",
                    placeholder="例如：108台上大1719、不純正不作為犯保證人地位、違約定金酌減...",
                    key=f"inp_adhoc_{subject}"
                )
            with col_adhoc_btn:
                st.write("")
                if st.button("➕ 新增考點", use_container_width=True, key=f"btn_add_adhoc_{subject}"):
                    if adhoc_in.strip():
                        item_a = f"【自訂考點】：{adhoc_in.strip()}"
                        if item_a not in st.session_state[list_key]:
                            st.session_state[list_key].append(item_a)
                        st.rerun()

        # 垂直向下累加列表渲染 (有框容器)
        current_items = st.session_state[list_key]
        st.markdown(f"**📋 目前已設定命題爭點與範圍列表（共 {len(current_items)} 項）：**")
        with st.container(border=True):
            if not current_items:
                st.caption("（尚未加入任何考點，請從上方下拉選單選取，或自訂新增；若留空系統將進行全科目綜合出題）")
            else:
                for idx, it in enumerate(current_items):
                    r_col_text, r_col_del = st.columns([5, 1])
                    with r_col_text:
                        st.markdown(f"**{idx + 1}.** {it}")
                    with r_col_del:
                        if st.button("🗑️ 刪除", key=f"btn_del_topic_{subject}_{idx}", use_container_width=True):
                            st.session_state[list_key].pop(idx)
                            st.rerun()

                st.write("")
                if st.button("🗑️ 清空全部列表項目", key=f"btn_clear_all_topics_{subject}"):
                    st.session_state[list_key] = []
                    st.rerun()

    # 自動組合 topic 傳入出題引擎（移除筆記區塊）
    if current_items:
        topic = "、".join([re.sub(r'^[【].*?[】]：?', '', it).split('（')[0] for it in current_items])
    else:
        topic = f"{subject}核心實務爭點與法規構成要件"
    final_notes = None

    if stage == "一試 (選擇題 / 單選題)":
        stage1_tab_ai, stage1_tab_300 = st.tabs([
            "🎲 AI 智慧命題模式（任意題數 & 支援手寫筆記 OCR 客製出題）",
            "📖 司律一試 300+ 題全真跨科模擬題庫（民・刑・公・商跨科即時測驗）"
        ])

        with stage1_tab_ai:
            st.markdown("#### ⚙️ AI 一試出題參數設定（比照 300 題模擬題庫規格）")
            qcol1, qcol2 = st.columns(2)
            with qcol1:
                q_mode = st.selectbox(
                    "題型結構模式：",
                    ["標準單選題 (案例情境盲測)", "綜合案例實事實務題組題 (跨子題)", "全真綜合模考卷 (混合題型)"]
                )
            with qcol2:
                q_count_option = st.selectbox(
                    "出題題數：",
                    ["5 題 (隨堂測驗)", "10 題 (標準單元測)", "15 題 (強化題組)", "20 題 (大型模考卷)", "30 題 (全真模擬題庫)", "50 題 (半套模考卷)", "100 題 (全真一試大卷)", "自訂題數"],
                    key="ai_q_count_select"
                )
                if q_count_option == "自訂題數":
                    q_count = st.number_input("請輸入自訂題數 (1~100 題)：", min_value=1, max_value=100, value=10, key="ai_custom_q_count")
                else:
                    q_count = int(q_count_option.split(" ")[0])

            if st.button("🎲 開始生成一試全真模擬測驗題卷", type="primary", use_container_width=True):
                target_topic = topic.strip() if topic.strip() else "核心實務爭點與法規構成要件"

                progress_bar = st.progress(0)
                status_text = st.empty()
                status_text.text(f"正在以司律一試命題規格批次生成 {q_count} 題，每批 5 題穩定出題中...")

                def update_progress(curr, tot):
                    progress_bar.progress(min(1.0, curr / tot))
                    status_text.text(f"已完成 {curr} / {tot} 題...")

                try:
                    gen = LawExamGenerator()
                    exam_res = gen.generate_stage1_exam(
                        subject=subject,
                        topic=target_topic,
                        count=q_count,
                        question_mode=q_mode,
                        notes_content=final_notes if final_notes else None,
                        progress_callback=update_progress
                    )
                    progress_bar.progress(1.0)
                    status_text.success(f"🎉 成功生成【{subject}】共 {len(exam_res.get('questions', []))} 題司律一試測驗卷！")
                    st.session_state["stage1_exam_data"] = exam_res

                except Exception as e:
                    st.error(f"出題失敗: {e}")

        with stage1_tab_300:
            st.markdown("#### 📖 司律一試 300+ 題全真跨科模擬題庫（涵蓋民法・刑法・憲法・行政法・民訴・刑訴・商事法）")
            st.write("全面收錄**行政法 300 題完整題庫**與**民法、刑法、憲法、民事訴訟法、刑事訴訟法、商事法 86 題跨科全真題目**，題題具備情境案例事實、四大嚴謹選項與 IRAC 權威實務見解解析（憲法判決、最高法院大法庭裁定、指標性重大原判例）。支援單科專精衝刺或全科跨領域大模考！")

            all_bank_mcqs = load_all_existing_stage1_mcqs()

            c300_col1, c300_col2, c300_col3 = st.columns([1.2, 1.2, 1])
            with c300_col1:
                sel_domain_filter = st.selectbox(
                    "1. 選擇測驗科目範圍：",
                    [
                        "🌟 全部既有題庫跨科隨機抽考",
                        "🏛️ 民法 (總則・債編・物權・親屬繼承)",
                        "⚖️ 刑法 (總則犯罪論・刑罰論・分則財產與生命法益)",
                        "📜 憲法 (基本權利違憲審查・正當法律程序・權力分立)",
                        "📑 行政法 (300 題模擬題庫・行政處分・行政契約・行政爭訟)",
                        "💼 民事訴訟法 (當事人適格・訴訟標的・爭點效・既判力)",
                        "🔍 刑事訴訟法 (強制處分令狀・科技偵查・證據排除・傳聞法則)",
                        "🏢 商事法 (公司負責人義務・內線交易・保險告知義務)"
                    ],
                    key="sel_stage1_bank_domain"
                )

            # 依科目精準過濾試題池
            if sel_domain_filter == "🌟 全部既有題庫跨科隨機抽考":
                subject_pool = all_bank_mcqs
            elif "民法" in sel_domain_filter and "民事訴訟法" not in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "民法"]
            elif "刑法" in sel_domain_filter and "刑事訴訟法" not in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "刑法"]
            elif "憲法" in sel_domain_filter and "行政法" not in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "憲法"]
            elif "行政法" in sel_domain_filter and "憲法" not in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if "行政" in q.get("subject", "")]
            elif "民事訴訟法" in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "民事訴訟法"]
            elif "刑事訴訟法" in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "刑事訴訟法"]
            elif "商事法" in sel_domain_filter:
                subject_pool = [q for q in all_bank_mcqs if q.get("subject") == "商事法"]
            else:
                subject_pool = [q for q in all_bank_mcqs if sel_domain_filter in q.get("subject", "") or sel_domain_filter in q.get("major_domain", "")]

            # 動態彙整該科目下所屬的考點分類
            raw_pool_cats = sorted(list({q.get("category", "").strip() for q in subject_pool if q.get("category")}))
            cat_options = [f"全部考點分類 (不限，此科目共 {len(subject_pool)} 題)"] + raw_pool_cats

            with c300_col2:
                cat_300_choice = st.selectbox(
                    "2. 考點分類專題篩選：",
                    cat_options,
                    key=f"sel_cat_300_choice_{sel_domain_filter[:4]}"
                )

            with c300_col3:
                count_300_choice = st.selectbox(
                    "3. 抽題題數：",
                    ["5 題 (快速隨測)", "10 題 (標準測驗)", "15 題 (綜合考卷)", "20 題 (大模考)", "30 題 (全卷實戰)", "50 題 (高強度特訓)", "自訂題數"],
                    key="count_300_select"
                )
                if count_300_choice == "自訂題數":
                    take_count = st.number_input("請輸入抽取題數 (1~100 題)：", min_value=1, max_value=100, value=10, key="custom_300_count")
                else:
                    take_count = int(count_300_choice.split(" ")[0])

            if st.button("🚀 從全真題庫抽取試題開始測驗", type="primary", use_container_width=True):
                import random
                if not subject_pool:
                    st.error("目前該科目題庫為空或載入失敗。")
                else:
                    pool = list(subject_pool)

                    # 考點分類過濾
                    if not cat_300_choice.startswith("全部考點分類"):
                        cat_filtered = [q for q in pool if q.get("category", "").strip() == cat_300_choice]
                        if cat_filtered:
                            pool = cat_filtered

                    actual_take = min(take_count, len(pool))
                    selected_qs = random.sample(pool, actual_take)
                    reindexed_qs = []
                    new_answer_key = {}
                    for i, q in enumerate(selected_qs, 1):
                        q_copy = dict(q)
                        q_copy["original_no"] = q_copy.get("question_no", i)
                        q_copy["question_no"] = i
                        ans = q_copy.get("answer", "A")
                        new_answer_key[str(i)] = ans
                        reindexed_qs.append(q_copy)

                    st.session_state["stage1_exam_data"] = {
                        "subject": sel_domain_filter,
                        "topic": f"全真模擬抽考（{sel_domain_filter}・{len(reindexed_qs)}題）",
                        "total_count": len(reindexed_qs),
                        "questions": reindexed_qs,
                        "answer_key": new_answer_key
                    }
                    st.session_state.pop("stage1_graded", None)
                    st.session_state.pop("stage1_user_answers", None)
                    st.success(f"🎉 已成功自【{sel_domain_filter}】題庫中隨機抽取 {len(reindexed_qs)} 題（符合條件試題池共 {len(pool)} 題），請於下方開始作答！")

        # 若 session 中有一試試題，展示作答、速查表與詳解
        if "stage1_exam_data" in st.session_state:
            exam_data = st.session_state["stage1_exam_data"]
            questions = exam_data.get("questions", [])
            answer_key = exam_data.get("answer_key", {})

            # 統計本卷所有試題考點分類
            raw_cats = [q.get("category", "").strip() for q in questions if q.get("category")]
            clean_cats = sorted(list(set(raw_cats)))

            st.divider()
            col_sec_head, col_sec_cat = st.columns([2, 1])
            with col_sec_head:
                st.subheader(f"📝 【第一部分：全真試題區】（盲測情境實力）")
                st.caption("提示：題幹已全面隱匿法條條號與裁判字號，請直接依具體事實判斷最正確選項。")
            with col_sec_cat:
                if clean_cats:
                    view_cat_filter = st.selectbox(
                        "🏷️ 依試題考點分類過濾瀏覽：",
                        ["🌟 顯示全卷考點試題 (共 %d 題)" % len(questions)] + [f"{c} ({raw_cats.count(c)} 題)" for c in clean_cats],
                        key="stage1_exam_category_filter"
                    )
                else:
                    view_cat_filter = "🌟 顯示全卷考點試題"

            user_answers = {}
            for q in questions:
                q_no = q.get("question_no")
                cat = q.get("category", "")
                cat_display = f" `{cat}`" if cat else ""

                # 若有選定分類過濾，且不符合當前分類，則跳過顯示
                if view_cat_filter != "🌟 顯示全卷考點試題" and not view_cat_filter.startswith("🌟 顯示全卷"):
                    chosen_cat = view_cat_filter.split(" (")[0].strip()
                    if cat.strip() != chosen_cat:
                        continue

                st.markdown(f"#### 第 {q_no} 題{cat_display}")
                if q.get("case_facts"):
                    st.info(f"**【題組共通案件事實】**：\n\n{q.get('case_facts')}")

                st.write(q.get("question"))

                opts = q.get("options", {})
                choice_options = []
                for k in ["A", "B", "C", "D"]:
                    if k in opts:
                        choice_options.append(f"({k}) {opts[k]}")

                user_ans = st.radio(
                    f"請選擇第 {q_no} 題答案：",
                    choice_options,
                    index=None,
                    key=f"user_choice_{q_no}"
                )
                if user_ans:
                    user_answers[str(q_no)] = user_ans[1] # 提取 'A'

                st.write("")

            col_submit, col_export = st.columns([1, 1])
            with col_submit:
                if st.button("🏁 交卷立即線上批改評分", type="primary"):
                    st.session_state["stage1_graded"] = True
                    st.session_state["stage1_user_answers"] = user_answers
                    st.rerun()

            with col_export:
                md_content = LawExamGenerator.format_stage1_exam_markdown(exam_data)
                st.download_button(
                    label="💾 一鍵下載完整全真模擬試卷 (Markdown 檔)",
                    data=md_content,
                    file_name=f"司律一試_{exam_data.get('subject')}_{exam_data.get('topic')[:10]}_{len(questions)}題.md",
                    mime="text/markdown"
                )

            # 批改結果與考點分類實力診斷
            is_graded = st.session_state.get("stage1_graded", False)
            if is_graded:
                u_answers = st.session_state.get("stage1_user_answers", user_answers)
                score = 0
                for q_num_str, correct_ans in answer_key.items():
                    if u_answers.get(q_num_str) == correct_ans:
                        score += 1
                total_q = len(questions)
                pct = int(score / total_q * 100) if total_q > 0 else 0
                st.balloons()
                st.success(f"🎉 測驗批改完成！總成績：{score} / {total_q} 題（得分率：{pct}%）")

                # 考點分類實力診斷與弱點分析報告
                st.markdown("#### 🎯 考點分類實力診斷與弱點分析報告")
                cat_stats = {}
                for q in questions:
                    c = q.get("category", "綜合實務考點").strip()
                    if not c:
                        c = "綜合實務考點"
                    if c not in cat_stats:
                        cat_stats[c] = {"total": 0, "correct": 0, "missed": []}
                    cat_stats[c]["total"] += 1
                    q_no_str = str(q.get("question_no"))
                    if u_answers.get(q_no_str) == answer_key.get(q_no_str):
                        cat_stats[c]["correct"] += 1
                    else:
                        cat_stats[c]["missed"].append(q.get("question_no"))

                diag_cols = st.columns(min(len(cat_stats), 4) if cat_stats else 1)
                for idx_c, (c_name, stats) in enumerate(cat_stats.items()):
                    with diag_cols[idx_c % len(diag_cols)]:
                        c_rate = int(stats["correct"] / stats["total"] * 100) if stats["total"] > 0 else 0
                        if c_rate == 100:
                            badge = "🌟 精熟達標"
                        elif c_rate >= 60:
                            badge = "👍 掌握良好"
                        else:
                            badge = "⚠️ 建議複習加強"
                        st.metric(
                            label=f"{c_name[:14]}",
                            value=f"{stats['correct']}/{stats['total']} 題 ({c_rate}%)",
                            delta=badge
                        )
                        if stats["missed"]:
                            st.caption(f"錯題題號：第 {', '.join(map(str, stats['missed']))} 題")

            # 第二部分：標準答案速查表與詳細解析（交卷批改後解鎖，附提前展開核對選項）
            peek_solution = st.checkbox("👁️ 提早檢視答案速查表與詳細解析 (不鎖定)", value=False, key="cb_peek_stage1_solution")
            show_stage1_sol = is_graded or peek_solution

            if not show_stage1_sol:
                st.info("🔒 **答案速查表與逐題詳解已安全鎖定**：請於上方完成作答後點擊「🏁 交卷立即線上批改評分」自動解鎖，或勾選上方「提早檢視」選項。")
            else:
                st.divider()
                st.subheader(f"📋 【第二部分：標準答案速查表】(共 {len(questions)} 題)")

                u_answers_map = st.session_state.get("stage1_user_answers", user_answers) if is_graded else {}
                cols_per_row = 5
                for row_start in range(1, len(questions) + 1, cols_per_row):
                    key_cols = st.columns(cols_per_row)
                    for c_idx in range(cols_per_row):
                        q_num = row_start + c_idx
                        if q_num <= len(questions):
                            with key_cols[c_idx]:
                                c_ans = answer_key.get(str(q_num), "A")
                                if is_graded:
                                    u_ans = u_answers_map.get(str(q_num))
                                    if u_ans == c_ans:
                                        st.success(f"**第 {q_num} 題**：`({c_ans})` ✅ 正確")
                                    elif u_ans:
                                        st.error(f"**第 {q_num} 題**：`({c_ans})` ❌ (選 {u_ans})")
                                    else:
                                        st.warning(f"**第 {q_num} 題**：`({c_ans})` ⚪ 未作答")
                                else:
                                    st.info(f"**第 {q_num} 題**：`({c_ans})`")

                st.divider()
                st.subheader("💡 【第三部分：逐題詳細解析與實務裁判出處】")
                for q in questions:
                    q_no = q.get("question_no")
                    ans = q.get("answer")
                    with st.expander(f"查看第 {q_no} 題詳細解析 (正確答案：({ans}))"):
                        if q.get("core_issue"):
                            st.markdown(f"**【核心爭點】**：:blue[{q.get('core_issue')}]")
                        if q.get("legal_references"):
                            st.markdown(f"**【規範法條及實務裁判字號】**：:green[{q.get('legal_references')}]")
                        st.markdown("**【逐項解析與盲點辨析】**：")
                        st.write(q.get("explanation", ""))
    else:
        # 二試申論實例題
        if st.button("🎲 生成二試實例申論題", type="primary", use_container_width=True):
            target_topic = topic.strip() if topic.strip() else "年度重大爭議實例與實務大法庭爭點"
            with st.spinner("正在融合最新判例、大法庭與考生筆記，設計二試綜合案例事實..."):
                try:
                    gen = LawExamGenerator()
                    res = gen.generate_stage2_exam(
                        subject=subject,
                        topic=target_topic,
                        notes_content=final_notes if final_notes else None
                    )
                    st.session_state["stage2_exam_data"] = res
                    st.success("二試實例題設計完成！")
                except Exception as e:
                    st.error(f"出題失敗: {e}")

        if "stage2_exam_data" in st.session_state:
            res = st.session_state["stage2_exam_data"]
            st.divider()
            st.subheader(f"【{res.get('subject', subject)}】綜合實例申論題 (總分：{res.get('total_points', 100)} 分)")
            st.markdown("#### 📜 案例事實背景：")
            st.write(res.get("question_facts", ""))

            st.markdown("#### ❓ 請回答下列問題：")
            for sub in res.get("sub_questions", []):
                st.write(f"- **{sub}**")

            with st.expander("🔍 查看命題核心爭點與評分指標"):
                for cr in res.get("core_issues", []):
                    st.write(f"- {cr}")
                st.info(f"**命題要點與得分關鍵：**\n{res.get('scoring_criteria', '')}")

            full_q_text = f"【案例事實】：\n{res.get('question_facts', '')}\n\n【問題】：\n" + "\n".join(res.get("sub_questions", []))

            cq_col1, cq_col2 = st.columns(2)
            with cq_col1:
                if st.button("🏆 生成榜首級示範擬答 (IRAC 三段論法)", type="primary"):
                    with st.spinner("榜首法學講座名師正在撰寫嚴謹三段論法擬答..."):
                        gen = LawExamGenerator()
                        ans = gen.generate_model_answer(question=full_q_text, subject=subject)
                        st.markdown("### 🏆 閱卷高分示範擬答：")
                        st.markdown(ans)
            with cq_col2:
                if st.button("📝 一鍵將此題直接帶入【試卷評分】批改"):
                    st.session_state["question_text_content"] = full_q_text
                    st.session_state["imported_from_bank_label"] = f"【AI 客製模擬考題 - {subject}】"
                    st.session_state["app_mode"] = "📝 試卷評分與手寫辨識 (手寫/PDF/Word)"
                    st.rerun()

    # ----------------- 模式 3: 歷年真題庫檢索 -----------------

