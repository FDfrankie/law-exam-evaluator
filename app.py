import os
import streamlit as st
from pathlib import Path

from config import (
    ROOT_DIR, CORE_DIR, get_gemini_api_key, DEFAULT_GEMINI_MODEL,
    MODE_HOME, MODE_EVAL, MODE_GEN, MODE_BANK, MODE_ANS,
    MODE_SEARCH, MODE_QA, MODE_SUMMARIZER, MODE_SIX_CODES, MODE_SFT
)
from ui.styles import inject_custom_css
from ui.components import render_system_status_badge
from ui.views import (
    workspace_grading,
    workspace_testing,
    workspace_research,
    workspace_sixcodes,
    workspace_qa_sft
)

# 1. 頁面全域設定
st.set_page_config(
    page_title="司律法學 AI 評分與研習旗艦系統",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. 全域主題樣式注入 (深邃藏青藍與思源宋體排版)
inject_custom_css()

# 3. 五大核心工作區常數定義
WORKSPACES = [
    "📝 試卷批改與擬答",
    "🎯 模擬命題與盲測",
    "⚖️ 裁判檢索與精鍊",
    "📖 智慧六法全書",
    "💬 法學諮詢與筆記庫"
]

# 跨模組連動與舊版模式相容路由表
LEGACY_ROUTE_MAP = {
    MODE_EVAL: (0, 0), MODE_BANK: (0, 1), MODE_ANS: (0, 2),
    MODE_GEN: (1, 0),
    MODE_SEARCH: (2, 0), MODE_SUMMARIZER: (2, 1),
    MODE_SIX_CODES: (3, 0),
    MODE_QA: (4, 0), MODE_SFT: (4, 1), MODE_HOME: (4, 2),
    "MODE_EVAL": (0, 0), "MODE_BANK": (0, 1), "MODE_ANS": (0, 2),
    "MODE_GEN": (1, 0),
    "MODE_SEARCH": (2, 0), "MODE_SUMMARIZER": (2, 1),
    "MODE_SIX_CODES": (3, 0),
    "MODE_QA": (4, 0), "MODE_SFT": (4, 1), "MODE_HOME": (4, 2)
}

# 處理跨模組跳轉請求
if "app_mode" in st.session_state:
    raw_mode = str(st.session_state["app_mode"])
    matched = False
    for k, (ws_idx, sub_idx) in LEGACY_ROUTE_MAP.items():
        if k in raw_mode:
            st.session_state["active_workspace_idx"] = ws_idx
            matched = True
            break
    if not matched:
        if any(w in raw_mode for w in ["評分", "試卷", "手寫"]):
            st.session_state["active_workspace_idx"] = 0
        elif any(w in raw_mode for w in ["出題", "命題", "模擬"]):
            st.session_state["active_workspace_idx"] = 1
        elif any(w in raw_mode for w in ["檢索", "裁判", "要旨"]):
            st.session_state["active_workspace_idx"] = 2
        elif any(w in raw_mode for w in ["六法", "法條"]):
            st.session_state["active_workspace_idx"] = 3
        elif any(w in raw_mode for w in ["問答", "諮詢", "筆記", "首頁"]):
            st.session_state["active_workspace_idx"] = 4

cur_ws_idx = st.session_state.get("active_workspace_idx", 0)
if cur_ws_idx >= len(WORKSPACES):
    cur_ws_idx = 0

# 4. 側邊欄簡潔專業導航
with st.sidebar:
    st.markdown("### ⚖️ 司律法學 AI 旗艦")
    st.caption("Taiwan Bar Exam & Judicial AI Suite")

    # API Key 設定 (安全隱碼與記憶體快取)
    api_key_val = get_gemini_api_key()
    user_key = st.text_input(
        "🔑 Gemini API Key (可選)：",
        value=api_key_val,
        type="password",
        help="金鑰僅暫存於當前工作階段記憶體，絕不寫入公開日誌。"
    )
    if user_key and user_key.strip():
        os.environ["GEMINI_API_KEY"] = user_key.strip()

    st.divider()

    # 五大工作區單選導航
    selected_workspace = st.radio(
        "🗂️ 核心工作區：",
        WORKSPACES,
        index=cur_ws_idx,
        key="main_workspace_radio"
    )
    new_idx = WORKSPACES.index(selected_workspace) if selected_workspace in WORKSPACES else cur_ws_idx
    if new_idx != st.session_state.get("active_workspace_idx"):
        st.session_state["active_workspace_idx"] = new_idx
        # 清除舊版 app_mode 防止反向鎖定
        st.session_state.pop("app_mode", None)

    # 側邊欄底部系統狀態徽章
    has_api = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    render_system_status_badge(is_api_ready=has_api, library_loaded=True)

# 5. 路由分發至獨立視圖模組
active_idx = st.session_state.get("active_workspace_idx", 0)

if active_idx == 0:
    workspace_grading.render_workspace()
elif active_idx == 1:
    workspace_testing.render_workspace()
elif active_idx == 2:
    workspace_research.render_workspace()
elif active_idx == 3:
    workspace_sixcodes.render_workspace()
elif active_idx == 4:
    workspace_qa_sft.render_workspace()
