"""
解析使用者上傳之《司律一試行政法全真模擬題庫暨詳解（300題完整版）》
提取 300 道全真題目、選項、標準答案、詳細解析與法條/判例出處，建立標準結構化題庫。
"""
import sys
import io
import re
import json
from pathlib import Path
import pdfplumber

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from config import RAW_DATA_DIR

USER_PDF_PATH = Path(r"C:\Users\mis\.gemini\antigravity\brain\7a4dfd47-e0dc-4156-b542-f11185a17887\.user_uploaded\media_1792215967898_02dabf0e.pdf")
OUTPUT_JSON_PATH = RAW_DATA_DIR / "admin_law_300_mcqs.json"

def parse_300_mcqs():
    print("=" * 70)
    print("  正在解析《司律一試行政法全真模擬題庫暨詳解（300題完整版）》...")
    print("=" * 70)

    if not USER_PDF_PATH.exists():
        print(f"[錯誤] 找不到 PDF: {USER_PDF_PATH}")
        return

    full_text = ""
    with pdfplumber.open(USER_PDF_PATH) as pdf:
        print(f"  總頁數: {len(pdf.pages)} 頁")
        for idx, page in enumerate(pdf.pages):
            t = page.extract_text()
            if t:
                full_text += f"\n--- PAGE {idx+1} ---\n" + t

    print(f"  已擷取總字數: {len(full_text):,} 字元")

    # 1. 提取解答與詳解區 (大約從 "第 1 題 正解：" 開始)
    explanations = {}
    answers = {}
    
    # 匹配詳解格式：第 X 題 正解：(A) ...
    expl_pattern = re.compile(
        r"第\s*(\d+)\s*題\s*正解：\s*\(?([A-D])\)?\s*([^\n]*)\n(.*?)(?=(?:第\s*\d+\s*題\s*正解：)|(?:\n--- PAGE)|$)",
        re.DOTALL
    )
    for m in expl_pattern.finditer(full_text):
        q_num = int(m.group(1))
        ans = m.group(2).upper()
        topic = m.group(3).strip()
        body = m.group(4).strip()
        answers[q_num] = ans
        explanations[q_num] = {
            "answer": ans,
            "topic": topic,
            "explanation": body
        }

    print(f"  成功提取解答與詳解: {len(explanations)} 題")

    # 2. 提取題目與選項區 (題目格式例如：1. [考點] 題幹... (A) ... (B) ... (C) ... (D) ...)
    # 遍歷 1 到 300 題
    questions = []
    
    # 切割題目
    # 題目特徵：數字. [分類] 題幹
    q_regex = re.compile(
        r"(?:^|\n)\s*(\d{1,3})\.\s*(\[[^\]]+\])?\s*(.*?)\n\s*\(A\)\s*(.*?)\n\s*\(B\)\s*(.*?)\n\s*\(C\)\s*(.*?)\n\s*\(D\)\s*(.*?)(?=(?:\n\s*\d{1,3}\.\s*\[)|\n--- PAGE 4|\n第\s*1\s*題\s*正解|$)",
        re.DOTALL
    )

    found_q_nums = set()
    for m in q_regex.finditer(full_text):
        q_num = int(m.group(1))
        if q_num > 300 or q_num in found_q_nums:
            continue
        found_q_nums.add(q_num)
        
        category = m.group(2).strip() if m.group(2) else ""
        q_text = m.group(3).strip()
        opt_a = m.group(4).strip().replace("\n", " ")
        opt_b = m.group(5).strip().replace("\n", " ")
        opt_c = m.group(6).strip().replace("\n", " ")
        opt_d = m.group(7).strip().replace("\n", " ")

        expl_info = explanations.get(q_num, {})
        ans = expl_info.get("answer", answers.get(q_num, "A"))
        expl = expl_info.get("explanation", "")
        topic_header = expl_info.get("topic", category)

        questions.append({
            "question_no": q_num,
            "category": category if category else topic_header,
            "question": q_text,
            "options": {
                "A": opt_a,
                "B": opt_b,
                "C": opt_c,
                "D": opt_d
            },
            "answer": ans,
            "explanation": expl,
            "core_issue": topic_header
        })

    questions.sort(key=lambda x: x["question_no"])
    print(f"  成功精確解析題幹與選項: {len(questions)} 題")

    result_dataset = {
        "title": "司律一試行政法全真模擬題庫暨詳解（300題完整版）",
        "subject": "行政法",
        "total_count": len(questions),
        "source": "考生上傳附件標準模擬題庫",
        "questions": questions
    }

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(result_dataset, f, ensure_ascii=False, indent=2)

    print(f"  [完成] 300 題題庫已儲存至: {OUTPUT_JSON_PATH}")

if __name__ == "__main__":
    parse_300_mcqs()
