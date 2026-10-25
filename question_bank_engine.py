# -*- coding: utf-8 -*-
"""
question_bank_engine.py - 模擬命題共享題庫、社群題目共享、考生作答隔離與法務回報引擎

功能特點：
1. 共享題庫持久化（generated_questions 表）：自動將 AI 模擬命題（第一試選擇、第二試實例）入庫。
2. 社群題目共享分流（community_shared_questions 表）：題目公開共享，自動考科分類，全員可隨選練習。
3. 考生作答隔離典藏（user_exam_submissions 表）：🔒 嚴格限開發者調閱，絕不公開他人作答。
4. 法務疑慮與移除回報（author_feedback_reports 表）：即時記錄使用者疑慮反饋供開發者審查。
5. 零 Token 隨選刷題與開發者專屬調閱室。
"""

import hashlib
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
    if db_path is not None:
        target = Path(db_path)
    else:
        target = None
        try:
            p = get_db_path()
            if p.exists() and p.stat().st_size > 0:
                target = p
        except Exception:
            pass

        if target is None:
            cands = [
                Path("G:/我的雲端硬碟/LawExamData/data/judicial_authority.db"),
                PROJECT_ROOT / "data" / "judicial_authority.db",
                Path(__file__).resolve().parent.parent / "data" / "judicial_authority.db",
                Path("data/judicial_authority.db")
            ]
            for c in cands:
                if c.exists() and c.stat().st_size > 0:
                    target = c
                    break
            if target is None:
                target = get_db_path()
    
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
    """初始化所有題庫、社群共享、考生作答與法務反饋資料表與索引"""
    conn = _get_connection(db_path)
    try:
        with conn:
            # 1. AI 模擬命題庫
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

            # 2. 社群考生共享題庫（全員公開）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS community_shared_questions (
                    q_id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    exam_stage TEXT NOT NULL DEFAULT '第二試 (申論實例題)',
                    stem_text TEXT NOT NULL,
                    raw_file_path TEXT DEFAULT '',
                    reference_answer TEXT DEFAULT '',
                    source_module TEXT DEFAULT '試卷批改',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_csq_subj ON community_shared_questions(subject);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_csq_stage ON community_shared_questions(exam_stage);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_csq_created ON community_shared_questions(created_at DESC);")

            # 3. 考生作答與批改紀錄表（🔒 嚴格限開發者觀看）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_exam_submissions (
                    sub_id TEXT PRIMARY KEY,
                    q_id TEXT,
                    subject TEXT NOT NULL,
                    answer_text TEXT NOT NULL,
                    answer_files_json TEXT DEFAULT '[]',
                    ai_evaluation_md TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_subm_qid ON user_exam_submissions(q_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_subm_subj ON user_exam_submissions(subject);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_subm_created ON user_exam_submissions(created_at DESC);")

            # 4. 法務疑慮與移除回報表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS author_feedback_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    contact TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
    finally:
        conn.close()


# =========================================================================
# 一、AI 模擬命題操作函式
# =========================================================================
def save_questions_to_pool(questions: List[Dict[str, Any]], db_path: Optional[str] = None) -> int:
    """將產生的模擬試題儲存至題庫"""
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
                
                cc = q.get("core_concepts", "")
                if isinstance(cc, list):
                    cc = "、".join(str(x) for x in cc)
                else:
                    cc = str(cc)

                difficulty = str(q.get("difficulty") or "司律二試")
                stem = str(q.get("stem") or q.get("question") or "")
                if not stem.strip():
                    continue

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
    """檢索模擬命題庫"""
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
    """取得題庫統計資訊"""
    init_question_bank_table(db_path)
    conn = _get_connection(db_path)
    stats = {"total": 0, "stages": {}, "subjects": {}, "community_total": 0}

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

        try:
            cur.execute("SELECT COUNT(*) FROM community_shared_questions;")
            stats["community_total"] = cur.fetchone()[0]
        except Exception:
            pass

    except Exception as e:
        print(f"[!] 統計共享題庫失敗: {e}")
    finally:
        conn.close()

    return stats


# =========================================================================
# 二、社群考生共享題庫（community_shared_questions - 全員公開）
# =========================================================================
def compute_question_hash(stem_text: str) -> str:
    """針對題目文字計算標準化 MD5 hash 進行精準去重"""
    norm = "".join(stem_text.split()).strip()
    return hashlib.md5(norm.encode("utf-8")).hexdigest()[:16]


def infer_subject_from_text(text: str, default: str = "法學綜合") -> str:
    """自動從題目文字推論法學考科領域"""
    t = text or ""
    if any(k in t for k in ["民法", "買賣", "租賃", "承攬", "抵押權", "所有權", "消滅時效", "侵權行為", "不當得利", "物權", "親屬", "繼承"]):
        return "民事財產與身分法"
    if any(k in t for k in ["刑法", "著手", "未遂", "正當防衛", "緊急避難", "殺人", "竊盜", "詐欺", "共犯", "過失", "背信"]):
        return "刑事實體法"
    if any(k in t for k in ["憲法", "行政程序", "行政處分", "訴願", "行政訴訟", "國家賠償", "比例原則", "法律保留"]):
        return "公法專題"
    if any(k in t for k in ["民事訴訟", "管轄", "訴訟標的", "既判力", "當事人適格", "言詞辯論"]):
        return "民事程序法"
    if any(k in t for k in ["刑事訴訟", "羈押", "搜索", "扣押", "傳聞法則", "證據能力", "起訴"]):
        return "刑事程序法"
    if any(k in t for k in ["公司法", "證券交易", "保險法", "票據", "股東會", "董事會", "內線交易"]):
        return "商事法專題"
    if any(k in t for k in ["專利", "商標", "著作權", "營業秘密", "進步性", "混淆誤認"]):
        return "智慧財產權法專題"
    return default


def save_community_question(
    stem_text: str,
    subject: Optional[str] = None,
    exam_stage: str = "第二試 (申論實例題)",
    raw_file_path: str = "",
    reference_answer: str = "",
    source_module: str = "試卷批改",
    db_path: Optional[str] = None
) -> str:
    """儲存題目至社群公開題庫（自動去重，並保存原始檔案與擬答）"""
    if not stem_text or not stem_text.strip():
        return ""

    init_question_bank_table(db_path)
    q_id = f"cq_{compute_question_hash(stem_text)}"
    
    if not subject or subject == "法學綜合":
        subject = infer_subject_from_text(stem_text, "民事財產與身分法")

    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                INSERT INTO community_shared_questions (
                    q_id, subject, exam_stage, stem_text, raw_file_path,
                    reference_answer, source_module, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(q_id) DO UPDATE SET
                    reference_answer = CASE WHEN excluded.reference_answer != '' THEN excluded.reference_answer ELSE reference_answer END,
                    raw_file_path = CASE WHEN excluded.raw_file_path != '' THEN excluded.raw_file_path ELSE raw_file_path END,
                    subject = CASE WHEN subject = '法學綜合' THEN excluded.subject ELSE subject END;
            """, (q_id, subject, exam_stage, stem_text.strip(), raw_file_path, reference_answer.strip(), source_module))
    except Exception as e:
        print(f"[!] 儲存社群公開題目失敗: {e}")
    finally:
        conn.close()

    return q_id


def save_community_questions_batch(
    questions: List[Dict[str, Any]],
    db_path: Optional[str] = None
) -> int:
    """批次高速儲存題目至社群公開題庫（單一事務，零鎖死）"""
    if not questions:
        return 0
    init_question_bank_table(db_path)
    records = []
    for q in questions:
        stem = str(q.get("stem_text") or "").strip()
        if not stem or len(stem) < 20:
            continue
        qid = f"cq_{compute_question_hash(stem)}"
        subj = str(q.get("subject") or "").strip()
        if not subj or subj == "法學綜合":
            subj = infer_subject_from_text(stem, "民事財產與身分法")
        stage = str(q.get("exam_stage") or "第二試 (申論實例題)")
        rfp = str(q.get("raw_file_path") or "")
        ra = str(q.get("reference_answer") or "").strip()
        mod = str(q.get("source_module") or "試卷批改")
        records.append((qid, subj, stage, stem, rfp, ra, mod))

    if not records:
        return 0

    inserted = 0
    conn = _get_connection(db_path)
    try:
        with conn:
            conn.executemany("""
                INSERT INTO community_shared_questions (
                    q_id, subject, exam_stage, stem_text, raw_file_path,
                    reference_answer, source_module, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(q_id) DO UPDATE SET
                    reference_answer = CASE WHEN excluded.reference_answer != '' THEN excluded.reference_answer ELSE reference_answer END,
                    raw_file_path = CASE WHEN excluded.raw_file_path != '' THEN excluded.raw_file_path ELSE raw_file_path END,
                    subject = CASE WHEN subject = '法學綜合' THEN excluded.subject ELSE subject END;
            """, records)
            inserted = len(records)
    except Exception as e:
        print(f"[!] 批次儲存社群題庫失敗: {e}")
    finally:
        conn.close()

    return inserted


def get_community_questions(
    subject: Optional[str] = None,
    exam_stage: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """檢索社群公開題庫"""
    init_question_bank_table(db_path)
    conn = _get_connection(db_path)
    
    query = "SELECT * FROM community_shared_questions WHERE 1=1"
    params = []

    if subject and subject != "全部科目":
        query += " AND subject LIKE ?"
        params.append(f"%{subject}%")

    if exam_stage and exam_stage != "全部階段":
        query += " AND exam_stage LIKE ?"
        params.append(f"%{exam_stage}%")

    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        query += " AND (stem_text LIKE ? OR reference_answer LIKE ?)"
        params.extend([kw, kw])

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    results = []
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        for r in cur.fetchall():
            results.append(dict(r))
    except Exception as e:
        print(f"[!] 檢索社群題庫失敗: {e}")
    finally:
        conn.close()

    return results


def get_community_question_subjects(db_path: Optional[str] = None) -> List[str]:
    """取得社群題庫中現存之所有考科分類"""
    init_question_bank_table(db_path)
    conn = _get_connection(db_path)
    subjects = []
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT subject FROM community_shared_questions WHERE subject != '' ORDER BY subject;")
        subjects = [r[0] for r in cur.fetchall()]
    except Exception:
        pass
    finally:
        conn.close()
    return subjects


# =========================================================================
# 三、考生作答與批改紀錄（user_exam_submissions - 🔒 嚴格限開發者）
# =========================================================================
def save_user_exam_submission(
    q_id: str,
    subject: str,
    answer_text: str,
    answer_files: Optional[List[str]] = None,
    ai_evaluation_md: str = "",
    db_path: Optional[str] = None
) -> str:
    """儲存考生作答原檔與 AI 批改報告（僅供開發者調閱，絕不對外公開）"""
    init_question_bank_table(db_path)
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    files_json = json.dumps(answer_files or [], ensure_ascii=False)

    conn = _get_connection(db_path)
    try:
        with conn:
            conn.execute("""
                INSERT INTO user_exam_submissions (
                    sub_id, q_id, subject, answer_text,
                    answer_files_json, ai_evaluation_md, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);
            """, (sub_id, q_id, subject, answer_text, files_json, ai_evaluation_md))
    except Exception as e:
        print(f"[!] 儲存考生作答失敗: {e}")
    finally:
        conn.close()

    return sub_id


def get_user_exam_submissions(
    subject: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """調閱考生作答紀錄（🔒 開發者專屬函式）"""
    init_question_bank_table(db_path)
    conn = _get_connection(db_path)
    
    query = """
        SELECT s.*, q.stem_text as question_stem, q.reference_answer as question_ref_ans
        FROM user_exam_submissions s
        LEFT JOIN community_shared_questions q ON s.q_id = q.q_id
        WHERE 1=1
    """
    params = []

    if subject and subject != "全部科目":
        query += " AND s.subject LIKE ?"
        params.append(f"%{subject}%")

    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        query += " AND (s.answer_text LIKE ? OR s.ai_evaluation_md LIKE ? OR q.stem_text LIKE ?)"
        params.extend([kw, kw, kw])

    query += " ORDER BY s.created_at DESC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    results = []
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        for r in cur.fetchall():
            item = dict(r)
            try:
                item["answer_files"] = json.loads(item.get("answer_files_json") or "[]")
            except Exception:
                item["answer_files"] = []
            results.append(item)
    except Exception as e:
        print(f"[!] 調閱考生作答紀錄失敗: {e}")
    finally:
        conn.close()

    return results


# =========================================================================
# 四、法務聲明與疑慮回報（author_feedback_reports）
# =========================================================================
def save_author_feedback(
    category: str,
    description: str,
    contact: str = "",
    db_path: Optional[str] = None
) -> int:
    """儲存使用者疑慮與問題回報紀錄"""
    init_question_bank_table(db_path)
    conn = _get_connection(db_path)
    new_id = 0
    try:
        with conn:
            cur = conn.execute("""
                INSERT INTO author_feedback_reports (category, description, contact, created_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP);
            """, (category, description, contact))
            new_id = cur.lastrowid
    except Exception as e:
        print(f"[!] 儲存使用者反饋失敗: {e}")
    finally:
        conn.close()
    return new_id


def get_author_feedbacks(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """取得法務反饋清單（開發者專用）"""
    init_question_bank_table(db_path)
    conn = _get_connection(db_path)
    results = []
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM author_feedback_reports ORDER BY created_at DESC LIMIT ?;", (limit,))
        results = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[!] 讀取法務反饋失敗: {e}")
    finally:
        conn.close()
    return results


# =========================================================================
# 五、Streamlit 前端介面渲染函式
# =========================================================================
def render_shared_question_pool_ui() -> None:
    """Streamlit 共享題庫隨選刷題介面（0 Token 秒讀）"""
    import streamlit as st

    st.markdown("### 📚 共享題庫隨選刷題中心（⚡ 0 Token 秒級載入）")
    st.caption("所有考生透過 AI 命題系統生成的精質試卷均自動去重典藏於此。支援一試選擇即時盲測、二試實例 IRAC 擬答研讀，全流程免重複消耗 API 配額！")

    stats = get_question_pool_stats()
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    m_col1.metric("題庫總題目數", f"{stats['total']} 題")
    
    stage1_cnt = sum(v for k, v in stats["stages"].items() if "第一試" in k or "選擇" in k)
    stage2_cnt = sum(v for k, v in stats["stages"].items() if "第二試" in k or "申論" in k)
    
    m_col2.metric("一試選擇試題", f"{stage1_cnt} 題")
    m_col3.metric("二試實例申論", f"{stage2_cnt} 題")
    m_col4.metric("社群共享題目", f"{stats.get('community_total', 0)} 題")

    st.divider()

    f_col1, f_col2, f_col3, f_col4 = st.columns([1.2, 1.5, 1.2, 2.1])
    with f_col1:
        sel_stage = st.selectbox("考試階段：", ["全部階段", "第一試 (選擇題)", "第二試 (申論實例題)"], key="qp_filter_stage")
    with f_col2:
        subject_options = ["全部科目"] + sorted(list(stats["subjects"].keys()))
        if "全部科目" not in subject_options:
            subject_options.insert(0, "全部科目")
        sel_sub = st.selectbox("考科分類：", subject_options, key="qp_filter_subject")
    with f_col3:
        sel_diff = st.selectbox("試題難度：", ["全部難度", "司律一試", "司律二試", "難度 10/10", "高難度"], key="qp_filter_diff")
    with f_col4:
        kw = st.text_input("🔍 爭點/法條/事實關鍵字檢索：", placeholder="例如：善意受讓、不當得利、正當防衛、第179條...", key="qp_filter_kw")

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

            st.markdown(f"**【試題內容】**：\n\n{q.get('stem', '')}")

            if is_mcq:
                options = q.get("options", {})
                choice_list = []
                correct_letter = q.get("correct_answer", "").strip().upper()
                
                if isinstance(options, dict):
                    for k in ["A", "B", "C", "D"]:
                        if k in options:
                            choice_list.append(f"({k}) {options[k]}")
                elif isinstance(options, list):
                    for opt_idx, opt_val in enumerate(options):
                        letter = chr(ord('A') + opt_idx)
                        choice_list.append(f"({letter}) {opt_val}")

                if choice_list:
                    u_choice = st.radio(f"作答選擇（點選即時核對）：", choice_list, index=None, key=f"mcq_radio_{qid}")
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


def render_developer_submission_viewer_ui() -> None:
    """🔒 開發者專屬：歷次考生上傳作答與批改調閱室"""
    import streamlit as st

    st.markdown("### 🔒 開發者專屬：歷次考生上傳作答與批改調閱室")
    st.caption("依據平台隱私權保護規範，考生上傳之手寫卷與個人作答受嚴格權限隔離，僅供系統管理員/開發者進行系統維護與作答模型調優。")

    sub_tab1, sub_tab2 = st.tabs(["📝 歷次考生作答調閱", "📩 使用者法務疑慮與移除申請"])

    with sub_tab1:
        fcol1, fcol2 = st.columns([1.5, 2.5])
        with fcol1:
            all_subs = ["全部科目", "民事財產與身分法", "刑事實體法", "公法專題", "民事程序法", "刑事程序法", "商事法專題", "智慧財產權法專題"]
            sel_s = st.selectbox("依考科過濾作答紀錄：", all_subs, key="dev_subm_filter_subj")
        with fcol2:
            kw = st.text_input("🔍 搜尋作答文字或題目關鍵字：", key="dev_subm_filter_kw")

        submissions = get_user_exam_submissions(subject=sel_s, keyword=kw, limit=50)

        if not submissions:
            st.info("目前尚無符合條件的考生上傳作答紀錄。")
        else:
            st.markdown(f"共調閱出 **{len(submissions)}** 筆考生作答與批改紀錄：")
            for idx, subm in enumerate(submissions, 1):
                sub_id = subm.get("sub_id", str(idx))
                created_at = str(subm.get("created_at", ""))[:19]
                subj = subm.get("subject", "未分類")
                
                with st.expander(f"【{idx}】考科：{subj} ｜ 提交時間：{created_at} ｜ 序號：{sub_id}"):
                    # 1. 題目
                    st.markdown("#### 📜 對應考試題目：")
                    st.write(subm.get("question_stem") or "（純作答批改，無關聯題目紀錄）")

                    # 2. 考生作答
                    st.markdown("#### ✍️ 考生作答文字 (OCR 辨識結果)：")
                    st.text_area("考生完整作答：", value=subm.get("answer_text", ""), height=150, key=f"ans_view_{sub_id}", disabled=True)

                    # 3. 考生原始作答檔案清單
                    files = subm.get("answer_files", [])
                    if files:
                        st.markdown(f"**📎 考生上傳之原始附件檔案（共 {len(files)} 個）：**")
                        for f_path in files:
                            p = Path(f_path)
                            st.caption(f"• 檔案路徑：`{p.name}` ({f_path})")
                            if p.exists() and p.is_file():
                                try:
                                    with open(p, "rb") as fp:
                                        f_bytes = fp.read()
                                    st.download_button(
                                        f"📥 下載作答附件：{p.name}",
                                        data=f_bytes,
                                        file_name=p.name,
                                        key=f"dl_subm_file_{sub_id}_{p.name}"
                                    )
                                except Exception:
                                    pass

                    # 4. AI 批改報告
                    st.markdown("#### 📊 AI 四維度批改與診斷報告：")
                    eval_md = subm.get("ai_evaluation_md", "")
                    if eval_md:
                        st.markdown(eval_md)
                        st.download_button(
                            "📥 下載此份 AI 批改報告 (.md)",
                            data=eval_md,
                            file_name=f"批改報告_{subj}_{sub_id}.md",
                            mime="text/markdown",
                            key=f"dl_eval_report_{sub_id}"
                        )
                    else:
                        st.info("尚無批改報告")

    with sub_tab2:
        st.markdown("#### 📩 使用者疑慮停用、個資移除與問題回報清單")
        reports = get_author_feedbacks(limit=50)
        if not reports:
            st.info("目前尚無使用者疑慮或移除申請回報。")
        else:
            for rep in reports:
                with st.container(border=True):
                    r_col1, r_col2 = st.columns([3, 1])
                    with r_col1:
                        st.markdown(f"**類別：`{rep.get('category')}`**")
                        st.caption(f"聯絡方式：{rep.get('contact') or '未留'} ｜ 提出時間：{rep.get('created_at')}")
                    with r_col2:
                        st.badge(rep.get("status", "pending"))
                    st.write(f"**詳細描述**：\n{rep.get('description')}")
