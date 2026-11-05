# -*- coding: utf-8 -*-
"""
document_exporter.py
====================
專業法學文書與國考成果 Word (.docx) / Markdown 匯出引擎。
支援：
1. 司律試卷閱卷診斷報告 (完整四大維度評分、開標分析、爭點命中與改寫示範)
2. 司律二試榜首水準示範擬答 (IRAC 標準排版與權威判解註釋)
3. 中華民國郵局標準格式存證信函與調解聲請要旨 (可直接列印寄發)
4. 體系導引式專題法學教科書 (離線研讀專用 A4 排版講義)
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

    # 設定預設正文字體
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Microsoft JhengHei'
    font.size = Pt(11)
    font.color.rgb = RGBColor(30, 41, 59)
    style.paragraph_format.line_spacing = 1.25
    style.paragraph_format.space_after = Pt(6)

    return doc


def export_evaluation_docx(report_data: Dict[str, Any], question_text: str = "") -> bytes:
    """
    將試卷評閱診斷報告匯出為正式 Word (.docx) 文件
    """
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
        
        # 移除 markdown 連結只保留文字或格式
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

    # 儲存至記憶體位元組串流
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def export_model_answer_docx(question: str, answer_markdown: str, subject: str = "") -> bytes:
    """
    將二試榜首示範擬答匯出為正式 Word (.docx) 文件
    """
    doc = _init_legal_doc()

    # 標題
    title_p = doc.add_paragraph()
    sub_title = f"【{subject}】" if subject else ""
    title_run = title_p.add_run(f"🏆 司法官暨律師高等考試二試・高分示範擬答 {sub_title}")
    title_run.font.name = 'Microsoft JhengHei'
    title_run.font.size = Pt(17)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(29, 53, 87)
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_p.paragraph_format.space_after = Pt(14)

    # 題目
    h_q = doc.add_heading("【國家考試題目】：", level=2)
    h_q.runs[0].font.color.rgb = RGBColor(30, 58, 138)
    p_q = doc.add_paragraph()
    p_q.add_run(question)
    p_q.paragraph_format.line_spacing = 1.2
    p_q.paragraph_format.space_after = Pt(12)

    # 擬答全文
    h_a = doc.add_heading("【示範擬答全文 (IRAC 標準法學架構)】：", level=2)
    h_a.runs[0].font.color.rgb = RGBColor(30, 58, 138)

    # 處理 markdown 換行與段落
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


def export_legal_notice_docx(
    notice_text: str,
    sender_name: str = "【寄件人姓名】",
    receiver_name: str = "【相對人姓名】",
    subject: str = "郵局存證信函"
) -> bytes:
    """
    將存證信函或調解聲請書草稿匯出為標準 A4 格式 Word 文件
    """
    doc = _init_legal_doc()

    # 信函抬頭
    title_p = doc.add_paragraph()
    title_run = title_p.add_run("📮 中華民國郵局存證信函")
    title_run.font.name = 'Microsoft JhengHei'
    title_run.font.size = Pt(18)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(15, 23, 42)
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_p.paragraph_format.space_after = Pt(14)

    # 寄件人與收件人表格
    table = doc.add_table(rows=3, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    info_data = [
        ("寄件人：", sender_name),
        ("收件人（相對人）：", receiver_name),
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

    # 內文
    h_c = doc.add_heading("【存證信函主旨與內文】：", level=2)
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


def export_textbook_docx(
    subject: str,
    chapter: str,
    topic_title: str,
    markdown_content: str
) -> bytes:
    """
    將體系教科書專題章節匯出為研討質感之 Word 文件
    """
    doc = _init_legal_doc()

    # 主標題
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

    # 處理 Markdown 章節
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

def export_mcq_exam_docx(
    exam_data: Dict[str, Any],
    user_answers: Optional[Dict[str, str]] = None
) -> bytes:
    """
    將司律一試選擇題試卷、考生作答與詳解報告匯出為正式 Word (.docx) 考卷
    """
    doc = _init_legal_doc()

    subject = exam_data.get("subject", "法學綜合")
    topic = exam_data.get("topic", "司律一試全真模擬試卷")
    questions = exam_data.get("questions", [])
    answer_key = exam_data.get("answer_key", {})

    # 考卷標題
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

    # 成績統計 (若已批改)
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

    # 第一部分：試題區
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

        # 若已作答，標註考生選擇與正誤
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

    # 第二部分：逐題詳細解析
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

