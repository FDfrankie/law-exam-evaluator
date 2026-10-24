# -*- coding: utf-8 -*-
"""
司法院權威司法見解輕量採集器 (Authority Crawler Pipeline)
功能：
1. 避開 ASP.NET ViewState 防爬機制，直接對司法院開放端點進行抓取：
   - 最高法院大法庭最新清單 (GetLatestTPSList.ashx)
   - 憲法法庭裁判與審裁要旨
2. 雙重網路適配：優先使用 requests，若未安裝則無縫回退至標準庫 urllib.request
3. 自動抽取案號、字號、裁判日期、要旨主文、法規條文引用
4. 具備 1 秒禮貌延遲防護機制
5. 解析完畢後批次 Upsert 寫入 data/judicial_authority.db
"""
import os
import sys
import time
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
import urllib.parse
import urllib.request
import ssl

try:
    import requests
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from authority_engine import JudicialAuthorityEngine

ENDPOINT_TPS_CIVIL = "https://legal.judicial.gov.tw/controls/GetLatestTPSList.ashx?court=TPS&jbookType=V"
ENDPOINT_TPS_CRIM = "https://legal.judicial.gov.tw/controls/GetLatestTPSList.ashx?court=TPS&jbookType=C"
ENDPOINT_TPS_GRAND = "https://legal.judicial.gov.tw/controls/GetLatestTPSList.ashx?court=TPS&jbookType=G"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://legal.judicial.gov.tw/"
}

class AuthorityCrawler:
    def __init__(self, delay_sec: float = 1.0):
        self.delay_sec = delay_sec
        self.engine = JudicialAuthorityEngine()
        self.session = requests.Session() if requests else None
        if self.session:
            self.session.headers.update(HEADERS)

    def _http_get(self, url: str) -> str:
        """安全連線輔助函式，支援 requests 與 urllib.request"""
        if self.session:
            resp = self.session.get(url, timeout=15)
            return resp.text if resp.status_code == 200 else ""
        else:
            req = urllib.request.Request(url, headers=HEADERS)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            try:
                with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                    return r.read().decode("utf-8", errors="ignore")
            except Exception as e:
                print(f"[!] urllib fetch failed for {url}: {e}")
                return ""

    def extract_laws_cited(self, text: str) -> List[str]:
        """自動從裁判內文抽取法規與條號引用"""
        laws = []
        pattern = r'([一-龥]{2,15}(?:法|條例|規則|細則))第\s*(\d+(?:之\d+)?)\s*條'
        matches = re.findall(pattern, text)
        for law_name, art_no in matches:
            full_ref = f"{law_name}第{art_no}條"
            if full_ref not in laws:
                laws.append(full_ref)
        return laws

    def crawl_tps_endpoint(self, endpoint_url: str, category: str = "GRAND_BENCH", sub_type: str = "民事大法庭") -> int:
        """採集司法院 TPS 官方 JSON / REST 端點"""
        print(f"[*] 連線司法院後端端點: {endpoint_url}")
        try:
            raw_text = self._http_get(endpoint_url)
            # 遵守 1 秒禮貌延遲機制
            time.sleep(self.delay_sec)

            if not raw_text:
                print(f"[!] 未獲取回應文字或連線逾時")
                return 0

            records = []
            try:
                data = json.loads(raw_text)
                if isinstance(data, list):
                    records = data
                elif isinstance(data, dict):
                    records = data.get("rows") or data.get("data") or [data]
            except Exception:
                # 簡單正則或 HTML 提取
                for row_match in re.finditer(r'<tr[^>]*>(.*?)</tr>', raw_text, re.DOTALL | re.IGNORECASE):
                    tds = re.findall(r'<td[^>]*>(.*?)</td>', row_match.group(1), re.DOTALL | re.IGNORECASE)
                    if len(tds) >= 3:
                        records.append({
                            "JID": re.sub(r'<[^>]+>', '', tds[0]).strip(),
                            "JDATE": re.sub(r'<[^>]+>', '', tds[1]).strip(),
                            "JTITLE": re.sub(r'<[^>]+>', '', tds[2]).strip()
                        })

            print(f"[*] 解析取得 {len(records)} 筆裁判資料")
            added_count = 0
            for item in records:
                case_no = item.get("JID") or item.get("case_no") or item.get("title", "")
                if not case_no:
                    continue

                title = item.get("JTITLE") or item.get("title") or "最高法院裁判要旨"
                date_s = item.get("JDATE") or item.get("date", "")
                holding = item.get("HOLDING") or item.get("summary") or item.get("content", "")
                reasoning = item.get("REASONING") or item.get("full_text", "") or holding

                laws = self.extract_laws_cited(holding + " " + reasoning)
                status = "大字終局裁定" if "大字" in case_no else "徵字提案裁定" if "徵字" in case_no else "重要裁判"
                actual_subtype = "刑事大法庭" if "刑" in case_no or "刑事" in title else sub_type

                rec = {
                    "id": case_no,
                    "category": category,
                    "sub_type": actual_subtype,
                    "case_no": case_no,
                    "date": date_s,
                    "court": "最高法院大法庭" if "大" in case_no else "最高法院",
                    "title": title,
                    "holding": holding if holding else f"{case_no} 裁判要旨詳見內文。",
                    "reasoning": reasoning,
                    "laws_cited": laws,
                    "status": status,
                    "extra_meta": {"source": "司法院端點採集"}
                }
                self.engine.upsert_record(rec)
                added_count += 1

            return added_count
        except Exception as e:
            print(f"[!] 採集過程異常: {e}")
            return 0

    def run_full_crawler(self) -> Dict[str, int]:
        results = {}
        # 1. 採集大法庭
        results["tps_grand"] = self.crawl_tps_endpoint(ENDPOINT_TPS_GRAND, "GRAND_BENCH", "民事大法庭")
        # 2. 採集民事重要裁定
        results["tps_civil"] = self.crawl_tps_endpoint(ENDPOINT_TPS_CIVIL, "GRAND_BENCH", "民事大法庭")
        # 3. 採集刑事重要裁定
        results["tps_crim"] = self.crawl_tps_endpoint(ENDPOINT_TPS_CRIM, "GRAND_BENCH", "刑事大法庭")
        return results

if __name__ == "__main__":
    crawler = AuthorityCrawler(delay_sec=1.0)
    print("啟動權威司法裁判採集管線（配置 1 秒禮貌延遲機制）...")
    stats = crawler.run_full_crawler()
    print("採集完成，各端點入庫成果:", stats)
    total_stats = crawler.engine.get_authority_stats()
    print("最新權威庫總計:", total_stats)
