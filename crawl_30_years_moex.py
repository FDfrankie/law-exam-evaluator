"""
考選部近30年 (84年～113年) 司律與司法特考全真試題庫爬蟲與索引生成器
自動爬取歷年司法官二試、律師二試、司法官律師一試、司法人員特考全真試題
"""
import sys
import json
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path

# 終端編碼防護
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from config import RAW_DATA_DIR

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

CATALOG_PATH = Path(RAW_DATA_DIR) / "exams_catalog.json"
REPO_CATALOG_PATH = Path(__file__).resolve().parent / "data" / "raw_exams" / "exams_catalog.json"

def crawl_30_years_moex():
    print("=" * 75)
    print("  🚀 啟動考選部歷年 (84年~113年 / 1995~2024) 司律與司法特考全卷爬取與索引編纂")
    print("=" * 75)

    existing_catalog = []
    if CATALOG_PATH.exists():
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                existing_catalog = json.load(f)
        except Exception:
            existing_catalog = []

    seen_ids = set(item.get("exam_id") for item in existing_catalog if item.get("exam_id"))
    new_items = []

    core_keywords = [
        '民法', '刑法', '憲法', '行政法', '民事訴訟法', '刑事訴訟法', '民訴', '刑訴',
        '商事法', '公司法', '保險法', '證券交易法', '票據法', '智慧財產法', '智慧財產權法',
        '勞動社會法', '勞工法', '財稅法', '稅法', '海商法', '海洋法', '國際公法', '國際私法',
        '綜合法學', '法學緒論', '強制執行法', '法院組織法', '破產法', '智慧財產', '身分法', '物權'
    ]

    for roc_yr in range(113, 83, -1):
        ad_yr = roc_yr + 1911
        url = f'https://wwwq.moex.gov.tw/exam/wFrmExamQandASearch.aspx?y={ad_yr}'
        try:
            r = session.get(url, timeout=12)
            soup = BeautifulSoup(r.text, 'html.parser')
            sel = soup.find('select', id='ctl00_holderContent_ddlExamCode')
            if not sel:
                continue

            target_codes = []
            for o in sel.find_all('option'):
                code = o.get('value', '').strip()
                name = o.get_text().strip()
                if code and any(k in name for k in ['司法官', '律師', '司法人員']):
                    target_codes.append((code, name))

            year_count = 0
            for code, exam_name in target_codes:
                exam_url = f'https://wwwq.moex.gov.tw/exam/wFrmExamQandASearch.aspx?y={ad_yr}&e={code}'
                try:
                    er = session.get(exam_url, timeout=12)
                    esoup = BeautifulSoup(er.text, 'html.parser')
                    tbl = esoup.find('table', id='ctl00_holderContent_tblExamQand')
                    if not tbl:
                        continue

                    cur_dept = exam_name
                    for tr in tbl.find_all('tr'):
                        cells = [c.get_text().strip() for c in tr.find_all(['td', 'th']) if c.get_text().strip()]
                        if not cells:
                            continue
                        if any(k in cells[0] for k in ['司法官', '律師', '類科', '等別']):
                            cur_dept = cells[0]

                        for a in tr.find_all('a'):
                            href = a.get('href', '')
                            if 't=Q' in href:
                                subj = cells[0].replace('試題', '').strip()
                                if any(k in subj for k in core_keywords):
                                    # 提取參數以生成唯一 ID
                                    # href: wHandExamQandA_File.ashx?t=Q&code=113111&c=301&s=0102&q=1
                                    params = dict(p.split('=') for p in href.split('?')[-1].split('&') if '=' in p)
                                    c_val = params.get('c', '000')
                                    s_val = params.get('s', '0000')
                                    q_val = params.get('q', '1')
                                    clean_subj = subj.replace(' ', '_').replace('/', '_')
                                    exam_id = f"MOEX_{roc_yr}_{code}_{c_val}_{s_val}_q{q_val}_{clean_subj}"

                                    if exam_id not in seen_ids:
                                        seen_ids.add(exam_id)
                                        category = (
                                            '司法官律師第二試' if any(k in exam_name for k in ['二試', '第二試'])
                                            else ('司法官律師第一試' if any(k in exam_name for k in ['一試', '第一試'])
                                            else '司法人員特考')
                                        )
                                        q_url = 'https://wwwq.moex.gov.tw/exam/' + href
                                        
                                        item = {
                                            "exam_id": exam_id,
                                            "year": str(roc_yr),
                                            "school": "考選部",
                                            "category": category,
                                            "department": cur_dept,
                                            "subject": subj,
                                            "exam_text": f"【{roc_yr}年 {exam_name}】\n等別類科：{cur_dept}\n科目：{subj}\n[本題為考選部公務全真試卷，點擊下方按鈕可即時轉錄試題或帶入批改]",
                                            "pdf_url": q_url,
                                            "pdf_file": f"{exam_id}.pdf"
                                        }
                                        new_items.append(item)
                                        year_count += 1
                except Exception as ee:
                    pass

            print(f"  [{roc_yr}年 ({ad_yr})] 收錄新增 {year_count} 份考卷 (累計庫存: {len(existing_catalog) + len(new_items)} 份)", flush=True)
            time.sleep(0.05)

        except Exception as e:
            print(f"  [警示] 處理 {roc_yr} 年失敗: {e}", flush=True)

    # 合併現有與新爬取試題
    total_catalog = existing_catalog + new_items
    print(f"\n[保存] 正在將 {len(total_catalog):,} 份真題存入目錄庫...", flush=True)
    
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(total_catalog, f, ensure_ascii=False, indent=2)

    REPO_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPO_CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(total_catalog, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 主庫存檔成功：{CATALOG_PATH} ({CATALOG_PATH.stat().st_size / (1024*1024):.2f} MB)", flush=True)
    print(f"  ✅ 鏡像存檔成功：{REPO_CATALOG_PATH} ({REPO_CATALOG_PATH.stat().st_size / (1024*1024):.2f} MB)", flush=True)
    print("=" * 75, flush=True)
    return len(total_catalog)

if __name__ == "__main__":
    crawl_30_years_moex()
