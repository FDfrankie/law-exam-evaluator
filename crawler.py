"""
考選部歷屆試題與評分參考資料爬蟲模組
專門爬取司律（司法官、律師）二試申論題題目、評分要點與試題大綱，並儲存至 Google Drive。
"""
import json
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from config import RAW_DATA_DIR, STANDARDS_DIR

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

class MoexCrawler:
    """考選部 (MOEX) 試題資料庫爬蟲"""
    def __init__(self, output_dir=RAW_DATA_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def download_file(self, url: str, target_path: Path):
        """下載檔案至指定目錄"""
        try:
            resp = self.session.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            with open(target_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"下載失敗 {url}: {e}")
            return False

    def save_exam_record(self, year: int, subject: str, question_text: str, reference_points: list = None):
        """
        將爬取或整理後的試題與爭點大綱結構化儲存為 JSON 與 Markdown，便於 LLM 讀取與訓練。
        """
        record = {
            "year": year,
            "category": "司法官及專門職業及技術人員高等考試律師考試",
            "subject": subject,
            "question": question_text,
            "reference_points": reference_points or [],
        }
        
        file_base = f"{year}_{subject.replace('/', '_')}"
        json_file = self.output_dir / f"{file_base}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
            
        md_file = self.output_dir / f"{file_base}.md"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(f"# {year}年 司律二試 - {subject}\n\n")
            f.write("## 題目\n\n" + question_text + "\n\n")
            if reference_points:
                f.write("## 核心爭點與評分指標\n\n")
                for pt in reference_points:
                    f.write(f"- {pt}\n")

        print(f"[已儲存試題至 Google Drive] {json_file}")
        return json_file

if __name__ == "__main__":
    crawler = MoexCrawler()
    print("MoexCrawler 模組就緒，儲存路徑為:", crawler.output_dir)
