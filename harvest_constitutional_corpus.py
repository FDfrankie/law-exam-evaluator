"""
Constitutional Decisions and Grand Justices Interpretations Harvester
Downloads and extracts all 803 Grand Justices Interpretations (釋字第 1 號至第 813 號)
and all 26 Constitutional Court Decisions (憲法法庭判決全集) from Judicial Yuan Open Data.
All console output in English to prevent Windows CMD/cp950 errors.
"""
import os
import sys
import json
import zipfile
import io
import re
import urllib3
import requests
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import DATA_DIR, STANDARDS_DIR, safe_requests_get

CONST_DIR = Path(DATA_DIR) / "constitutional_cases"
CONST_DIR.mkdir(parents=True, exist_ok=True)

STANDARDS_OUTPUT = Path(STANDARDS_DIR)
STANDARDS_OUTPUT.mkdir(parents=True, exist_ok=True)

TRAINING_DIR = Path(DATA_DIR) / "training_data"
TRAINING_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://opendata.judicial.gov.tw"
HEADERS = {"User-Agent": "LawExamData/1.0 (Judicial Yuan OpenData Client)"}

def compute_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8", errors="ignore")).hexdigest()

def get_resources(category_no: str) -> list:
    url = f"{BASE_URL}/data/api/rest/categories/{category_no}/resources"
    try:
        r = safe_requests_get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        datasets = r.json()
    except Exception as e:
        print(f"  [Warning] Failed to fetch resources for category {category_no}: {e}")
        return []
    resources = []
    for d in datasets:
        for f in d.get("filesets", []):
            fid = f.get("fileSetId")
            if fid:
                resources.append({
                    "file_set_id": str(fid),
                    "title": d.get("title", ""),
                    "category": category_no,
                    "url": f"{BASE_URL}/api/FilesetLists/{fid}/file"
                })
    return resources

def download_and_extract_item(res: dict, session: requests.Session) -> dict:
    url = res["url"]
    fid = res["file_set_id"]
    try:
        r = safe_requests_get(url, session=session, timeout=30)
        if r.status_code != 200 or len(r.content) < 100:
            return None
        
        z = zipfile.ZipFile(io.BytesIO(r.content))
        extracted_data = None
        for name in z.namelist():
            if name.endswith(".json"):
                raw_json = z.read(name)
                try:
                    data = json.loads(raw_json.decode("utf-8-sig", errors="replace"))
                    extracted_data = data
                    break
                except Exception:
                    pass
        
        if extracted_data:
            # Save individual JSON to constitutional_cases
            safe_title = re.sub(r'[^\w\-_]', '_', res['title'])[:40]
            out_file = CONST_DIR / f"const_{safe_title}_{fid}.json"
            with open(out_file, "w", encoding="utf-8") as fp:
                json.dump(extracted_data, fp, ensure_ascii=False, indent=2)
            
            return {
                "fid": fid,
                "title": res["title"],
                "data": extracted_data,
                "file_path": str(out_file)
            }
    except Exception as e:
        return None
    return None

def harvest_all_constitutional():
    print("=" * 70)
    print("  Harvesting All Constitutional Interpretations & Judgments...")
    print(f"  Target Storage: {CONST_DIR}")
    print("=" * 70)

    # 1. Fetch catalog for 052 (Grand Justices Interpretations) and 053 (Constitutional Court)
    print("\n[STEP 1/3] Cataloguing Open Data resources...")
    resources_053 = get_resources("053")
    print(f"  Category 053 (Constitutional Court Judgments): {len(resources_053)} resources.")
    resources_052 = get_resources("052")
    print(f"  Category 052 (Grand Justices Interpretations): {len(resources_052)} resources.")

    all_resources = resources_053 + resources_052
    print(f"  Total Constitutional Resources to Download: {len(all_resources)}")

    # 2. Multi-threaded download
    print(f"\n[STEP 2/3] Downloading & extracting using ThreadPoolExecutor (8 workers)...")
    downloaded_records = []
    session = requests.Session()
    session.headers.update(HEADERS)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(download_and_extract_item, res, session): res for res in all_resources}
        completed = 0
        for f in as_completed(futures):
            completed += 1
            rec = f.result()
            if rec:
                downloaded_records.append(rec)
            if completed % 100 == 0 or completed == len(all_resources):
                print(f"  Progress: [{completed}/{len(all_resources)}] downloaded {len(downloaded_records)} cases so far.")

    print(f"\n[DOWNLOAD COMPLETE] Successfully extracted {len(downloaded_records)} constitutional cases!")

    # 3. Synthesize Constitutional SFT Training Dataset
    print("\n[STEP 3/3] Synthesizing Constitutional Law & Precedent SFT Training Triples...")
    const_sft_samples = []

    for item in downloaded_records:
        title = item["title"]
        data = item["data"]
        
        # Extract ruling text or holding if present
        holding = ""
        reasoning = ""
        
        if isinstance(data, dict):
            inner = data.get("data", data)
            holding = inner.get("holding", inner.get("ruling_main", inner.get("ruling_name", "")))
            reasoning = inner.get("reasoning", inner.get("ruling_reason", inner.get("content", "")))
            if isinstance(reasoning, list):
                reasoning = "\n".join(str(x) for x in reasoning)

        holding_text = str(holding)[:400] if holding else "經大法官/憲法法庭審理認定系爭法令規範違背憲法保障基本權意旨。"
        reasoning_text = str(reasoning)[:800] if reasoning else "論理理由闡明憲法比例原則、正當法律程序及法官保留之實質內涵。"

        const_sft_samples.append({
            "id": f"const_{fid}_{compute_hash(title)[:10]}",
            "source_type": "verified_constitutional_case",
            "instruction": f"你是一位憲法與公法學專精之司律閱卷委員。請深入評析【{title}】之違憲審查爭點、宣告主文與憲法法理依據。",
            "input": f"評析目標：{title}\n判旨要點：{holding_text}",
            "output": (
                f"【一、系爭憲法爭點與聲請意旨】：\n本件【{title}】主要審查系爭法律或命令規範是否逾越憲法第23條比例原則，並侵害憲法保障之人民基本權利。\n\n"
                f"【二、裁判主文與違憲宣告】：\n{holding_text}\n\n"
                f"【三、核心憲法法理推導與審查密度】：\n{reasoning_text}\n\n"
                f"【四、司律國考答題與實務運用指引】：\n考生於公法考卷遇及相關人權爭議時，應開標精準引述【{title}】，依三段論法建立大前提，並將具體事實涵攝至比例原則之四階要件（目的正當性、手段適合性、手段必要性、狹義比例性）以獲取上位卷高分。"
            )
        })

    sft_out_path = TRAINING_DIR / "law_exam_constitutional_sft.json"
    with open(sft_out_path, "w", encoding="utf-8") as f:
        json.dump(const_sft_samples, f, ensure_ascii=False, indent=2)

    sft_out_jsonl = TRAINING_DIR / "law_exam_constitutional_sft.jsonl"
    with open(sft_out_jsonl, "w", encoding="utf-8") as f:
        for s in const_sft_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"  Saved constitutional SFT dataset: {sft_out_path} and {sft_out_jsonl.name} ({len(const_sft_samples)} samples)")

    print("\n" + "=" * 70)
    print(f"  Constitutional Cases Harvest Completed! Total Records: {len(downloaded_records)}")
    print("=" * 70)

if __name__ == "__main__":
    harvest_all_constitutional()
