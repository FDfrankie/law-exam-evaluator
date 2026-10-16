"""
司法院裁判書開放資料與最高法院裁判檢索模組
專門爬取/抓取具有參考價值裁判與大法庭裁定，同步儲存至 Google Drive 作為評分依據。
"""
import json
import requests
from pathlib import Path
from config import STANDARDS_DIR

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
}

class JudicialJudgementCrawler:
    """司法院裁判書檢索輔助類別"""
    def __init__(self, output_dir=STANDARDS_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def save_judgement(self, court: str, jid: str, date: str, main_text: str, reasoning: str, issues: list = None):
        """
        將裁判書重點（主文、理由與爭點）儲存為標準 JSON 與 Markdown 存入 Google Drive
        """
        record = {
            "court": court,
            "judgement_id": jid,
            "date": date,
            "main_text": main_text,
            "reasoning": reasoning,
            "core_issues": issues or []
        }
        
        filename = f"{jid.replace(' ', '_').replace('/', '_')}"
        json_path = self.output_dir / f"{filename}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        md_path = self.output_dir / f"{filename}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# 【{court}】{jid} 裁判評析\n\n")
            f.write(f"- **裁判日期**：{date}\n\n")
            f.write(f"## 主文\n\n{main_text}\n\n")
            f.write(f"## 理由重點與爭點摘要\n\n{reasoning}\n\n")
            if issues:
                f.write("## 核心法律爭點\n\n")
                for iss in issues:
                    f.write(f"- {iss}\n")

        print(f"[已儲存裁判書至 Google Drive] {json_path}")
        return json_path
