"""
可重用法學 UI 元件庫 (Reusable Legal UI Components)
包含：
1. 試卷評分 KPI Metric Cards 與 Side-by-Side Diff 雙欄對照
2. 智慧六法飾條引述卡、關鍵詞高亮與內建水平 Tabs
3. 外部 8 大法學資料庫緊湊單行 Pill 標籤列
4. 安全高效的 pypdfium2 PDF 預覽元件
5. 系統狀態徽章 Footer
"""

import io
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import streamlit as st
from PIL import Image

def render_kpi_metrics(
    total_score: int,
    grade_level: str = "上位卷 (前 15%)",
    issue_score: int = 22,
    irac_score: int = 21,
    subsumption_score: int = 42
):
    """渲染 4 張專業 KPI Metric 指標卡片與進度條"""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        badge_bg = "#DCFCE7" if total_score >= 70 else ("#FEF3C7" if total_score >= 50 else "#FEE2E2")
        badge_color = "#166534" if total_score >= 70 else ("#92400E" if total_score >= 50 else "#991B1B")
        st.markdown(f"""
        <div class="kpi-metric-card">
            <div class="kpi-metric-title">📊 綜合總分評定</div>
            <div class="kpi-metric-val">{total_score} <span style="font-size:1rem;color:#64748B;">/ 100</span></div>
            <div class="kpi-metric-badge" style="background:{badge_bg};color:{badge_color};">{grade_level}</div>
        </div>
        """, unsafe_allow_html=True)
        st.progress(min(1.0, max(0.0, total_score / 100.0)))

    with col2:
        st.markdown(f"""
        <div class="kpi-metric-card">
            <div class="kpi-metric-title">🎯 爭點意識與定性</div>
            <div class="kpi-metric-val">{issue_score} <span style="font-size:1rem;color:#64748B;">/ 25</span></div>
            <div class="kpi-metric-badge" style="background:#E0E7FF;color:#3730A3;">配分比 25%</div>
        </div>
        """, unsafe_allow_html=True)
        st.progress(min(1.0, max(0.0, issue_score / 25.0)))

    with col3:
        st.markdown(f"""
        <div class="kpi-metric-card">
            <div class="kpi-metric-title">⚖️ 法理邏輯三段論</div>
            <div class="kpi-metric-val">{irac_score} <span style="font-size:1rem;color:#64748B;">/ 25</span></div>
            <div class="kpi-metric-badge" style="background:#E0E7FF;color:#3730A3;">配分比 25%</div>
        </div>
        """, unsafe_allow_html=True)
        st.progress(min(1.0, max(0.0, irac_score / 25.0)))

    with col4:
        st.markdown(f"""
        <div class="kpi-metric-card">
            <div class="kpi-metric-title">🏛️ 實務學說與涵攝</div>
            <div class="kpi-metric-val">{subsumption_score} <span style="font-size:1rem;color:#64748B;">/ 50</span></div>
            <div class="kpi-metric-badge" style="background:#FEF3C7;color:#92400E;">配分比 50%</div>
        </div>
        """, unsafe_allow_html=True)
        st.progress(min(1.0, max(0.0, subsumption_score / 50.0)))


def render_side_by_side_diff(user_ocr_text: str, benchmark_model_text: str):
    """
    考生手寫謄錄 vs 閱卷委員示範擬答 左右雙欄對照檢視 (Side-by-Side Diff View)
    """
    st.markdown("#### 🔍 試卷作答與上位改寫雙欄對照 (Side-by-Side View)")
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("""
        <div style="background:#FFFFFF;border:1px solid #CBD5E1;border-radius:8px;padding:14px;min-height:300px;">
            <div style="font-weight:700;color:#0F172A;margin-bottom:8px;display:flex;align-items:center;">
                📝 考生原始手寫謄錄作答 (OCR 辨識)
            </div>
            <div class="ocr-transcription-text" style="white-space:pre-wrap;">
        """ + (user_ocr_text.strip() if user_ocr_text else "尚未輸入或辨識考生作答文字") + """
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col_right:
        st.markdown("""
        <div style="background:#F0FDF4;border:1px solid #86EFAC;border-radius:8px;padding:14px;min-height:300px;">
            <div style="font-weight:700;color:#166534;margin-bottom:8px;display:flex;align-items:center;">
                🌟 閱卷委員標準上位改寫示範 (IRAC 強化)
            </div>
            <div class="ocr-transcription-text" style="white-space:pre-wrap;color:#14532D;">
        """ + (benchmark_model_text.strip() if benchmark_model_text else "正在結合上位卷評分標準生成示範擬答...") + """
            </div>
        </div>
        """, unsafe_allow_html=True)


def highlight_statutory_keywords(raw_text: str) -> str:
    """自動標記高亮但書、準用、視為等法條核心關鍵詞"""
    if not raw_text:
        return ""
    # 但書
    highlighted = re.sub(
        r'(但[^\n，。；]+(?:不在此限|得[^\n，。；]+|除[^\n，。；]+外))',
        r'<span class="kw-proviso">\1</span>',
        raw_text
    )
    # 視為
    highlighted = re.sub(
        r'(視為[^\n，。；]*)',
        r'<span class="kw-deem">\1</span>',
        highlighted
    )
    # 準用
    highlighted = re.sub(
        r'(準用[^\n，。；]*)',
        r'<span class="kw-apply">\1</span>',
        highlighted
    )
    return highlighted


def render_statutory_card(
    law_name: str,
    article_no: str,
    content: str,
    annotations: Optional[Dict[str, Any]] = None
):
    """
    智慧六法條文卡片：左飾條引述框 + 關鍵詞高亮 + 內建水平 tabs (立法理由、裁判、函釋、筆記)
    """
    clean_no = str(article_no).replace(" ", "").replace("第", "").replace("條", "")
    highlighted_content = highlight_statutory_keywords(content)

    st.markdown(f"""
    <div class="statute-quote-card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <span style="font-size:1.15rem;font-weight:700;color:#1E3A8A;">
                📖 {law_name} 第 {clean_no} 條
            </span>
        </div>
        <div class="statute-article-body">
            {highlighted_content}
        </div>
    </div>
    """, unsafe_allow_html=True)

    if annotations:
        t_hist, t_prec, t_admin, t_notes = st.tabs([
            "📜 立法理由與沿革",
            "⚖️ 大法庭與權威裁判",
            "🏛️ 主管機關行政函釋",
            "📝 個人筆記與講義"
        ])
        with t_hist:
            leg_details = annotations.get("legislative_details", {})
            reasons = leg_details.get("legislative_reasons", [])
            if reasons:
                for r in reasons[:3]:
                    st.caption(f"**【{r.get('date', '修法日期')} 修正理由】**：")
                    st.write(r.get("reason", "無詳細說明"))
            else:
                st.info("此條文無特別歷史立法修正理由紀錄。")

        with t_prec:
            precedents = annotations.get("precedents", [])
            if precedents:
                for p in precedents[:4]:
                    st.markdown(f"**{p.get('case_id', '實務裁判')}** `{p.get('court', '')}`")
                    st.caption(p.get("summary", p.get("holding", ""))[:180] + "...")
            else:
                st.info("暫無直接標註之特定實務裁判。")

        with t_admin:
            rulings = annotations.get("admin_rulings", [])
            if rulings:
                for r in rulings[:3]:
                    st.markdown(f"**{r.get('title', '行政函釋')}**")
                    st.caption(r.get("holding", "")[:180] + "...")
            else:
                st.info("暫無相關主管機關行政函釋。")

        with t_notes:
            notes = annotations.get("notes", []) or annotations.get("handouts", [])
            if notes:
                for n in notes[:3]:
                    st.markdown(f"📘 **{n.get('filename', '筆記講義')}**")
                    if n.get("summary"):
                        st.caption(n.get("summary")[:120] + "...")
            else:
                st.info("目前尚無此法條關聯之個人手寫或課輔筆記。")


def render_inline_action_pills():
    """外部 8 大法學資料庫緊湊單行 Pill 標籤列"""
    databases = [
        ("司法院裁判書", "https://judgment.judicial.gov.tw/FJUD/Default.aspx"),
        ("全國法規資料庫", "https://law.moj.gov.tw/"),
        ("憲法法庭裁判", "https://cons.judicial.gov.tw/"),
        ("立法院法律系統", "https://lis.ly.gov.tw/lglawc/lglawkm"),
        ("法務部主管法規", "https://mojlaw.moj.gov.tw/"),
        ("考選部歷屆試題", "https://wwwq.moex.gov.tw/exam/wFrmExamQandA.aspx"),
        ("金管會法令函釋", "https://law.fsc.gov.tw/"),
        ("智財局法規解釋", "https://topic.tipo.gov.tw/patents-tw/np-677-101.html")
    ]
    pills_html = '<div class="action-pills-container"><span style="font-size:0.85rem;font-weight:600;color:#64748B;margin-right:4px;">🌐 權威法學外庫直連：</span>'
    for name, url in databases:
        pills_html += f'<a class="action-pill" href="{url}" target="_blank">{name} ↗</a>'
    pills_html += '</div>'
    st.markdown(pills_html, unsafe_allow_html=True)


def render_safe_pdf_viewer(file_path_or_bytes, max_pages: int = 4):
    """
    使用 pypdfium2 高效安全渲染 PDF 頁面預覽圖，杜絕 Base64 iframe 在行動裝置或大檔崩潰問題
    """
    if not file_path_or_bytes:
        st.info("無可預覽之 PDF 檔案。")
        return

    try:
        import pypdfium2 as pdfium
        if isinstance(file_path_or_bytes, (str, Path)):
            pdf = pdfium.PdfDocument(str(file_path_or_bytes))
        else:
            pdf = pdfium.PdfDocument(file_path_or_bytes)

        page_count = len(pdf)
        st.caption(f"📄 檔案總頁數：共 {page_count} 頁（預覽前 {min(page_count, max_pages)} 頁）")

        render_count = min(page_count, max_pages)
        for i in range(render_count):
            page = pdf.get_page(i)
            # scale=1.5 提供清晰文字渲染
            pil_image = page.render(scale=1.5).to_pil()
            st.image(pil_image, caption=f"第 {i+1} 頁", use_container_width=True)

    except Exception as e:
        st.warning(f"PDF 預覽圖渲染暫不可用 ({e})，請點擊下方按鈕直接下載原檔閱讀。")

    # 提供原檔下載按鈕
    if isinstance(file_path_or_bytes, (str, Path)):
        p = Path(file_path_or_bytes)
        if p.exists():
            with open(p, "rb") as f:
                st.download_button(
                    label=f"💾 下載完整 PDF ({p.name})",
                    data=f.read(),
                    file_name=p.name,
                    mime="application/pdf"
                )
    elif isinstance(file_path_or_bytes, bytes):
        st.download_button(
            label="💾 下載完整 PDF 檔案",
            data=file_path_or_bytes,
            file_name="law_document.pdf",
            mime="application/pdf"
        )


def render_system_status_badge(is_api_ready: bool = True, library_loaded: bool = True):
    """側邊欄底部簡潔狀態徽章"""
    status_gemini = "🟢 Gemini 引擎就緒" if is_api_ready else "🟡 待輸入 API Key"
    status_lib = "📚 本地法學庫已載入" if library_loaded else "⏳ 資料載入中"
    st.markdown(f"""
    <div class="system-status-footer">
        <div><strong>系統運行狀態</strong></div>
        <div style="margin-top:4px;">{status_gemini}</div>
        <div style="margin-top:2px;">{status_lib}</div>
    </div>
    """, unsafe_allow_html=True)
