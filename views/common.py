"""
共用快取資料載入函式與評分/題庫狀態輔助工具
"""
import streamlit as st

def reset_stage1_exam_state():
    """徹底重設一試選擇題之作答紀錄、批改報告狀態與所有 Radio 按鍵暫存，避免上次答案污染新題目"""
    st.session_state["stage1_graded"] = False
    st.session_state.pop("stage1_user_answers", None)
    st.session_state.pop("cb_peek_stage1_solution", None)
    for k in list(st.session_state.keys()):
        if k.startswith("user_choice_"):
            st.session_state.pop(k, None)

@st.cache_data(ttl=300)
def load_all_drive_notes():
    """載入 Google Drive / 本機歸檔個人筆記清單"""
    try:
        from ingest_user_notes_to_sft import get_google_drive_notes_list
        return get_google_drive_notes_list()
    except Exception:
        return []

@st.cache_data(ttl=3600)
def load_all_existing_stage1_mcqs() -> list:
    """全量載入既有一試全真題庫（委由 exam_generator 模組執行，並於前端保留 1 小時快取）"""
    try:
        from exam_generator import load_all_existing_stage1_mcqs as _load_mcqs
        return _load_mcqs()
    except Exception:
        return []
