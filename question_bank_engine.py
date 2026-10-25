# -*- coding: utf-8 -*-
"""
question_bank_engine.py - 模擬命題共享題庫資料持久化與隨選刷題引擎

功能特點：
1. 共享題庫持久化（generated_questions 表）：自動將 AI 模擬命題（第一試選擇、第二試實例）入庫。
2. 零 Token 隨選刷題：支援第一試隨機/分類刷題與即時作答反饋、第二試 IRAC 擬答展開。
3. 多維度檢索：支援依學門科目、考試階段、難度、法條/爭點關鍵字進行快速檢索。
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from config import get_db_path, PROJECT_ROOT
except ImportError:
    try:
        from code.config import get_db_path, PROJECT_ROOT
    except ImportError:
        PROJECT_ROOT = Path(__file__).resolve().parent.parent
        def get_db_path():
            return PROJECT_ROOT / "data" / "judicial_authority.db"


def _get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    if db_path is None:
        target = get_db_path()
    else:
        target = Path(db_path)
    
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
    except Exception:
        pass
    return conn


def init_question_bank_table(db_path: Optional[str] = None) -> None:
    """初始化共享題庫資料表與索引"""
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS generated_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id TEXT UNIQUE NOT NULL,
                    exam_stage TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    chapter_topic TEXT,
                    core_concepts TEXT,
                    difficulty TEXT,
                    stem TEXT NOT NULL,
                    options_json TEXT,
                    correct_answer TEXT,
                    explanation TEXT,
                    laws_cited TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_qbank_stage ON generated_questions(exam_stage);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_qbank_subject ON generated_questions(subject);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_qbank_diff ON generated_questions(difficulty);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_qbank_created ON generated_questions(created_at DESC);")
    finally:
        conn.close()


def save_questions_to_pool(questions: List[Dict[str, Any]], db_path: Optional[str] = None) -> int:
    """
    將產生的題目清單儲存至共享題庫。
    questions: 每題應包含 exam_stage, subject, stem, options, correct_answer, explanation, etc.
    """
    if not questions:
        return 0

    init_question_bank_table(db_path)
    conn = _get_connection(db_path)
    inserted = 0

    try:
        with conn:
            for q in questions:
                qid = str(q.get("question_id") or f"q_{uuid.uuid4().hex[:12]}")
                exam_stage = str(q.get("exam_stage") or "第一試 (選擇題)")
                subject = str(q.get("subject") or "民事實體法")
                chapter_topic = str(q.get("chapter_topic") or "")
                
                # core_concepts 處理
                cc = q.get("core_concepts", "")
                if isinstance(cc, list):
                    cc = "、".join(str(x) for x in cc)
                else:
                    cc = str(cc)

                difficulty = str(q.get("difficulty") or "司律二試")
                stem = str(q.get("stem") or q.get("question") or "")
                if not stem.strip():
                    continue

                # options 處理
                opts = q.get("options", [])
                if isinstance(opts, (list, dict)):
                    options_json = json.dumps(opts, ensure_ascii=False)
                elif isinstance(opts, str):
                    options_json = opts
                else:
                    options_json = "[]"

                correct_answer = str(q.get("correct_answer") or q.get("answer") or "")
                explanation = str(q.get("explanation") or q.get("model_answer") or "")
                
                laws = q.get("laws_cited", "")
                if isinstance(laws, list):
                    laws_cited = "、".join(str(x) for x in laws)
                else:
                    laws_cited = str(laws)

                conn.execute("""
                    INSERT OR REPLACE INTO generated_questions (
                        question_id, exam_stage, subject, chapter_topic,
                        core_concepts, difficulty, stem, options_json,
                        correct_answer, explanation, laws_cited, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    qid, exam_stage, subject, chapter_topic,
                    cc, difficulty, stem, options_json,
                    correct_answer, explanation, laws_cited
                ))
                inserted += 1
    except Exception as e:
        print(f"[!] 寫入共享題庫失敗: {e}")
    finally:
        conn.close()

    return inserted


def get_questions_from_pool(
    exam_stage: Optional[str] = None,
    subject: Optional[str] = None,
    difficulty: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    從共享題庫檢索題目。
    """
    init_question_bank_table(db_path)
    conn = _get_connection(db_path)
    
    query = "SELECT * FROM generated_questions WHERE 1=1"
    params = []

    if exam_stage and exam_stage != "全部階段":
        query += " AND exam_stage LIKE ?"
        params.append(f"%{exam_stage}%")

    if subject and subject != "全部科目":
        query += " AND subject LIKE ?"
        params.append(f"%{subject}%")

    if difficulty and difficulty != "全部難度":
        query += " AND difficulty LIKE ?"
        params.append(f"%{difficulty}%")

    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        query += " AND (stem LIKE ? OR core_concepts LIKE ? OR chapter_topic LIKE ? OR laws_cited LIKE ?)"
        params.extend([kw, kw, kw, kw])

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    results = []
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        for r in rows:
            item = dict(r)
            # 解析 options_json
            try:
                item["options"] = json.loads(item.get("options_json") or "[]")
            except Exception:
                item["options"] = []
            results.append(item)
    except Exception as e:
        print(f"[!] 檢索共享題庫失敗: {e}")
    finally:
        conn.close()

    return results


def get_question_pool_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """取得題庫統計資訊（各階段、各科目筆數）"""
    init_question_bank_table(db_path)
    conn = _get_connection(db_path)
    stats = {
        "total": 0,
        "stages": {},
        "subjects": {}
    }

    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM generated_questions;")
        stats["total"] = cur.fetchone()[0]

        cur.execute("SELECT exam_stage, COUNT(*) FROM generated_questions GROUP BY exam_stage;")
        for row in cur.fetchall():
            stats["stages"][row[0]] = row[1]

        cur.execute("SELECT subject, COUNT(*) FROM generated_questions GROUP BY subject;")
        for row in cur.fetchall():
            stats["subjects"][row[0]] = row[1]

    except Exception as e:
        print(f"[!] 統計共享題庫失敗: {e}")
    finally:
        conn.close()

    return stats


def delete_question_from_pool(question_id: str, db_path: Optional[str] = None) -> bool:
    """刪除指定題號之題目"""
    conn = _get_connection(db_path)
    deleted = False
    try:
        with conn:
            cur = conn.execute("DELETE FROM generated_questions WHERE question_id = ?;", (question_id,))
            deleted = (cur.rowcount > 0)
    except Exception as e:
        print(f"[!] 刪除題目失敗: {e}")
    finally:
        conn.close()
    return deleted


def render_shared_question_pool_ui() -> None:
    """
    Streamlit 共享題庫隨選刷題介面（0 Token 秒讀）
    """
    import streamlit as st

    st.markdown("### 📚 共享題庫隨選刷題中心（⚡ 0 Token 秒級載入）")
    st.caption("所有考生透過 AI 命題系統生成的精質試卷均自動去重典藏於此。支援一試選擇即時盲測、二試實例 IRAC 擬答研讀，全流程免重複消耗 API 配額！")

    # 1. 統計指標卡片
    stats = get_question_pool_stats()
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    m_col1.metric("題庫總題目數", f"{stats['total']} 題")
    
    stage1_cnt = sum(v for k, v in stats["stages"].items() if "第一試" in k or "選擇" in k)
    stage2_cnt = sum(v for k, v in stats["stages"].items() if "第二試" in k or "申論" in k)
    
    m_col2.metric("一試選擇試題", f"{stage1_cnt} 題")
    m_col3.metric("二試實例申論", f"{stage2_cnt} 題")
    m_col4.metric("已收納考科", f"{len(stats['subjects'])} 個科目")

    st.divider()

    # 2. 檢索與篩選列
    f_col1, f_col2, f_col3, f_col4 = st.columns([1.2, 1.5, 1.2, 2.1])
    
    with f_col1:
        sel_stage = st.selectbox(
            "考試階段：",
            ["全部階段", "第一試 (選擇題)", "第二試 (申論實例題)"],
            key="qp_filter_stage"
        )
    
    with f_col2:
        subject_options = ["全部科目"] + sorted(list(stats["subjects"].keys()))
        if "全部科目" not in subject_options:
            subject_options.insert(0, "全部科目")
        sel_sub = st.selectbox(
            "考科分類：",
            subject_options,
            key="qp_filter_subject"
        )
        
    with f_col3:
        sel_diff = st.selectbox(
            "試題難度：",
            ["全部難度", "司律一試", "司律二試", "難度 10/10", "高難度"],
            key="qp_filter_diff"
        )

    with f_col4:
        kw = st.text_input(
            "🔍 爭點/法條/事實關鍵字檢索：",
            placeholder="例如：善意受讓、不當得利、正當防衛、第179條...",
            key="qp_filter_kw"
        )

    # 3. 執行檢索
    questions = get_questions_from_pool(
        exam_stage=sel_stage,
        subject=sel_sub,
        difficulty=sel_diff,
        keyword=kw,
        limit=50
    )

    if not questions:
        st.info("💡 目前共享題庫中尚無符合此條件的試題。您可以切換至【🎲 AI 即時客製命題】產出新試題，系統將自動秒級入庫！")
        return

    st.markdown(f"##### 🎯 篩選出 **{len(questions)}** 道高質量共享試題：")

    # 4. 逐題渲染
    for idx, q in enumerate(questions, 1):
        is_mcq = "一試" in q.get("exam_stage", "") or "選擇" in q.get("exam_stage", "")
        stage_badge = "🔵【第一試 選擇題】" if is_mcq else "🟣【第二試 申論實例題】"
        sub_name = q.get("subject", "法學綜合")
        created_dt = str(q.get("created_at", ""))[:10]
        qid = q.get("question_id", str(idx))
        
        with st.container(border=True):
            col_h1, col_h2 = st.columns([3, 1])
            with col_h1:
                st.markdown(f"#### 第 {idx} 題 {stage_badge} `{sub_name}`")
                if q.get("chapter_topic"):
                    st.caption(f"專題/篇章：{q['chapter_topic']} ｜ 難度：{q.get('difficulty', '標準')}")
            with col_h2:
                st.caption(f"入庫日期：{created_dt}")

            if q.get("core_concepts"):
                st.info(f"🎯 **【命題核心爭點】**：{q['core_concepts']}")

            # 題幹內文
            st.markdown(f"**【試題內容】**：\n\n{q.get('stem', '')}")

            # 針對選擇題渲染作答單選介面
            if is_mcq:
                options = q.get("options", {})
                choice_list = []
                correct_letter = q.get("correct_answer", "").strip().upper()
                
                # 容錯字典或清單格式
                if isinstance(options, dict):
                    for k in ["A", "B", "C", "D"]:
                        if k in options:
                            choice_list.append(f"({k}) {options[k]}")
                elif isinstance(options, list):
                    for opt_idx, opt_val in enumerate(options):
                        letter = chr(ord('A') + opt_idx)
                        choice_list.append(f"({letter}) {opt_val}")

                if choice_list:
                    u_choice = st.radio(
                        f"作答選擇（點選即時核對）：",
                        choice_list,
                        index=None,
                        key=f"mcq_radio_{qid}"
                    )
                    
                    if u_choice:
                        user_letter = u_choice.split(")")[0].replace("(", "").strip().upper()
                        if user_letter == correct_letter:
                            st.success(f"🎉 **回答正確！** 標準解答為 ({correct_letter})")
                        else:
                            st.error(f"❌ **答錯了！** 您的選擇為 ({user_letter}) ｜ 正確答案應為 **({correct_letter})**")

                with st.expander(f"💡 查看本題詳解與法規出處 (標準解答: {correct_letter})"):
                    st.markdown("**【詳細法理解析】**：")
                    st.write(q.get("explanation", "無解析內容"))
                    if q.get("laws_cited"):
                        st.markdown(f"**【規範依據與實務裁判】**：:blue[{q['laws_cited']}]")

            else:
                # 第二試申論實例題
                with st.expander("🏆 查看榜首級示範擬答與 IRAC 三段論解析（0 Token 秒讀）", expanded=False):
                    st.markdown("### 🏆 評分指標與示範擬答：")
                    st.markdown(q.get("explanation", "尚未產生擬答內容"))
                    if q.get("laws_cited"):
                        st.caption(f"引用裁判與法條：{q['laws_cited']}")

                col_btn_eval, _ = st.columns([1.5, 2.5])
                with col_btn_eval:
                    if st.button("📝 帶入此題至【試卷評分】進行作答批改", key=f"btn_take_to_eval_{qid}"):
                        st.session_state["question_text_content"] = q.get("stem", "")
                        st.session_state["imported_from_bank_label"] = f"【共享題庫實例題 - {sub_name}】"
                        try:
                            from config import MODE_EVAL
                        except ImportError:
                            MODE_EVAL = "試卷評分"
                        st.session_state["app_mode"] = MODE_EVAL
                        st.session_state["nav_sidebar_radio_mode"] = MODE_EVAL
                        st.rerun()
