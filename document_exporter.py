# -*- coding: utf-8 -*-

"""

document_exporter.py

====================

專業法學文書與國考成果 Word (.docx) / PDF (.pdf) 雙規格高階匯出引擎。

支援：

1. 司律試卷閱卷診斷報告 (完整四大維度評分、開標分析、爭點命中與改寫示範) - DOCX / PDF

2. 司律二試榜首水準示範擬答 (IRAC 標準排版與權威判解註釋) - DOCX / PDF

3. 中華民國郵局標準格式存證信函與調解聲請要旨 (可直接列印寄發) - DOCX / PDF

4. 體系導引式專題法學教科書 (離線研讀專用 A4 排版講義) - DOCX / PDF

5. 司律一試選擇題全真考卷與逐題法理詳解 - DOCX / PDF

6. 訴訟程序策略與實務評估建議書 - DOCX / PDF (恪遵律師法，僅提供策略評估與法律分析)

"""



import io

import re

from typing import Dict, Any, List, Optional



import docx

from docx.shared import Pt, Inches, RGBColor

from docx.enum.text import WD_ALIGN_PARAGRAPH

from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL

from docx.oxml import OxmlElement

from docx.oxml.ns import qn



try:

    import pymupdf

    HAS_PYMUPDF = True

except ImportError:

    try:

        import fitz as pymupdf

        HAS_PYMUPDF = True

    except ImportError:

        HAS_PYMUPDF = False





# =============================================================================

# A. Word (.docx) 排版公用底層

# =============================================================================



def _set_cell_background(cell, hex_color: str):

    """設定表格單元格背景底色 (RGB 十六進制字串，如 'F1F5F9')"""

    tc_pr = cell._tc.get_or_add_tcPr()

    shd = OxmlElement('w:shd')

    shd.set(qn('w:val'), 'clear')

    shd.set(qn('w:color'), 'auto')

    shd.set(qn('w:fill'), hex_color.replace('#', ''))

    tc_pr.append(shd)





def _set_cell_margins(cell, top=100, bottom=100, left=150, right=150):

    """設定單元格內邊距"""

    tc_pr = cell._tc.get_or_add_tcPr()

    tc_mar = OxmlElement('w:tcMar')

    for m_name, m_val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:

        node = OxmlElement(f'w:{m_name}')

        node.set(qn('w:w'), str(m_val))

        node.set(qn('w:type'), 'dxa')

        tc_mar.append(node)

    tc_pr.append(tc_mar)





def _init_legal_doc() -> docx.Document:

    """初始化具備標準台灣法學排版規範之 Word 文件物件"""

    doc = docx.Document()

    for section in doc.sections:

        section.top_margin = Inches(1.0)

        section.bottom_margin = Inches(1.0)

        section.left_margin = Inches(1.0)

        section.right_margin = Inches(1.0)



    style = doc.styles['Normal']

    font = style.font

    font.name = 'Microsoft JhengHei'

    font.size = Pt(11)

    font.color.rgb = RGBColor(30, 41, 59)

    style.paragraph_format.line_spacing = 1.25

    style.paragraph_format.space_after = Pt(6)



    return doc





# =============================================================================
# B. PDF 專業法學排版核心 (PyMuPDF Engine)
# =============================================================================

_PDF_SYMBOL_MAP = {
    "✅": "[核驗通過]",
    "✔": "[核驗通過]",
    "☑️": "[已勾選]",
    "☑": "[已勾選]",
    "❌": "[未通過]",
    "✖": "[未通過]",
    "❎": "[未通過]",
    "⚠️": "[警示]",
    "⚠": "[警示]",
    "⚖️": "[法學]",
    "⚖": "[法學]",
    "📌": "【重點】",
    "📍": "【重點】",
    "🏛️": "[司法實務]",
    "🏛": "[司法實務]",
    "📜": "[法條]",
    "💡": "[解析]",
    "🔍": "[檢索]",
    "🔎": "[檢索]",
    "🛡️": "[防偽核驗]",
    "🛡": "[防偽核驗]",
    "📮": "[存證文書]",
    "📋": "[試卷]",
    "📖": "[教材]",
    "📚": "[文獻]",
    "🏆": "[示範擬答]",
    "🌟": "[亮點]",
    "✨": "[亮點]",
    "🔗": "[連結]",
    "⚪": "[未作答]",
    "🔴": "[錯誤]",
    "🟢": "[正確]",
    "🟡": "[注意]",
    "🎯": "【核心】",
    "📝": "[作答]",
    "✍️": "[手寫]",
    "✍": "[手寫]",
    "📊": "[統計]",
    "📈": "[分析]",
    "🎓": "[考試]",
    "📄": "[文件]",
    "💬": "[評語]",
    "❓": "[問題]",
    "👥": "[社群]",
    "🆕": "[最新]",
    "🚀": "",
    "➔": "->",
    "➜": "->",
    "➝": "->",
    "➡️": "->",
    "➡": "->",
    "→": "->",
    "←": "<-",
    "👇": "",
    "👉": "->",
    "🔹": "•",
    "🔸": "•",
    "▪": "•",
    "▫": "•",
}

_PDF_SYMBOL_PATTERN = re.compile(
    "|".join(re.escape(k) for k in sorted(_PDF_SYMBOL_MAP.keys(), key=len, reverse=True))
)
_UNSUPPORTED_EMOJI_RE = re.compile(
    r"[\uFE0E\uFE0F\u200D\u200B\uFEFF\U0001F000-\U0001FAFF]+"
)
_UNSUPPORTED_DINGBAT_RE = re.compile(r"[\u2600-\u2604\u2606-\u27BF]+")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _sanitize_pdf_text(text: Any) -> str:
    """將 PyMuPDF china-t 字型不支援的 Emoji 與特殊符號轉換為清晰 CJK/ASCII 標籤，避免出現 □ 方框。"""
    if text is None:
        return ""
    s = str(text)
    if not s:
        return ""
    s = _PDF_SYMBOL_PATTERN.sub(lambda m: _PDF_SYMBOL_MAP[m.group(0)], s)
    s = _UNSUPPORTED_EMOJI_RE.sub("", s)
    s = _UNSUPPORTED_DINGBAT_RE.sub("", s)
    return s


def _clean_inline_markdown(text: str) -> str:
    """清理 Markdown 連結與反引號標記並執行 PDF 字元淨化。"""
    s = _sanitize_pdf_text(text)
    s = _MD_LINK_RE.sub(r"\1", s)
    s = s.replace("`", "")
    return s


def _split_bold_spans(line: str) -> List[tuple]:
    """將單行文字中的 **粗體** 拆分為 [(segment_text, is_bold), ...]。"""
    parts = re.split(r"(\*\*[^*\n]+?\*\*)", line)
    spans: List[tuple] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            spans.append((part[2:-2], True))
        else:
            cleaned = part.replace("**", "")
            if cleaned:
                spans.append((cleaned, False))
    return spans


class LegalPdfDocument:
    """
    兼具繁體中文字型支援、自動分頁、頁首頁尾與高雅法學配色的 PDF 產生器
    """

    def __init__(self, title="台灣法學研析報告", margin=45):
        if not HAS_PYMUPDF:
            raise RuntimeError("未安裝 pymupdf 套件，無法產出 PDF 文件！")
        self.doc = pymupdf.open()
        self.title = _sanitize_pdf_text(title)
        self.margin = margin
        self.width = 595.32   # A4 width in pt
        self.height = 841.92  # A4 height in pt
        self.max_width = self.width - (2 * self.margin)
        self.font_name = "china-t"
        self.font = pymupdf.Font("china-t")
        self.pages = []
        self.cur_page = None
        self.cur_y = self.margin + 25
        self._new_page()

    def _new_page(self):
        page = self.doc.new_page(width=self.width, height=self.height)
        self.pages.append(page)
        self.cur_page = page
        self.cur_y = self.margin + 25
        # 頂部裝飾線與頁首文件題名
        page.draw_line((self.margin, self.margin + 14), (self.width - self.margin, self.margin + 14), color=(0.7, 0.75, 0.8), width=0.8)
        page.insert_text((self.margin, self.margin + 10), self.title[:45], fontname=self.font_name, fontsize=8, color=(0.4, 0.45, 0.5))

    def ensure_space(self, needed_pt):
        if self.cur_y + needed_pt > self.height - self.margin - 25:
            self._new_page()

    def add_title(self, text):
        clean = _clean_inline_markdown(text).replace("**", "")
        title_lines = self._wrap_lines(clean, self.max_width, 15)
        needed = max(45, len(title_lines) * 20 + 22)
        self.ensure_space(needed)
        for t_line in title_lines or [clean]:
            self.cur_page.insert_text((self.margin, self.cur_y + 16), t_line, fontname=self.font_name, fontsize=15, color=(0.11, 0.21, 0.34))
            self.cur_y += 22
        self.cur_y += 2
        self.cur_page.draw_line((self.margin, self.cur_y), (self.width - self.margin, self.cur_y), color=(0.85, 0.88, 0.92), width=1.5)
        self.cur_y += 14

    def add_heading(self, text, level=2):
        size = 12 if level == 2 else 11
        clean = _clean_inline_markdown(text).replace("**", "")
        lines = self._wrap_lines(clean, self.max_width, size)
        needed = max(32, len(lines) * (size + 5) + 14)
        self.ensure_space(needed)
        self.cur_y += 6
        for h_line in lines or [clean]:
            self.cur_page.insert_text((self.margin, self.cur_y + size), h_line, fontname=self.font_name, fontsize=size, color=(0.12, 0.23, 0.54))
            self.cur_y += size + 5
        self.cur_y += 3

    def _wrap_lines(self, text, max_w, font_size):
        clean_text = _sanitize_pdf_text(text)
        lines = []
        for raw_line in clean_text.splitlines():
            if not raw_line.strip():
                lines.append("")
                continue
            cur_line = ""
            for char in raw_line:
                test_line = cur_line + char
                if self.font.text_length(test_line, font_size) > max_w:
                    lines.append(cur_line)
                    cur_line = char
                else:
                    cur_line = test_line
            if cur_line:
                lines.append(cur_line)
        return lines

    def _wrap_styled_spans(self, spans: List[tuple], max_w: float, font_size: float) -> List[List[tuple]]:
        """依 max_w 斷行同時保留每個字元的粗體屬性。"""
        wrapped: List[List[tuple]] = []
        cur_chars: List[tuple] = []
        cur_plain = ""

        def _flush_line():
            if not cur_chars:
                wrapped.append([])
                return
            merged: List[tuple] = []
            buf = ""
            prev_bold = cur_chars[0][1]
            for ch, b in cur_chars:
                if b == prev_bold:
                    buf += ch
                else:
                    merged.append((buf, prev_bold))
                    buf = ch
                    prev_bold = b
            if buf:
                merged.append((buf, prev_bold))
            wrapped.append(merged)

        for seg_text, is_bold in spans:
            for ch in seg_text:
                test_plain = cur_plain + ch
                if cur_plain and self.font.text_length(test_plain, font_size) > max_w:
                    _flush_line()
                    cur_chars = [(ch, is_bold)]
                    cur_plain = ch
                else:
                    cur_chars.append((ch, is_bold))
                    cur_plain = test_plain
        if cur_chars or not wrapped:
            _flush_line()
        return wrapped

    def _draw_styled_line(self, line_spans: List[tuple], x0: float, baseline_y: float, font_size: float, color: tuple):
        """繪製支援行內粗體視覺強化的文字行。"""
        cur_x = x0
        for seg_text, is_bold in line_spans:
            if not seg_text:
                continue
            if is_bold:
                bold_color = (
                    max(0.05, color[0] * 0.55),
                    max(0.08, color[1] * 0.55),
                    min(0.45, color[2] * 0.85 + 0.08),
                )
                self.cur_page.insert_text(
                    (cur_x, baseline_y),
                    seg_text,
                    fontname=self.font_name,
                    fontsize=font_size,
                    color=bold_color,
                    render_mode=2,
                    border_width=0.025,
                )
            else:
                self.cur_page.insert_text(
                    (cur_x, baseline_y),
                    seg_text,
                    fontname=self.font_name,
                    fontsize=font_size,
                    color=color,
                )
            cur_x += self.font.text_length(seg_text, font_size)

    def _render_styled_text_block(self, line_text: str, x0: float, max_w: float, font_size: float, color: tuple, line_spacing: float, left_bar_x: Optional[float] = None):
        """渲染單段可包含 **bold** 的自動換行文字。"""
        cleaned = _clean_inline_markdown(line_text)
        spans = _split_bold_spans(cleaned)
        wrapped_lines = self._wrap_styled_spans(spans, max_w, font_size)
        line_height = font_size * line_spacing
        for w_line in wrapped_lines:
            self.ensure_space(line_height)
            if left_bar_x is not None:
                self.cur_page.draw_line(
                    (left_bar_x, self.cur_y + 1),
                    (left_bar_x, self.cur_y + line_height - 1),
                    color=(0.45, 0.58, 0.78),
                    width=2.0,
                )
            self._draw_styled_line(w_line, x0, self.cur_y + font_size, font_size, color)
            self.cur_y += line_height

    def add_paragraph(self, text, font_size=10, indent=0, color=(0.15, 0.2, 0.25), line_spacing=1.35):
        sanitized = _sanitize_pdf_text(text)
        raw_lines = sanitized.splitlines()
        max_w = max(40.0, self.max_width - indent)
        i = 0
        while i < len(raw_lines):
            raw = raw_lines[i]
            stripped = raw.strip()

            if not stripped:
                self.cur_y += font_size * 0.45
                i += 1
                continue

            # Markdown 水平分隔線
            if re.match(r"^[-*=]{3,}$", stripped):
                self.ensure_space(10)
                self.cur_page.draw_line(
                    (self.margin + indent, self.cur_y + 4),
                    (self.width - self.margin, self.cur_y + 4),
                    color=(0.82, 0.85, 0.90),
                    width=0.7,
                )
                self.cur_y += 9
                i += 1
                continue

            # Markdown Pipe Table 區塊解析
            if stripped.startswith("|") and stripped.count("|") >= 2:
                table_lines = []
                j = i
                while j < len(raw_lines):
                    cand = raw_lines[j].strip()
                    if cand.startswith("|") and cand.count("|") >= 2:
                        table_lines.append(cand)
                        j += 1
                    else:
                        break
                parsed_rows = []
                for t_line in table_lines:
                    cells = [c.strip() for c in t_line.strip().strip("|").split("|")]
                    if cells and all(re.match(r"^:?-{2,}:?$", c.replace(" ", "")) for c in cells if c != ""):
                        if any(re.match(r"^:?-{2,}:?$", c.replace(" ", "")) for c in cells):
                            continue
                    parsed_rows.append([_clean_inline_markdown(c).replace("**", "") for c in cells])
                if len(parsed_rows) >= 2:
                    self.add_table(parsed_rows[0], parsed_rows[1:])
                    i = j
                    continue

            # Markdown 標題 (# / ## / ###)
            h_match = re.match(r"^\s*(#{1,4})\s+(.+)$", raw)
            if h_match:
                level = 2 if len(h_match.group(1)) <= 2 else 3
                self.add_heading(h_match.group(2), level=level)
                i += 1
                continue

            # Markdown 無序清單 (- / * / •)
            b_match = re.match(r"^\s*[-*•]\s+(.+)$", raw)
            if b_match:
                self.add_bullet(b_match.group(1), font_size=font_size)
                i += 1
                continue

            # Markdown 引用區塊 (> )
            q_match = re.match(r"^\s*>\s*(.*)$", raw)
            if q_match:
                q_body = q_match.group(1).strip()
                q_body = re.sub(r"^\[!WARNING\]\s*", "[警示] ", q_body, flags=re.IGNORECASE)
                q_body = re.sub(r"^\[!IMPORTANT\]\s*", "[重要] ", q_body, flags=re.IGNORECASE)
                q_body = re.sub(r"^\[!(?:NOTE|TIP)\]\s*", "[說明] ", q_body, flags=re.IGNORECASE)
                if q_body:
                    self._render_styled_text_block(
                        q_body,
                        self.margin + indent + 12,
                        max(40.0, max_w - 12),
                        max(8.5, font_size - 0.5),
                        (0.24, 0.30, 0.40),
                        line_spacing,
                        left_bar_x=self.margin + indent + 4,
                    )
                else:
                    self.cur_y += font_size * 0.35
                i += 1
                continue

            # 一般段落文字 (支援行內 **粗體**)
            self._render_styled_text_block(
                raw,
                self.margin + indent,
                max_w,
                font_size,
                color,
                line_spacing,
            )
            i += 1

        self.cur_y += 4

    def add_bullet(self, text, font_size=10, bullet_char="•"):
        clean_bullet = _sanitize_pdf_text(bullet_char).strip() or "•"
        bullet_w = self.font.text_length(clean_bullet + " ", font_size)
        text_indent = max(16.0, 4.0 + bullet_w + 2.0)
        max_w = max(40.0, self.max_width - text_indent)

        cleaned_body = _clean_inline_markdown(text)
        spans = _split_bold_spans(cleaned_body)
        wrapped_lines = self._wrap_styled_spans(spans, max_w, font_size)
        line_height = font_size * 1.35

        for idx, w_line in enumerate(wrapped_lines):
            self.ensure_space(line_height)
            if idx == 0:
                self.cur_page.insert_text(
                    (self.margin + 4, self.cur_y + font_size),
                    clean_bullet,
                    fontname=self.font_name,
                    fontsize=font_size,
                    color=(0.25, 0.45, 0.75)
                )
            self._draw_styled_line(w_line, self.margin + text_indent, self.cur_y + font_size, font_size, (0.15, 0.2, 0.25))
            self.cur_y += line_height
        self.cur_y += 2

    def add_callout(self, text, title="", bg_color=(0.95, 0.97, 1.0), border_color=(0.25, 0.45, 0.75)):
        pad = 8
        content_w = self.max_width - (2 * pad) - 6
        clean_title = _clean_inline_markdown(title).replace("**", "") if title else ""
        clean_body = _clean_inline_markdown(text)
        full_text = (f"【{clean_title}】\n" if clean_title else "") + clean_body

        all_wrapped: List[List[tuple]] = []
        for raw_l in full_text.splitlines():
            if not raw_l.strip():
                all_wrapped.append([])
            else:
                all_wrapped.extend(self._wrap_styled_spans(_split_bold_spans(raw_l), content_w, 9.5))

        line_h = 13.0
        box_h = (len(all_wrapped) * line_h) + (2 * pad)
        max_page_h = self.height - (2 * self.margin) - 45

        if box_h <= max_page_h:
            self.ensure_space(box_h + 8)
            top_y = self.cur_y
            rect = pymupdf.Rect(self.margin, top_y, self.width - self.margin, top_y + box_h)
            self.cur_page.draw_rect(rect, color=None, fill=bg_color)
            self.cur_page.draw_line((self.margin, top_y), (self.margin, top_y + box_h), color=border_color, width=3.5)

            text_y = top_y + pad
            for w_line in all_wrapped:
                if w_line:
                    self._draw_styled_line(w_line, self.margin + pad + 6, text_y + 9.5, 9.5, (0.1, 0.15, 0.2))
                text_y += line_h
            self.cur_y = top_y + box_h + 8
        else:
            # 長內容自動依頁高切段繪製背景框
            idx = 0
            while idx < len(all_wrapped):
                avail_h = (self.height - self.margin - 25) - self.cur_y
                if avail_h < (2 * pad + line_h * 2):
                    self._new_page()
                    avail_h = (self.height - self.margin - 25) - self.cur_y
                fit_lines = max(1, int((avail_h - 2 * pad) // line_h))
                chunk = all_wrapped[idx: idx + fit_lines]
                chunk_h = (len(chunk) * line_h) + (2 * pad)
                top_y = self.cur_y
                rect = pymupdf.Rect(self.margin, top_y, self.width - self.margin, top_y + chunk_h)
                self.cur_page.draw_rect(rect, color=None, fill=bg_color)
                self.cur_page.draw_line((self.margin, top_y), (self.margin, top_y + chunk_h), color=border_color, width=3.5)
                text_y = top_y + pad
                for w_line in chunk:
                    if w_line:
                        self._draw_styled_line(w_line, self.margin + pad + 6, text_y + 9.5, 9.5, (0.1, 0.15, 0.2))
                    text_y += line_h
                self.cur_y = top_y + chunk_h + 6
                idx += fit_lines

    def add_table(self, headers, rows):
        if not headers:
            return
        n_cols = len(headers)
        col_w = self.max_width / n_cols
        font_size = 9.0
        line_h = 12.5
        pad_x = 5.0
        pad_y = 5.0
        cell_text_w = max(24.0, col_w - (2 * pad_x))

        clean_headers = [_clean_inline_markdown(str(h)).replace("**", "") for h in headers]
        header_wrapped = [self._wrap_lines(ch, cell_text_w, font_size) or [""] for ch in clean_headers]
        header_lines_max = max(len(lw) for lw in header_wrapped)
        header_h = max(22.0, header_lines_max * line_h + (2 * pad_y))

        def _draw_header():
            header_rect = pymupdf.Rect(self.margin, self.cur_y, self.width - self.margin, self.cur_y + header_h)
            self.cur_page.draw_rect(header_rect, color=(0.8, 0.85, 0.9), fill=(0.9, 0.93, 0.97))
            for col_idx, cell_lines in enumerate(header_wrapped):
                x0 = self.margin + (col_idx * col_w)
                if col_idx > 0:
                    self.cur_page.draw_line((x0, self.cur_y), (x0, self.cur_y + header_h), color=(0.8, 0.85, 0.9), width=0.6)
                for l_idx, h_line in enumerate(cell_lines):
                    if h_line:
                        self.cur_page.insert_text(
                            (x0 + pad_x, self.cur_y + pad_y + font_size + (l_idx * line_h)),
                            h_line,
                            fontname=self.font_name,
                            fontsize=font_size,
                            color=(0.1, 0.2, 0.35),
                        )
            self.cur_y += header_h

        self.ensure_space(header_h + 24)
        _draw_header()

        for r_idx, row in enumerate(rows):
            norm_row = list(row[:n_cols]) + [""] * max(0, n_cols - len(row))
            cell_wrapped = [
                self._wrap_lines(_clean_inline_markdown(str(val)).replace("**", ""), cell_text_w, font_size) or [""]
                for val in norm_row
            ]
            max_lines = max(len(lw) for lw in cell_wrapped)
            row_h = max(22.0, max_lines * line_h + (2 * pad_y))

            if self.cur_y + row_h > self.height - self.margin - 25:
                self._new_page()
                _draw_header()

            fill_c = (0.98, 0.99, 1.0) if r_idx % 2 == 0 else (1.0, 1.0, 1.0)
            r_rect = pymupdf.Rect(self.margin, self.cur_y, self.width - self.margin, self.cur_y + row_h)
            self.cur_page.draw_rect(r_rect, color=(0.88, 0.9, 0.93), fill=fill_c)
            for col_idx, cell_lines in enumerate(cell_wrapped):
                x0 = self.margin + (col_idx * col_w)
                if col_idx > 0:
                    self.cur_page.draw_line((x0, self.cur_y), (x0, self.cur_y + row_h), color=(0.88, 0.9, 0.93), width=0.6)
                for l_idx, c_line in enumerate(cell_lines):
                    if c_line:
                        self.cur_page.insert_text(
                            (x0 + pad_x, self.cur_y + pad_y + font_size + (l_idx * line_h)),
                            c_line,
                            fontname=self.font_name,
                            fontsize=font_size,
                            color=(0.15, 0.2, 0.25),
                        )
            self.cur_y += row_h
        self.cur_y += 8

    def get_pdf_bytes(self) -> bytes:
        total_pages = len(self.doc)
        for idx in range(total_pages):
            page = self.doc[idx]
            footer_text = f"第 {idx + 1} 頁 ／ 共 {total_pages} 頁  ｜  台灣司律法學研析系統 AI 智慧匯出"
            page.draw_line((self.margin, self.height - self.margin - 12), (self.width - self.margin, self.height - self.margin - 12), color=(0.85, 0.85, 0.85), width=0.6)
            page.insert_text(
                (self.width / 2 - 80, self.height - self.margin - 2),
                footer_text,
                fontname=self.font_name,
                fontsize=8,
                color=(0.5, 0.55, 0.6)
            )
        buf = io.BytesIO(self.doc.tobytes())
        return buf.getvalue()





# =============================================================================

# 1. 試卷評閱診斷報告 (Evaluation Report) - DOCX / PDF

# =============================================================================



def export_evaluation_docx(report_data: Dict[str, Any], question_text: str = "") -> bytes:

    """將試卷評閱診斷報告匯出為正式 Word (.docx) 文件"""

    doc = _init_legal_doc()



    # 1. 大標題

    title_p = doc.add_paragraph()

    title_run = title_p.add_run("⚖️ 司法官暨律師高等考試・手寫試卷評閱診斷報告")

    title_run.font.name = 'Microsoft JhengHei'

    title_run.font.size = Pt(18)

    title_run.font.bold = True

    title_run.font.color.rgb = RGBColor(29, 53, 87)

    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    title_p.paragraph_format.space_after = Pt(12)



    # 2. 評分總覽表格

    score = report_data.get("total_score", 0)

    grade = report_data.get("grade_level", "未定")

    issue_score = report_data.get("issue_spotting_score", 0)

    reason_score = report_data.get("legal_reasoning_score", 0)

    prec_score = report_data.get("precedent_scholarship_score", 0)

    subsume_score = report_data.get("subsumption_score", 0)



    table = doc.add_table(rows=2, cols=6)

    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    table.autofit = True



    headers = ["總得分", "等第評級", "爭點意識 (25)", "法學推論 (25)", "實務學說 (25)", "事實涵攝 (25)"]

    values = [f"{score} / 100", str(grade), f"{issue_score}", f"{reason_score}", f"{prec_score}", f"{subsume_score}"]



    for col_idx, h_text in enumerate(headers):

        cell = table.cell(0, col_idx)

        cell.text = h_text

        _set_cell_background(cell, "E2E8F0")

        _set_cell_margins(cell, 120, 120, 120, 120)

        p = cell.paragraphs[0]

        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        for r in p.runs:

            r.font.bold = True

            r.font.size = Pt(10)

            r.font.color.rgb = RGBColor(15, 23, 42)



    for col_idx, v_text in enumerate(values):

        cell = table.cell(1, col_idx)

        cell.text = v_text

        _set_cell_background(cell, "F8FAFC")

        _set_cell_margins(cell, 140, 140, 120, 120)

        p = cell.paragraphs[0]

        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        for r in p.runs:

            r.font.bold = True

            r.font.size = Pt(11)

            r.font.color.rgb = RGBColor(30, 58, 138) if col_idx < 2 else RGBColor(51, 65, 85)



    doc.add_paragraph().paragraph_format.space_after = Pt(10)



    # 3. 考試題目

    if question_text:

        h_q = doc.add_heading("一、考試題目", level=2)

        h_q.runs[0].font.color.rgb = RGBColor(30, 58, 138)

        p_q = doc.add_paragraph()

        p_q.add_run(question_text)

        p_q.paragraph_format.line_spacing = 1.2



    # 4. 考生手寫作答謄錄

    transcription = report_data.get("transcription", "")

    if transcription:

        h_t = doc.add_heading("二、考生原卷作答內容（OCR 辨識謄錄）", level=2)

        h_t.runs[0].font.color.rgb = RGBColor(30, 58, 138)

        p_t = doc.add_paragraph()

        p_t.add_run(transcription)

        p_t.paragraph_format.line_spacing = 1.2



    # 5. 爭點與評析

    h_i = doc.add_heading("三、爭點命中分析與論述診斷", level=2)

    h_i.runs[0].font.color.rgb = RGBColor(30, 58, 138)



    doc.add_paragraph().add_run("✅ 成功命中之爭點：").font.bold = True

    for item in report_data.get("identified_issues", []):

        p = doc.add_paragraph(style='List Bullet')

        p.add_run(f"命中：{item}")



    doc.add_paragraph().add_run("❌ 漏未論述之核心考點：").font.bold = True

    for item in report_data.get("missed_issues", []):

        p = doc.add_paragraph(style='List Bullet')

        r = p.add_run(f"遺漏：{item}")

        r.font.color.rgb = RGBColor(185, 28, 28)



    doc.add_paragraph().add_run("🌟 作答亮點：").font.bold = True

    for item in report_data.get("strengths", []):

        p = doc.add_paragraph(style='List Bullet')

        p.add_run(item)



    doc.add_paragraph().add_run("⚠️ 論述盲點與缺失：").font.bold = True

    for item in report_data.get("weaknesses", []):

        p = doc.add_paragraph(style='List Bullet')

        p.add_run(item)



    # 6. 閱卷委員改寫示範

    rev = report_data.get("suggested_revision_annotated") or report_data.get("suggested_revision", "")

    if rev:

        h_r = doc.add_heading("四、閱卷委員開標與涵攝改寫示範 (IRAC 架構)", level=2)

        h_r.runs[0].font.color.rgb = RGBColor(30, 58, 138)

        clean_rev = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1 (\2)', rev)

        p_r = doc.add_paragraph()

        p_r.add_run(clean_rev)

        p_r.paragraph_format.line_spacing = 1.3



    # 7. 裁判核驗清單

    audit_md = report_data.get("audit_markdown", "")

    if audit_md:

        h_a = doc.add_heading("五、裁判案號真實性查核清單 (Ground Truth Case Audit)", level=2)

        h_a.runs[0].font.color.rgb = RGBColor(30, 58, 138)

        p_a = doc.add_paragraph()

        p_a.add_run("本報告所有引用判解字號均經司法院實體裁判庫實質核驗，堅決杜絕 AI 幻覺。")

        for line in audit_md.splitlines():

            if line.startswith("|") and not line.startswith("| :"):

                cols = [c.strip() for c in line.split("|")[1:-1]]

                if cols and len(cols) >= 3:

                    p_line = doc.add_paragraph(style='List Bullet')

                    p_line.add_run(" ｜ ".join(cols))



    buffer = io.BytesIO()

    doc.save(buffer)

    buffer.seek(0)

    return buffer.getvalue()





def export_evaluation_pdf(report_data: Dict[str, Any], question_text: str = "") -> bytes:

    """將試卷評閱診斷報告匯出為正式 PDF 文件"""

    pdf = LegalPdfDocument(title="⚖️ 司法官暨律師高等考試・手寫試卷評閱診斷報告")

    pdf.add_title("⚖️ 司法官暨律師高等考試・手寫試卷評閱診斷報告")



    score = report_data.get("total_score", 0)

    grade = report_data.get("grade_level", "未定")

    issue_score = report_data.get("issue_spotting_score", 0)

    reason_score = report_data.get("legal_reasoning_score", 0)

    prec_score = report_data.get("precedent_scholarship_score", 0)

    subsume_score = report_data.get("subsumption_score", 0)



    pdf.add_table(

        ["總得分", "等第評級", "爭點意識 (25)", "法學推論 (25)", "實務學說 (25)", "事實涵攝 (25)"],

        [[f"{score} / 100", str(grade), f"{issue_score}", f"{reason_score}", f"{prec_score}", f"{subsume_score}"]]

    )



    if question_text:

        pdf.add_heading("一、考試題目", level=2)

        pdf.add_paragraph(question_text)



    transcription = report_data.get("transcription", "")

    if transcription:

        pdf.add_heading("二、考生原卷作答內容（OCR 謄錄）", level=2)

        pdf.add_paragraph(transcription)



    pdf.add_heading("三、爭點命中分析與論述診斷", level=2)

    for item in report_data.get("identified_issues", []):

        pdf.add_bullet(f"命中爭點：{item}", bullet_char="✅")

    for item in report_data.get("missed_issues", []):

        pdf.add_bullet(f"漏未論述：{item}", bullet_char="❌")

    for item in report_data.get("strengths", []):

        pdf.add_bullet(f"作答亮點：{item}", bullet_char="🌟")

    for item in report_data.get("weaknesses", []):

        pdf.add_bullet(f"盲點缺失：{item}", bullet_char="⚠️")



    rev = report_data.get("suggested_revision_annotated") or report_data.get("suggested_revision", "")
    if rev:
        pdf.add_heading("四、閱卷委員開標與涵攝改寫示範 (IRAC)", level=2)
        clean_rev = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', rev)
        pdf.add_callout(clean_rev, title="上位卷 IRAC 開標示範")

    audit_md = report_data.get("audit_markdown", "")
    if audit_md:
        pdf.add_heading("五、裁判案號真實性查核清單 (Ground Truth Case Audit)", level=2)
        audit_lines = []
        for raw_a in str(audit_md).splitlines():
            s_a = raw_a.strip()
            if s_a == "---":
                continue
            if s_a.startswith("#") and ("裁判引用真實性查核清單" in s_a or "Ground Truth Case Audit" in s_a):
                continue
            audit_lines.append(raw_a)
        cleaned_audit_md = "\n".join(audit_lines).strip()
        if cleaned_audit_md:
            pdf.add_paragraph(cleaned_audit_md)
        else:
            pdf.add_paragraph("本報告所有引用判解字號均經司法院實體裁判庫實質核驗，堅決杜絕 AI 幻覺。")

    return pdf.get_pdf_bytes()





# =============================================================================

# 2. 二試榜首示範擬答 (Model Answer) - DOCX / PDF

# =============================================================================



def export_model_answer_docx(question: str, answer_markdown: str, subject: str = "") -> bytes:

    """將二試榜首示範擬答匯出為正式 Word (.docx) 文件"""

    doc = _init_legal_doc()



    title_p = doc.add_paragraph()

    sub_title = f"【{subject}】" if subject else ""

    title_run = title_p.add_run(f"🏆 司法官暨律師高等考試二試・高分示範擬答 {sub_title}")

    title_run.font.name = 'Microsoft JhengHei'

    title_run.font.size = Pt(17)

    title_run.font.bold = True

    title_run.font.color.rgb = RGBColor(29, 53, 87)

    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    title_p.paragraph_format.space_after = Pt(14)



    h_q = doc.add_heading("【國家考試題目】：", level=2)

    h_q.runs[0].font.color.rgb = RGBColor(30, 58, 138)

    p_q = doc.add_paragraph()

    p_q.add_run(question)

    p_q.paragraph_format.line_spacing = 1.2

    p_q.paragraph_format.space_after = Pt(12)



    h_a = doc.add_heading("【示範擬答全文 (IRAC 標準法學架構)】：", level=2)

    h_a.runs[0].font.color.rgb = RGBColor(30, 58, 138)



    clean_ans = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', answer_markdown)

    for block in clean_ans.split("\n\n"):

        b_clean = block.strip()

        if not b_clean:

            continue

        p = doc.add_paragraph()

        if b_clean.startswith("### ") or b_clean.startswith("## "):

            p.add_run(b_clean.replace("#", "").strip()).font.bold = True

            p.paragraph_format.space_before = Pt(8)

            p.paragraph_format.space_after = Pt(4)

        elif b_clean.startswith("一、") or b_clean.startswith("二、") or b_clean.startswith("三、") or b_clean.startswith("四、"):

            r = p.add_run(b_clean)

            r.font.bold = True

            p.paragraph_format.space_before = Pt(6)

        else:

            p.add_run(b_clean)

            p.paragraph_format.line_spacing = 1.3



    buffer = io.BytesIO()

    doc.save(buffer)

    buffer.seek(0)

    return buffer.getvalue()





def export_model_answer_pdf(question: str, answer_markdown: str, subject: str = "") -> bytes:

    """將二試榜首示範擬答匯出為正式 PDF 文件"""

    sub_title = f"【{subject}】" if subject else ""

    pdf = LegalPdfDocument(title=f"🏆 司法官律師二試・高分示範擬答 {sub_title}")

    pdf.add_title(f"🏆 司法官暨律師考試二試・高分示範擬答 {sub_title}")



    pdf.add_heading("【國家考試題目】：", level=2)

    pdf.add_paragraph(question)



    pdf.add_heading("【示範擬答全文 (IRAC 標準法學架構)】：", level=2)

    clean_ans = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', answer_markdown)

    for block in clean_ans.split("\n\n"):

        b_clean = block.strip()

        if not b_clean:

            continue

        if b_clean.startswith("#"):

            pdf.add_heading(b_clean.replace("#", "").strip(), level=3)

        else:

            pdf.add_paragraph(b_clean)



    return pdf.get_pdf_bytes()





# =============================================================================

# 3. 郵局存證信函與調解聲請要旨 (Legal Notice & Mediation) - DOCX / PDF

# =============================================================================



def export_legal_notice_docx(

    notice_text: str,

    sender_name: str = "【寄件人姓名】",

    receiver_name: str = "【相對人姓名】",

    subject: str = "郵局存證信函"

) -> bytes:

    """將存證信函或調解聲請書草稿匯出為標準 A4 格式 Word 文件"""

    doc = _init_legal_doc()



    doc_subject = (subject or "").strip() or "郵局存證信函"

    title_p = doc.add_paragraph()
    title_run = title_p.add_run(doc_subject)
    title_run.font.name = 'Microsoft JhengHei'
    title_run.font.size = Pt(18)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(15, 23, 42)
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_p.paragraph_format.space_after = Pt(14)

    table = doc.add_table(rows=4, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    is_mediation = "調解" in doc_subject
    info_data = [
        ("主　旨：", doc_subject),
        ("聲請人：" if is_mediation else "寄件人：", sender_name),
        ("對造人：" if is_mediation else "收件人（相對人）：", receiver_name),
        ("副　本：", "無（或載明：所在地鄉鎮市區調解委員會）")
    ]
    for row_idx, (k, v) in enumerate(info_data):
        c0 = table.cell(row_idx, 0)
        c0.text = k
        _set_cell_background(c0, "F1F5F9")
        c0.paragraphs[0].runs[0].font.bold = True
        c1 = table.cell(row_idx, 1)
        c1.text = v

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    h_c = doc.add_heading(f"【{doc_subject} — 主旨與內文】：", level=2)
    h_c.runs[0].font.color.rgb = RGBColor(15, 23, 42)



    clean_notice = re.sub(r'#+\s*', '', notice_text)

    for line in clean_notice.splitlines():

        l_str = line.strip()

        if l_str:

            p = doc.add_paragraph()

            p.add_run(l_str)

            p.paragraph_format.line_spacing = 1.3

            p.paragraph_format.space_after = Pt(4)



    buffer = io.BytesIO()

    doc.save(buffer)

    buffer.seek(0)

    return buffer.getvalue()





def export_legal_notice_pdf(

    notice_text: str,

    sender_name: str = "【寄件人姓名】",

    receiver_name: str = "【相對人姓名】",

    subject: str = "郵局存證信函"

) -> bytes:

    """將存證信函草稿匯出為標準 PDF 文件"""
    doc_subject = (subject or "").strip() or "郵局存證信函"
    pdf = LegalPdfDocument(title=doc_subject)
    pdf.add_title(doc_subject)

    is_mediation = "調解" in doc_subject
    pdf.add_table(
        ["欄位項目", "登記內容"],
        [
            ["主　旨：", doc_subject],
            ["聲請人：" if is_mediation else "寄件人：", sender_name],
            ["對造人：" if is_mediation else "收件人（相對人）：", receiver_name],
            ["副　本：", "無（或載明：所在地調解委員會）"]
        ]
    )

    pdf.add_heading(f"【{doc_subject} — 通知內文】：", level=2)
    pdf.add_paragraph(notice_text)

    return pdf.get_pdf_bytes()


def export_mediation_pdf(
    med_text: str,
    sender_name: str = "聲請人",
    receiver_name: str = "對造人",
    subject: str = "鄉鎮市區調解委員會聲請要旨",
    applicant: Optional[str] = None,
    respondent: Optional[str] = None,
) -> bytes:
    """將調解聲請要旨匯出為標準 PDF 文件（相容 sender_name/receiver_name 與 applicant/respondent 參數）"""
    actual_sender = applicant if applicant is not None else sender_name
    actual_receiver = respondent if respondent is not None else receiver_name
    doc_subject = (subject or "").strip() or "鄉鎮市區調解委員會聲請要旨"

    pdf = LegalPdfDocument(title=doc_subject)
    pdf.add_title(doc_subject)

    pdf.add_table(
        ["調解關係人／事項", "姓名／內容"],
        [
            ["調解主旨：", doc_subject],
            ["聲請人：", actual_sender],
            ["對造人：", actual_receiver],
        ]
    )

    pdf.add_heading("【調解聲請理由與和解方案建議】：", level=2)
    pdf.add_paragraph(med_text)

    return pdf.get_pdf_bytes()





# =============================================================================

# 4. 體系法學教科書專題 (Textbook Topic) - DOCX / PDF

# =============================================================================



def export_textbook_docx(

    subject: str,

    chapter: str,

    topic_title: str,

    markdown_content: str

) -> bytes:

    """將體系教科書專題章節匯出為研討質感之 Word 文件"""

    doc = _init_legal_doc()



    title_p = doc.add_paragraph()

    title_run = title_p.add_run(f"📖 體系導引式法學教科書・{subject}")

    title_run.font.name = 'Microsoft JhengHei'

    title_run.font.size = Pt(18)

    title_run.font.bold = True

    title_run.font.color.rgb = RGBColor(29, 53, 87)

    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER



    sub_p = doc.add_paragraph()

    sub_run = sub_p.add_run(f"單元：{chapter} ｜ 專題：{topic_title}")

    sub_run.font.size = Pt(12)

    sub_run.font.bold = True

    sub_run.font.color.rgb = RGBColor(71, 85, 105)

    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    sub_p.paragraph_format.space_after = Pt(14)



    clean_content = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', markdown_content)

    for block in clean_content.split("\n\n"):

        b_clean = block.strip()

        if not b_clean:

            continue

        p = doc.add_paragraph()

        if b_clean.startswith("# ") or b_clean.startswith("## "):

            r = p.add_run(b_clean.replace("#", "").strip())

            r.font.bold = True

            r.font.size = Pt(14)

            r.font.color.rgb = RGBColor(30, 58, 138)

            p.paragraph_format.space_before = Pt(10)

            p.paragraph_format.space_after = Pt(4)

        elif b_clean.startswith("### "):

            r = p.add_run(b_clean.replace("#", "").strip())

            r.font.bold = True

            r.font.size = Pt(12)

            r.font.color.rgb = RGBColor(51, 65, 85)

            p.paragraph_format.space_before = Pt(6)

            p.paragraph_format.space_after = Pt(2)

        else:

            p.add_run(b_clean)

            p.paragraph_format.line_spacing = 1.3



    buffer = io.BytesIO()

    doc.save(buffer)

    buffer.seek(0)

    return buffer.getvalue()





def export_textbook_pdf(

    subject: str,

    chapter: str,

    topic_title: str,

    markdown_content: str

) -> bytes:

    """將體系教科書專題章節匯出為研讀版 PDF 文件"""

    pdf = LegalPdfDocument(title=f"📖 體系導引式法學教科書・{subject}")

    pdf.add_title(f"📖 體系導引式法學教科書・{subject}")

    pdf.add_paragraph(f"單元：{chapter} ｜ 專題：{topic_title}", font_size=11, color=(0.28, 0.33, 0.41))



    clean_content = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', markdown_content)

    for block in clean_content.split("\n\n"):

        b_clean = block.strip()

        if not b_clean:

            continue

        if b_clean.startswith("#"):

            pdf.add_heading(b_clean.replace("#", "").strip(), level=2 if b_clean.startswith("## ") else 3)

        else:

            pdf.add_paragraph(b_clean)



    return pdf.get_pdf_bytes()





# =============================================================================

# 5. 司律一試選擇題模擬試卷 (MCQ Exam) - DOCX / PDF

# =============================================================================



def export_mcq_exam_docx(

    exam_data: Dict[str, Any],

    user_answers: Optional[Dict[str, str]] = None

) -> bytes:

    """將司律一試選擇題試卷、考生作答與詳解報告匯出為正式 Word (.docx) 考卷"""

    doc = _init_legal_doc()



    subject = exam_data.get("subject", "法學綜合")

    topic = exam_data.get("topic", "司律一試全真模擬試卷")

    questions = exam_data.get("questions", [])

    answer_key = exam_data.get("answer_key", {})



    title_p = doc.add_paragraph()

    title_run = title_p.add_run(f"📋 司法官暨律師高等考試一試・全真模擬試卷【{subject}】")

    title_run.font.name = 'Microsoft JhengHei'

    title_run.font.size = Pt(17)

    title_run.font.bold = True

    title_run.font.color.rgb = RGBColor(29, 53, 87)

    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER



    sub_p = doc.add_paragraph()

    sub_run = sub_p.add_run(f"測驗主題：{topic} ｜ 總題數：{len(questions)} 題 ｜ 每題 2 分")

    sub_run.font.size = Pt(11)

    sub_run.font.bold = True

    sub_run.font.color.rgb = RGBColor(71, 85, 105)

    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    sub_p.paragraph_format.space_after = Pt(12)



    if user_answers:

        score = 0

        for q_num_str, c_ans in answer_key.items():

            if user_answers.get(q_num_str) == c_ans:

                score += 1

        pct = int(score / len(questions) * 100) if questions else 0



        score_p = doc.add_paragraph()

        r_sc = score_p.add_run(f"★ 測驗成績：{score} / {len(questions)} 題（得分率：{pct}%，測驗總分：{score * 2} 分）")

        r_sc.font.bold = True

        r_sc.font.size = Pt(13)

        r_sc.font.color.rgb = RGBColor(22, 101, 52) if pct >= 60 else RGBColor(185, 28, 28)

        score_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        score_p.paragraph_format.space_after = Pt(14)



    h_sec1 = doc.add_heading("壹、全真試題測驗區", level=2)

    h_sec1.runs[0].font.color.rgb = RGBColor(30, 58, 138)



    for q in questions:

        q_no = q.get("question_no")

        cat = q.get("category", "")

        cat_str = f" [{cat}]" if cat else ""



        p_q = doc.add_paragraph()

        r_no = p_q.add_run(f"第 {q_no} 題{cat_str}：")

        r_no.font.bold = True

        p_q.add_run(q.get("question", ""))

        p_q.paragraph_format.space_before = Pt(8)

        p_q.paragraph_format.space_after = Pt(3)



        if q.get("case_facts"):

            p_cf = doc.add_paragraph()

            p_cf.add_run(f"【共通案例事實】：{q.get('case_facts')}")

            p_cf.paragraph_format.line_spacing = 1.15



        opts = q.get("options", {})

        for opt_key in ["A", "B", "C", "D"]:

            if opt_key in opts:

                p_opt = doc.add_paragraph()

                p_opt.paragraph_format.left_indent = Inches(0.25)

                p_opt.paragraph_format.space_after = Pt(2)

                p_opt.add_run(f"({opt_key}) {opts[opt_key]}")



        if user_answers:

            u_ans = user_answers.get(str(q_no))

            c_ans = answer_key.get(str(q_no), "")

            p_res = doc.add_paragraph()

            p_res.paragraph_format.left_indent = Inches(0.25)

            p_res.paragraph_format.space_after = Pt(6)

            if u_ans == c_ans:

                r_ans = p_res.add_run(f"✅ 考生作答：({u_ans}) ➔ 正確！")

                r_ans.font.bold = True

                r_ans.font.color.rgb = RGBColor(22, 101, 52)

            elif u_ans:

                r_ans = p_res.add_run(f"❌ 考生作答：({u_ans}) ➔ 錯誤（標準答案：({c_ans})）")

                r_ans.font.bold = True

                r_ans.font.color.rgb = RGBColor(185, 28, 28)

            else:

                r_ans = p_res.add_run(f"⚪ 未作答（標準答案：({c_ans})）")

                r_ans.font.color.rgb = RGBColor(100, 116, 139)



    doc.add_page_break()

    h_sec2 = doc.add_heading("貳、逐題法理詳細解析與實務出處", level=2)

    h_sec2.runs[0].font.color.rgb = RGBColor(30, 58, 138)



    for q in questions:

        q_no = q.get("question_no")

        c_ans = q.get("answer") or answer_key.get(str(q_no), "")

        core_issue = q.get("core_issue", "")

        legal_refs = q.get("legal_references", "")

        explanation = q.get("explanation", "")



        p_h = doc.add_paragraph()

        r_ph = p_h.add_run(f"第 {q_no} 題 【正確答案：({c_ans})】")

        r_ph.font.bold = True

        r_ph.font.size = Pt(12)

        r_ph.font.color.rgb = RGBColor(30, 58, 138)

        p_h.paragraph_format.space_before = Pt(10)

        p_h.paragraph_format.space_after = Pt(2)



        if core_issue:

            p_ci = doc.add_paragraph()

            p_ci.add_run(f"【核心法學考點】：{core_issue}").font.bold = True

            p_ci.paragraph_format.space_after = Pt(2)



        if legal_refs:

            p_lr = doc.add_paragraph()

            p_lr.add_run(f"【依據法條與裁判字號】：{legal_refs}")

            p_lr.paragraph_format.space_after = Pt(2)



        if explanation:

            p_exp = doc.add_paragraph()

            p_exp.add_run(explanation)

            p_exp.paragraph_format.line_spacing = 1.25

            p_exp.paragraph_format.space_after = Pt(8)



    buffer = io.BytesIO()

    doc.save(buffer)

    buffer.seek(0)

    return buffer.getvalue()





def export_mcq_exam_pdf(
    exam_data: Dict[str, Any],
    user_answers: Optional[Dict[str, str]] = None,
    blank_practice: bool = False
) -> bytes:
    """將司律一試選擇題試卷與詳解匯出為正式 PDF 考卷（支援 blank_practice 純白卷練習模式）"""
    subject = exam_data.get("subject", "法學綜合")
    topic = exam_data.get("topic", "司律一試全真模擬試卷")
    questions = exam_data.get("questions", [])
    answer_key = exam_data.get("answer_key", {})

    pdf = LegalPdfDocument(title=f"📋 司法官律師一試・全真模擬試卷【{subject}】")
    pdf.add_title(f"📋 司法官暨律師考試一試・全真模擬試卷【{subject}】")
    pdf.add_paragraph(f"測驗主題：{topic} ｜ 總題數：{len(questions)} 題", font_size=10, color=(0.4, 0.45, 0.5))

    resolved_answers: Dict[str, str] = {}
    for idx, q in enumerate(questions, 1):
        q_no = q.get("question_no", idx)
        resolved_answers[str(q_no)] = str(q.get("answer") or answer_key.get(str(q_no), "")).strip()

    if not blank_practice and user_answers:
        score = 0
        for q_num_str, c_ans in resolved_answers.items():
            if c_ans and user_answers.get(q_num_str) == c_ans:
                score += 1
        pct = int(score / len(questions) * 100) if questions else 0
        is_pass = pct >= 60
        score_color = (0.09, 0.40, 0.20) if is_pass else (0.73, 0.11, 0.11)
        pdf.add_callout(
            f"★ 測驗成績：{score} / {len(questions)} 題（得分率：{pct}%，測驗總分：{score * 2} 分）",
            title="一試模擬測驗成績統計",
            bg_color=(0.94, 0.99, 0.95) if is_pass else (0.99, 0.95, 0.95),
            border_color=score_color,
        )

    pdf.add_heading("壹、全真試題測驗區", level=2)
    for idx, q in enumerate(questions, 1):
        q_no = q.get("question_no", idx)
        cat = q.get("category", "")
        cat_str = f" [{cat}]" if cat else ""
        pdf.add_paragraph(f"**第 {q_no} 題{cat_str}**：{q.get('question', '')}", font_size=10)

        if q.get("case_facts"):
            pdf.add_paragraph(
                f"【共通案例事實】：{q.get('case_facts')}",
                font_size=9.5,
                indent=8,
                color=(0.25, 0.30, 0.38),
            )

        opts = q.get("options", {})
        if isinstance(opts, dict):
            for opt_key in ["A", "B", "C", "D"]:
                if opt_key in opts:
                    pdf.add_paragraph(f"({opt_key}) {opts[opt_key]}", font_size=9.5, indent=14)
        elif isinstance(opts, list):
            for o_idx, opt_val in enumerate(opts):
                opt_key = chr(ord("A") + o_idx)
                pdf.add_paragraph(f"({opt_key}) {opt_val}", font_size=9.5, indent=14)

        if not blank_practice and user_answers:
            u_ans = user_answers.get(str(q_no))
            c_ans = resolved_answers.get(str(q_no), "")
            if u_ans and u_ans == c_ans:
                pdf.add_paragraph(
                    f"✅ 考生作答：({u_ans}) ➔ 正確！",
                    font_size=9.5,
                    indent=14,
                    color=(0.09, 0.40, 0.20),
                )
            elif u_ans:
                pdf.add_paragraph(
                    f"❌ 考生作答：({u_ans}) ➔ 錯誤（標準答案：({c_ans})）",
                    font_size=9.5,
                    indent=14,
                    color=(0.73, 0.11, 0.11),
                )
            else:
                pdf.add_paragraph(
                    f"⚪ 未作答（標準答案：({c_ans})）",
                    font_size=9.5,
                    indent=14,
                    color=(0.39, 0.45, 0.55),
                )

    if questions:
        pdf._new_page()

    pdf.add_heading("貳、標準答案與逐題法理詳細解析與實務出處", level=2)

    if blank_practice and questions:
        ans_rows = []
        for idx, q in enumerate(questions, 1):
            q_no = q.get("question_no", idx)
            c_ans = resolved_answers.get(str(q_no), "")
            ans_rows.append([f"第 {q_no} 題", f"({c_ans})", q.get("core_issue", "") or "-"])
        pdf.add_table(["題號", "標準答案", "核心法學考點"], ans_rows)

    for idx, q in enumerate(questions, 1):
        q_no = q.get("question_no", idx)
        c_ans = resolved_answers.get(str(q_no), "")
        core_issue = q.get("core_issue", "")
        legal_refs = q.get("legal_references", "")
        exp = q.get("explanation", "")

        pdf.add_paragraph(f"**第 {q_no} 題 【正確答案：({c_ans})】**", font_size=10.5, color=(0.12, 0.23, 0.54))
        if core_issue:
            pdf.add_paragraph(f"**【核心法學考點】**：{core_issue}", font_size=9.5, indent=10, color=(0.15, 0.22, 0.32))
        if legal_refs:
            pdf.add_paragraph(f"【依據法條與裁判字號】：{legal_refs}", font_size=9.5, indent=10, color=(0.25, 0.30, 0.38))
        if exp:
            pdf.add_paragraph(f"解析：{exp}", font_size=9.5, indent=10)

    return pdf.get_pdf_bytes()





# =============================================================================

# 6. 訴訟程序策略與實務評估建議書 (Litigation Strategy & Advice) - DOCX / PDF

# =============================================================================



def export_litigation_advice_docx(

    advice_text: str,

    question_text: str = "",

    title: str = "訴訟程序策略與實務評估建議書",

    party_role: str = "",

    stage: str = "",

    case_subject: str = "",

    **kwargs

) -> bytes:

    """

    將訴訟策略與實務指引匯出為正式 Word (.docx) 文件。

    注意：本文件僅提供法律程序與策略評估學術參考，絕非正式法院訴狀。

    """

    doc = _init_legal_doc()



    title_p = doc.add_paragraph()

    title_run = title_p.add_run(f"⚖️ {title}")

    title_run.font.name = 'Microsoft JhengHei'

    title_run.font.size = Pt(18)

    title_run.font.bold = True

    title_run.font.color.rgb = RGBColor(29, 53, 87)

    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    title_p.paragraph_format.space_after = Pt(12)



    warn_p = doc.add_paragraph()

    w_run = warn_p.add_run("⚠️【免責與委任聲明】：本建議書係依當事人提供事實與法學法理之客觀研析，僅供評估救濟途徑、舉證責任與訴訟風險之學術參考，絕非正式訴訟書狀。具體訴訟進行請依法委請中華民國合格執業律師辦理。")

    w_run.font.size = Pt(9.5)

    w_run.font.color.rgb = RGBColor(185, 28, 28)

    warn_p.paragraph_format.space_after = Pt(12)



    meta_items = []

    if party_role:

        meta_items.append(("當事人訴訟地位：", party_role))

    if stage:

        meta_items.append(("目前救濟階段：", stage))

    if case_subject:

        meta_items.append(("諮詢案由：", case_subject))



    if meta_items:

        t = doc.add_table(rows=len(meta_items), cols=2)

        t.alignment = WD_TABLE_ALIGNMENT.CENTER

        for r_idx, (k, v) in enumerate(meta_items):

            c0 = t.cell(r_idx, 0)

            c0.text = k

            _set_cell_background(c0, "F1F5F9")

            c0.paragraphs[0].runs[0].font.bold = True

            c1 = t.cell(r_idx, 1)

            c1.text = v

        doc.add_paragraph().paragraph_format.space_after = Pt(8)



    if question_text:

        h_q = doc.add_heading("一、爭端事實與諮詢核心問題：", level=2)

        h_q.runs[0].font.color.rgb = RGBColor(30, 58, 138)

        p_q = doc.add_paragraph()

        p_q.add_run(question_text)

        p_q.paragraph_format.line_spacing = 1.2

        p_q.paragraph_format.space_after = Pt(10)



    h_a = doc.add_heading("二、訴訟策略、管轄判定與攻防指引：", level=2)

    h_a.runs[0].font.color.rgb = RGBColor(30, 58, 138)



    clean_advice = re.sub(r'#+\s*', '', advice_text)

    for line in clean_advice.splitlines():

        l_str = line.strip()

        if l_str:

            p = doc.add_paragraph()

            p.add_run(l_str)

            p.paragraph_format.line_spacing = 1.3

            p.paragraph_format.space_after = Pt(4)



    buffer = io.BytesIO()

    doc.save(buffer)

    buffer.seek(0)

    return buffer.getvalue()





def export_litigation_advice_pdf(

    advice_text: str,

    question_text: str = "",

    title: str = "訴訟程序策略與實務評估建議書",

    party_role: str = "",

    stage: str = "",

    case_subject: str = "",

    **kwargs

) -> bytes:

    """將訴訟策略與實務指引匯出為正式 PDF 文件"""

    pdf = LegalPdfDocument(title=f"⚖️ {title}")

    pdf.add_title(f"⚖️ {title}")



    pdf.add_callout(

        "本建議書係依當事人提供事實與法理判解之客觀研析，僅供評估救濟途徑、舉證責任與訴訟風險之學術參考，絕非正式訴訟書狀。具體訴訟進行請依法委任執業律師辦理。",

        title="重要法律聲明"

    )



    meta_rows = []

    if party_role:

        meta_rows.append(["當事人訴訟地位", party_role])

    if stage:

        meta_rows.append(["目前救濟階段", stage])

    if case_subject:

        meta_rows.append(["諮詢案由", case_subject])



    if meta_rows:

        pdf.add_table(["評估項目", "當事人情況"], meta_rows)



    if question_text:

        pdf.add_heading("一、爭端事實經過：", level=2)

        pdf.add_paragraph(question_text)



    pdf.add_heading("二、訴訟策略與實務評估分析：", level=2)

    clean_advice = re.sub(r'#+\s*', '', advice_text)

    for line in clean_advice.splitlines():

        if line.strip():

            pdf.add_paragraph(line.strip())



    return pdf.get_pdf_bytes()





def export_litigation_pleading_docx(pleading_data: Any, **kwargs) -> bytes:

    """安全防護重定向：依系統安全防護準則，不提供法院訴訟書狀，全面重定向至標準【訴訟策略與爭點分析建議書】Word 文件"""

    if isinstance(pleading_data, dict):

        body = pleading_data.get("body_text", "")

        title = pleading_data.get("title", "法律諮詢與訴訟策略建議書")

        q_text = f"管轄法院評估：{pleading_data.get('court', '')} ｜ 案號：{pleading_data.get('case_no', '')} ｜ 當事人：{pleading_data.get('plaintiff', '')} 與 {pleading_data.get('defendant', '')}"

        return export_litigation_advice_docx(body, question_text=q_text, title=title)

    return export_litigation_advice_docx(str(pleading_data), **kwargs)
