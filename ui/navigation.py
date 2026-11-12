"""Canonical cross-mode navigation & Streamlit widget-key pre-sync helpers."""

from typing import Any, Dict, Iterable, Optional, Union
import streamlit as st

PENDING_PREFIX = "_pending_"

M5_SUB_ADVANCED_SEARCH = "⚖️ 裁判書多維專業檢索 (支援布林語法)"
M5_SUB_UNIFIED_CORPUS = "🌐 全方位法學大典藏跨庫檢索 (裁判/判例/釋字/命令/法律)"
M5_SUB_HOT_SEARCH = "⚡ 權威實務裁判與先例即時檢索"
M5_SUB_APPEAL_CHAIN = "🌿 審級更迭與歷審脈絡鏈"
M5_SUB_ADMIN_ORDERS = "📜 全國行政法規命令與部會要點"
M5_SUB_ISSUES = "🤖 司律二試核心爭點與 IRAC 實務法理"
M5_SUB_DISTINGUISHING = "🔄 裁判見解分歧與案例橫向比對"

M5_SUB_MODES = [
    M5_SUB_ADVANCED_SEARCH,
    M5_SUB_UNIFIED_CORPUS,
    M5_SUB_HOT_SEARCH,
    M5_SUB_APPEAL_CHAIN,
    M5_SUB_ADMIN_ORDERS,
    M5_SUB_ISSUES,
    M5_SUB_DISTINGUISHING,
]

_LEGACY_M5_INT_MAP = {
    0: M5_SUB_ADVANCED_SEARCH,
    1: M5_SUB_HOT_SEARCH,
    2: M5_SUB_APPEAL_CHAIN,
    3: M5_SUB_ISSUES,
    4: M5_SUB_DISTINGUISHING,
}


def resolve_m5_sub_mode(raw_sub: Union[str, int, None]) -> str:
    """Resolve string or legacy integer sub-mode specifier into canonical MODE_SEARCH label."""
    if isinstance(raw_sub, str):
        if raw_sub in M5_SUB_MODES:
            return raw_sub
        for item in M5_SUB_MODES:
            if raw_sub in item:
                return item
        return M5_SUB_ADVANCED_SEARCH
    if isinstance(raw_sub, int):
        if raw_sub in _LEGACY_M5_INT_MAP:
            return _LEGACY_M5_INT_MAP[raw_sub]
        if 0 <= raw_sub < len(M5_SUB_MODES):
            return M5_SUB_MODES[raw_sub]
    return M5_SUB_ADVANCED_SEARCH


def set_pending_widget_value(widget_key: str, value: Any) -> None:
    """Queue a widget value update safely via _pending_<key> before next rerun."""
    st.session_state[f"{PENDING_PREFIX}{widget_key}"] = value


def sync_pending_widget_keys(keys: Iterable[str]) -> None:
    """Flush queued _pending_<key> values into widget keys BEFORE widget instantiation."""
    for key in keys:
        p_key = f"{PENDING_PREFIX}{key}"
        if p_key in st.session_state:
            st.session_state[key] = st.session_state.pop(p_key)


def navigate_to(
    target_mode: str,
    *,
    sub_mode: Union[str, int, None] = None,
    pending_widgets: Optional[Dict[str, Any]] = None,
    extra_state: Optional[Dict[str, Any]] = None,
    rerun: bool = True,
) -> None:
    """Navigate cleanly across modes and sub-modes using pre-instantiation pending widget sync."""
    st.session_state["app_mode"] = target_mode
    st.session_state["nav_sidebar_radio_mode"] = target_mode
    st.session_state["main_app_nav_radio"] = target_mode

    if sub_mode is not None:
        canonical_sub = resolve_m5_sub_mode(sub_mode)
        st.session_state["m5_sub_mode_idx"] = canonical_sub
        set_pending_widget_value("m5_sub_module_radio", canonical_sub)

    if extra_state:
        for k, v in extra_state.items():
            st.session_state[k] = v

    if pending_widgets:
        for wk, wv in pending_widgets.items():
            set_pending_widget_value(wk, wv)

    if rerun:
        st.rerun()
