"""
專業法學視覺設計系統 (LegalTech Editorial Style CSS)
包含深邃藏青藍 (#1E3A8A)、典雅琥珀金 (#D97706)、沉穩灰白 (#F8FAFC)
襯線體 (Noto Serif TC) 條文裁判呈現與緊湊響應式排版。
"""

import streamlit as st

GLOBAL_CSS = """
<style>
/* 匯入 Google Fonts: 思源黑體 (Noto Sans TC) 與 思源宋體 (Noto Serif TC) */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+TC:wght@400;500;600;700&family=Noto+Serif+TC:wght@400;600;700&display=swap');

:root {
    --primary-blue: #1E3A8A;
    --accent-gold: #D97706;
    --bg-slate: #F8FAFC;
    --card-surface: #FFFFFF;
    --border-subtle: #E2E8F0;
    --text-main: #0F172A;
    --text-muted: #64748B;
}

html, body, [class*="css"] {
    font-family: 'Noto Sans TC', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    color: var(--text-main);
    background-color: var(--bg-slate);
}

/* 內容卡片全面圓角投影現代化 */
.legal-card {
    background: var(--card-surface);
    border: 1px solid var(--border-subtle);
    border-radius: 12px;
    padding: 22px 24px;
    margin-bottom: 20px;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04), 0 1px 2px rgba(15, 23, 42, 0.02);
    transition: box-shadow 0.2s ease, border-color 0.2s ease;
}

.legal-card:hover {
    border-color: #CBD5E1;
    box-shadow: 0 4px 6px -1px rgba(15, 23, 42, 0.08), 0 2px 4px -1px rgba(15, 23, 42, 0.04);
}

/* 法條全文與裁判主文專業襯線體閱讀排版 */
.statute-article-body, .judicial-verdict-text, .ocr-transcription-text {
    font-family: 'Noto Serif TC', Georgia, 'Times New Roman', serif !important;
    font-size: 1.05rem !important;
    line-height: 1.85 !important;
    color: #1E293B !important;
    letter-spacing: 0.02em;
}

/* 條文引述左飾條藍色卡片 */
.statute-quote-card {
    border-left: 5px solid var(--primary-blue);
    background-color: #F8FAFC;
    border-top: 1px solid var(--border-subtle);
    border-right: 1px solid var(--border-subtle);
    border-bottom: 1px solid var(--border-subtle);
    border-radius: 4px 10px 10px 4px;
    padding: 16px 20px;
    margin: 12px 0 16px 0;
}

/* 法條關鍵詞自動高亮 */
.kw-proviso {
    background-color: #FEF3C7;
    color: #92400E;
    font-weight: 600;
    padding: 1px 4px;
    border-radius: 3px;
    border-bottom: 2px solid #D97706;
}

.kw-deem {
    background-color: #E0E7FF;
    color: #3730A3;
    font-weight: 600;
    padding: 1px 4px;
    border-radius: 3px;
    border-bottom: 2px solid #4F46E5;
}

.kw-apply {
    background-color: #DCFCE7;
    color: #166534;
    font-weight: 600;
    padding: 1px 4px;
    border-radius: 3px;
    border-bottom: 2px solid #16A34A;
}

/* 緊湊單行 Inline Action Pills 標籤列 */
.action-pills-container {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin: 10px 0 18px 0;
}

.action-pill {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
    font-size: 0.85rem;
    font-weight: 500;
    color: #334155;
    background-color: #F1F5F9;
    border: 1px solid #E2E8F0;
    border-radius: 9999px;
    text-decoration: none;
    transition: all 0.15s ease;
}

.action-pill:hover {
    background-color: var(--primary-blue);
    color: #FFFFFF !important;
    border-color: var(--primary-blue);
    text-decoration: none;
}

/* KPI 評分指標卡片 */
.kpi-metric-card {
    background: #FFFFFF;
    border: 1px solid var(--border-subtle);
    border-radius: 10px;
    padding: 16px;
    text-align: center;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
}

.kpi-metric-title {
    font-size: 0.85rem;
    color: var(--text-muted);
    font-weight: 500;
    margin-bottom: 4px;
}

.kpi-metric-val {
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--primary-blue);
}

.kpi-metric-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 600;
    margin-top: 6px;
}

/* 側邊欄優化降噪 */
[data-testid="stSidebar"] {
    background-color: #0F172A;
    color: #F8FAFC;
}

[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] span {
    color: #E2E8F0;
}

[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
    color: #FFFFFF !important;
}

/* 膠囊型頁籤 Tabs 現代美化 */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background-color: #F1F5F9;
    padding: 6px;
    border-radius: 10px;
}

.stTabs [data-baseweb="tab"] {
    height: 38px;
    border-radius: 6px;
    font-weight: 600;
    font-size: 0.92rem;
    color: #475569;
    padding: 0 16px;
}

.stTabs [aria-selected="true"] {
    background-color: #FFFFFF !important;
    color: var(--primary-blue) !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08) !important;
}

/* 系統狀態徽章 Footer */
.system-status-footer {
    padding: 14px 16px;
    background-color: rgba(255, 255, 255, 0.05);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 8px;
    font-size: 0.82rem;
    color: #94A3B8;
    margin-top: 24px;
}
</style>
"""

def inject_custom_css():
    """注入全域專業法學視覺主題 CSS"""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
