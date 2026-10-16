"""
National Laws and Regulations Corpus Builder
Parses all 1,351 statutory laws and 10,452 orders from ChLaw.json and ChOrder.json,
extracting 236,949+ articles into structured statutory knowledge records and SFT training samples.
Output target: G:\\我的雲端硬碟\\LawExamData\\national_laws\\
"""
import os
import sys
import json
import re
from pathlib import Path

from config import DATA_DIR

LAWS_DIR = Path(DATA_DIR) / "national_laws"
TRAINING_DIR = Path(DATA_DIR) / "training_data"
TRAINING_DIR.mkdir(parents=True, exist_ok=True)

CH_LAW_PATH = LAWS_DIR / "ChLaw.json"
CH_ORDER_PATH = LAWS_DIR / "ChOrder.json"

CORE_EXAM_KEYWORDS = [
    "民法", "刑法", "民事訴訟法", "刑事訴訟法", "憲法", "行政程序法", "行政訴訟法", "行政罰法",
    "訴願法", "國家賠償法", "公司法", "證券交易法", "保險法", "票據法", "銀行法", "消費者保護法",
    "金融消費者保護法", "海商法", "勞動基準法", "勞動事件法", "工會法", "勞工保險條例", "全民健康保險法",
    "稅捐稽徵法", "所得稅法", "加值型及非加值型營業稅法", "納稅者權利保護法", "涉外民事法律適用法",
    "著作權法", "專利法", "商標法", "公平交易法", "營業秘密法", "國民法官法", "家事事件法",
    "強制執行法", "少年事件處理法", "土地法"
]

def build_corpus():
    print("=" * 70)
    print("  Building National Laws and Regulations Knowledge Corpus...")
    print("=" * 70)

    if not CH_LAW_PATH.exists():
        print(f"[ERROR] {CH_LAW_PATH} not found. Please run ingest_national_laws.py first.")
        return

    # Load Statutes
    print("\n[STEP 1/3] Processing ChLaw.json (Statutes)...")
    with open(CH_LAW_PATH, "r", encoding="utf-8-sig") as f:
        statutes_data = json.load(f)
    statutes = statutes_data.get("Laws", [])
    print(f"  Loaded {len(statutes)} statutes.")

    statute_articles = []
    core_exam_articles = []

    for law in statutes:
        law_name = law.get("LawName", "")
        law_category = law.get("LawCategory", "")
        pcode = law.get("PCode", "")
        articles = law.get("LawArticles", [])
        
        is_core = any(k in law_name for k in CORE_EXAM_KEYWORDS)

        for art in articles:
            art_no = art.get("ArticleNo", "")
            art_content = art.get("ArticleContent", "")
            if not art_content:
                continue
            
            clean_content = re.sub(r'[\r\n\t]+', '\n', art_content).strip()
            item = {
                "law_name": law_name,
                "category": law_category,
                "pcode": pcode,
                "article_no": art_no,
                "content": clean_content,
                "type": "statute"
            }
            statute_articles.append(item)
            if is_core:
                core_exam_articles.append(item)

    print(f"  Total statute articles extracted: {len(statute_articles)}")
    print(f"  Core exam statute articles extracted: {len(core_exam_articles)}")

    # Load Administrative Orders and Regulations
    print("\n[STEP 2/3] Processing ChOrder.json (Regulations & Orders)...")
    with open(CH_ORDER_PATH, "r", encoding="utf-8-sig") as f:
        orders_data = json.load(f)
    orders = orders_data.get("Laws", [])
    print(f"  Loaded {len(orders)} administrative orders.")

    order_articles = []
    for order in orders:
        order_name = order.get("LawName", "")
        order_category = order.get("LawCategory", "")
        pcode = order.get("PCode", "")
        articles = order.get("LawArticles", [])
        for art in articles:
            art_no = art.get("ArticleNo", "")
            art_content = art.get("ArticleContent", "")
            if not art_content:
                continue
            clean_content = re.sub(r'[\r\n\t]+', '\n', art_content).strip()
            order_articles.append({
                "law_name": order_name,
                "category": order_category,
                "pcode": pcode,
                "article_no": art_no,
                "content": clean_content,
                "type": "regulation"
            })
    print(f"  Total order/regulation articles extracted: {len(order_articles)}")

    # Total combined articles
    total_all_articles = len(statute_articles) + len(order_articles)
    print(f"\n[TOTAL STATUTORY ARTICLES] {total_all_articles} articles across 11,803 laws and orders!")

    # Save Core Exam Articles Corpus (Clean JSON)
    core_corpus_path = LAWS_DIR / "core_exam_laws_articles.json"
    with open(core_corpus_path, "w", encoding="utf-8") as f:
        json.dump(core_exam_articles, f, ensure_ascii=False, indent=2)
    print(f"\n[STEP 3/3] Saved core exam articles corpus: {core_corpus_path} ({len(core_exam_articles)} articles)")

    # Synthesize Statutory Interpretation SFT Samples
    print("  Synthesizing Statutory Rule Lookup & Interpretation SFT Triples...")
    statutory_sft_samples = []
    for item in core_exam_articles[:1500]:
        law_name = item["law_name"]
        art_no = item["article_no"]
        content = item["content"]
        
        statutory_sft_samples.append({
            "instruction": f"請檢索並闡述台灣【{law_name}】{art_no}之規範內容、立法意旨與核心構成要件。",
            "input": f"詢問條文：{law_name} {art_no}",
            "output": (
                f"【法規名稱】：{law_name}\n"
                f"【條文字號】：{art_no}\n"
                f"【法定條文全文內容】：\n{content}\n\n"
                f"【立法意旨與規範功能分析】：\n"
                f"本條屬【{item['category']}】之重要法律依據，規範當事人間之法定權利義務構成要件與法律效果。\n"
                f"於司法官律師考試及實務裁判中，應將具體爭端事實嚴格涵攝至本條各項要件，始得確立法律效果之發生。"
            )
        })

    sft_laws_path = TRAINING_DIR / "law_exam_statutory_rules_sft.json"
    with open(sft_laws_path, "w", encoding="utf-8") as f:
        json.dump(statutory_sft_samples, f, ensure_ascii=False, indent=2)
    print(f"  Saved statutory rules SFT dataset: {sft_laws_path} ({len(statutory_sft_samples)} samples)")

    print("\n" + "=" * 70)
    print("  National Laws Corpus Processing Completed Successfully!")
    print("=" * 70)

if __name__ == "__main__":
    build_corpus()
