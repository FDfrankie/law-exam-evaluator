"""
司律手寫試卷評分、出題、考古題庫與高分擬答大師 - Web 圖形介面 (Streamlit)
支援功能：
1. 首頁與系統導覽 (功能總覽・隱私權政策・法律聲明)
2. 試卷評閱：多模態手寫試卷辨識與四大維度評分
3. 司律出題：一試選擇題與二試實例題
4. 歷年真題庫：涵蓋台大法研所、台大轉學考、司法官律師、司法特考等真題演練
5. 高分擬答：榜首級 IRAC 三段論法擬答生成
6. 統一法學檢索樞紐與 AI 判決研析
7. 專屬法學全能問答樞紐
8. 一鍵 AI 裁判與長篇函釋要旨自動精鍊
9. 智慧六法與條文判解綜合標註
10. 手寫筆記蒸餾與 SFT 模型微調大庫
"""
import streamlit as st
import os
import sys

from config import init_directories, GOOGLE_DRIVE_DATA_DIR, get_gemini_api_key
from views.constants import (
    MODE_HOME,
    MODE_EVAL,
    MODE_GEN,
    MODE_BANK,
    MODE_ANS,
    MODE_SEARCH,
    MODE_QA,
    MODE_SUMMARIZER,
    MODE_SIX_CODES,
    MODE_SFT,
    ALL_MODES
)
from views import (
    render_mode_home,
    render_mode_eval,
    render_mode_gen,
    render_mode_bank,
    render_mode_ans,
    render_mode_search,
    render_mode_qa,
    render_mode_summarizer,
    render_mode_six_codes,
    render_mode_sft
)

# 設定頁面配置
st.set_page_config(
    page_title="司律考試 AI 評分與命題大師",
    page_icon="⚖️",
    layout="wide"
)

init_directories()

# 側邊欄導航
with st.sidebar:
    st.title("⚖️ 司律 AI 助手")
    st.markdown(f"**雲端同步位置**:  \n`{GOOGLE_DRIVE_DATA_DIR}`")
    st.divider()

    mode_options = ALL_MODES
    if "app_mode" not in st.session_state:
        st.session_state["app_mode"] = MODE_HOME
    elif st.session_state["app_mode"] not in mode_options:
        old_val = str(st.session_state["app_mode"])
        if "首頁" in old_val or "導覽" in old_val:
            st.session_state["app_mode"] = MODE_HOME
        elif "評分" in old_val or "手寫" in old_val:
            st.session_state["app_mode"] = MODE_EVAL
        elif "出題" in old_val or "模擬" in old_val:
            st.session_state["app_mode"] = MODE_GEN
        elif "歷年真題" in old_val or "題庫" in old_val:
            st.session_state["app_mode"] = MODE_BANK
        elif "擬答" in old_val or "權威" in old_val:
            st.session_state["app_mode"] = MODE_ANS
        elif "統一法學檢索" in old_val or "判決研析" in old_val or "爭點查詢" in old_val:
            st.session_state["app_mode"] = MODE_SEARCH
        elif "全能問答" in old_val or "法學諮詢" in old_val or "法律諮詢" in old_val or "生活法律" in old_val or "萬能檢索" in old_val or "專屬法學" in old_val:
            st.session_state["app_mode"] = MODE_QA
        elif "AI 裁判" in old_val or "AI 摘要" in old_val or "AI裁判" in old_val or "精鍊" in old_val or "起訴書" in old_val or "開放資料" in old_val:
            st.session_state["app_mode"] = MODE_SUMMARIZER
        elif "智慧六法" in old_val or "六法" in old_val or "函釋" in old_val:
            st.session_state["app_mode"] = MODE_SIX_CODES
        elif "手寫筆記蒸餾" in old_val or "SFT" in old_val:
            st.session_state["app_mode"] = MODE_SFT
        else:
            st.session_state["app_mode"] = MODE_HOME

    # 雙向導航同步機制：
    # 1. 若頁面內按鈕要求切換（st.session_state["app_mode"] 被按鈕程式化變更且與前次渲染不同），同步至 Radio
    # 2. 若使用者於側邊欄點選 Radio，同步至 st.session_state["app_mode"]
    # 3. 杜絕因強制覆寫 Radio 導致的「點選後紅點跳一下但頁面不切換」現象
    last_rendered_mode = st.session_state.get("_last_rendered_mode", None)

    if last_rendered_mode is None:
        st.session_state["main_app_nav_radio"] = st.session_state["app_mode"]
    elif st.session_state["app_mode"] != last_rendered_mode:
        # 頁面內按鈕或外部程式要求切換目標模式
        st.session_state["main_app_nav_radio"] = st.session_state["app_mode"]
    elif "main_app_nav_radio" in st.session_state and st.session_state["main_app_nav_radio"] in mode_options:
        # 使用者點擊了側邊欄 Radio 元件
        st.session_state["app_mode"] = st.session_state["main_app_nav_radio"]

    cur_mode = st.session_state["app_mode"]
    cur_idx = mode_options.index(cur_mode) if cur_mode in mode_options else 0

    app_mode = st.radio(
        "選擇功能模式：",
        mode_options,
        index=cur_idx,
        key="main_app_nav_radio"
    )
    st.session_state["app_mode"] = app_mode
    st.session_state["_last_rendered_mode"] = app_mode

    api_key = get_gemini_api_key()
    if not api_key:
        st.warning("⚠️ 尚未偵測到 API Key！請在 Streamlit Cloud 的 Secrets 設定 `GEMINI_API_KEY`，或在下方直接輸入：")
        user_key = st.text_input("輸入 Gemini API Key：", type="password")
        if user_key.strip():
            os.environ["GEMINI_API_KEY"] = user_key.strip()
            st.success("API Key 已套用！")
    else:
        st.success("🟢 AI 核心引擎已就緒 (Gemini 視覺多模態)")
    st.info("💡 支援檔案：手寫/打字 PDF、照片 (JPG/PNG/WEBP)、Word (.docx)")


# ----------------- 模式路由調度 -----------------
if app_mode == MODE_HOME:
    render_mode_home()
elif app_mode == MODE_EVAL or "試卷評分" in app_mode:
    render_mode_eval()
elif app_mode == MODE_GEN or "模擬出題" in app_mode:
    render_mode_gen()
elif app_mode == MODE_BANK or "歷年真題" in app_mode:
    render_mode_bank()
elif app_mode == MODE_ANS or "擬答生成" in app_mode:
    render_mode_ans()
elif app_mode == MODE_SEARCH or "統一法學檢索" in app_mode:
    render_mode_search()
elif app_mode == MODE_QA or "全能問答" in app_mode:
    render_mode_qa()
elif app_mode == MODE_SUMMARIZER or "一鍵 AI 裁判" in app_mode:
    render_mode_summarizer()
elif app_mode == MODE_SIX_CODES or "智慧六法" in app_mode:
    render_mode_six_codes()
elif app_mode == MODE_SFT or "手寫筆記蒸餾" in app_mode:
    render_mode_sft()
