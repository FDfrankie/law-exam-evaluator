"""
National Laws and Regulations Ingestion Engine
Downloads and extracts the entire Republic of China (Taiwan) National Laws Database
directly from the Ministry of Justice (MOJ) Open Data API.
Outputs to: G:\\我的雲端硬碟\\LawExamData\\national_laws\\
"""
import os
import sys
import json
import zipfile
import urllib3
import requests
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import DATA_DIR, safe_requests_get

OUTPUT_DIR = Path(DATA_DIR) / "national_laws"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CH_LAW_URL = "https://law.moj.gov.tw/api/ch/law/json"
CH_ORDER_URL = "https://law.moj.gov.tw/api/ch/order/json"

def download_and_extract(url: str, name: str) -> Path:
    print(f"[DOWNLOADING] {name} from {url}...")
    zip_path = OUTPUT_DIR / f"{name}.zip"
    
    # Download with safe TLS verification and fallback
    r = safe_requests_get(url, stream=True, timeout=60)
    r.raise_for_status()
    total_bytes = 0
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)
                total_bytes += len(chunk)
    
    print(f"  [SAVED] {name}.zip ({total_bytes / (1024*1024):.2f} MB)")
    
    # Extract
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(OUTPUT_DIR)
        extracted_files = z.namelist()
        print(f"  [EXTRACTED] {extracted_files}")
    
    # Clean up zip
    if zip_path.exists():
        zip_path.unlink()
        
    return OUTPUT_DIR / extracted_files[0]

def inspect_and_index():
    ch_law_file = OUTPUT_DIR / "ChLaw.json"
    if not ch_law_file.exists():
        ch_law_file = download_and_extract(CH_LAW_URL, "ChLaw")
    
    print("\n[INDEXING] Loading national laws...")
    with open(ch_law_file, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    
    laws = data.get("Laws", [])
    print(f"  Total National Laws: {len(laws)}")
    
    # Sample inspection
    total_articles = 0
    categories = {}
    for law in laws:
        law_name = law.get("LawName", "")
        law_category = law.get("LawCategory", "")
        categories[law_category] = categories.get(law_category, 0) + 1
        articles = law.get("LawArticles", [])
        total_articles += len(articles)
        
    print(f"  Total Statutory Articles across all laws: {total_articles}")
    print(f"  Total Categories: {len(categories)}")
    
    # Create an index of core bar exam subjects
    core_subjects = [
        "民法", "刑法", "民事訴訟法", "刑事訴訟法", "中華民國憲法", "行政程序法", "行政訴訟法",
        "公司法", "證券交易法", "保險法", "票據法", "勞動基準法", "著作權法", "專利法", "商標法",
        "營業秘密法", "公平交易法", "消費者保護法", "國民法官法", "涉外民事法律適用法"
    ]
    
    found_core = []
    for law in laws:
        for cs in core_subjects:
            if cs in law.get("LawName", ""):
                found_core.append({
                    "name": law.get("LawName"),
                    "articles_count": len(law.get("LawArticles", [])),
                    "category": law.get("LawCategory"),
                    "last_modified": law.get("LawModifiedDate")
                })
                break
                
    print(f"  Found {len(found_core)} core examination statutes.")
    
    # Save a summary index
    summary_path = OUTPUT_DIR / "national_laws_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "total_laws": len(laws),
            "total_articles": total_articles,
            "core_exam_laws": found_core
        }, f, ensure_ascii=False, indent=2)
        
    print(f"  Summary saved to {summary_path}")

if __name__ == "__main__":
    download_and_extract(CH_LAW_URL, "ChLaw")
    download_and_extract(CH_ORDER_URL, "ChOrder")
    inspect_and_index()
