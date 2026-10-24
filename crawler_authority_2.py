# -*- coding: utf-8 -*-
"""
司法院高階權威見解即時採集管線（Authority Crawler Pipeline 2.0）
===================================================================
功能涵蓋：
1. 最高法院（TPS）端點採集：
   - 民事大法庭 (jbookType=V)
   - 刑事大法庭 (jbookType=C)
   - 大法庭裁判要旨 (jbookType=G)
2. 憲法法庭端點與裁定採集（crawl_constitutional_orders_endpoint）：
   - 憲判字（憲法法庭實體判決）
   - 憲裁字（憲法法庭實體裁定）
   - 憲審裁字（審查庭不受理裁定與程序裁定）
3. 自動結構化抽取：案號、裁判日期、案由、主文（holding）、理由（reasoning）、相關法條（laws_cited）
4. 預設配置 1 秒禮貌延遲機制，並支援斷點與 Upsert 寫入 data/judicial_authority.db
"""

import os
import sys
import time
import json
import re
import argparse
import ssl
from pathlib import Path
from typing import Dict, Any, List, Optional
import urllib.parse
import urllib.request

# 終端輸出編碼保護
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

from authority_engine import JudicialAuthorityEngine

# 官方端點配置
ENDPOINT_TPS_CIVIL = "https://legal.judicial.gov.tw/controls/GetLatestTPSList.ashx?court=TPS&jbookType=V"
ENDPOINT_TPS_CRIM = "https://legal.judicial.gov.tw/controls/GetLatestTPSList.ashx?court=TPS&jbookType=C"
ENDPOINT_TPS_GRAND = "https://legal.judicial.gov.tw/controls/GetLatestTPSList.ashx?court=TPS&jbookType=G"

FINT_BASE_URL = "https://legal.judicial.gov.tw/FINT/"
FINT_QRY_URL = "https://legal.judicial.gov.tw/FINT/qryresult.aspx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://legal.judicial.gov.tw/FINT/default.aspx"
}


class AuthorityCrawler:
    def __init__(self, delay_sec: float = 1.0):
        self.delay_sec = delay_sec
        self.engine = JudicialAuthorityEngine()
        self.session = requests.Session() if requests else None
        if self.session:
            self.session.headers.update(HEADERS)

    def _http_get(self, url: str, referer: Optional[str] = None) -> str:
        """安全連線函式，支援 requests 與 urllib.request 自動降級"""
        headers = dict(HEADERS)
        if referer:
            headers["Referer"] = referer

        if self.session:
            try:
                resp = self.session.get(url, headers=headers, verify=False, timeout=20)
                return resp.text if resp.status_code == 200 else ""
            except Exception as e:
                print(f"[!] requests 連線失敗 {url}: {e}")
                return ""
        else:
            req = urllib.request.Request(url, headers=headers)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            try:
                with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
                    return r.read().decode("utf-8", errors="ignore")
            except Exception as e:
                print(f"[!] urllib 連線失敗 {url}: {e}")
                return ""

    def extract_laws_cited(self, text: str) -> List[str]:
        """自動從裁判內文抽取法規與條號引用"""
        laws = []
        if not text:
            return laws
        pattern = r'([一-龥]{2,15}(?:憲法|法|條例|規則|細則))第\s*(\d+(?:之\d+)?)\s*條'
        matches = re.findall(pattern, text)
        for law_name, art_no in matches:
            full_ref = f"{law_name}第{art_no}條"
            if full_ref not in laws:
                laws.append(full_ref)
        return laws

    # =========================================================================
    # 1. 最高法院（TPS）大法庭與重要裁判端點採集
    # =========================================================================
    def crawl_tps_endpoint(self, endpoint_url: str, category: str = "GRAND_BENCH", sub_type: str = "民事大法庭") -> int:
        """採集司法院 TPS 官方 JSON / REST 端點"""
        print(f"[*] 連線司法院最高法院端點: {endpoint_url}")
        try:
            raw_text = self._http_get(endpoint_url)
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
            print(f"[!] 最高法院端點採集過程異常: {e}")
            return 0

    # =========================================================================
    # 2. 憲法法庭裁判與審裁要旨端點採集 (憲裁字、憲審裁字、憲判字)
    # =========================================================================
    def crawl_constitutional_orders_endpoint(self, max_pages: int = 5, sub_type_filter: Optional[List[str]] = None) -> int:
        """
        採集憲法法庭官方裁判與裁定端點（ty=JCC）。
        涵蓋：
        - 憲判字（憲法法庭判決）
        - 憲裁字（憲法法庭實體裁定）
        - 憲審裁字（審查庭不受理裁定與程序裁定）
        """
        print(f"[*] 啟動憲法法庭權威見解端點採集 (預計掃描前 {max_pages} 頁，約 {max_pages * 20} 筆最新裁定/判決)...")
        
        # 1. 取得會話 q_hash
        entry_html = self._http_get(FINT_QRY_URL)
        m_q = re.search(r'q=([a-f0-9]{32})', entry_html)
        q_hash = m_q.group(1) if m_q else "53f93baa3057821107c750323892fa92"
        print(f"[+] 獲取憲法法庭查詢識別碼 (q): {q_hash}")

        added_count = 0
        parsed_cases = set()

        for page in range(1, max_pages + 1):
            list_url = f"{FINT_BASE_URL}qryresultlst.aspx?ty=JCC&q={q_hash}&sort=DS&page={page}"
            list_html = self._http_get(list_url, referer=FINT_QRY_URL)
            time.sleep(self.delay_sec)

            if not BeautifulSoup:
                print("[!] 未安裝 BeautifulSoup，跳過解析。")
                break

            soup = BeautifulSoup(list_html, "html.parser")
            data_links = soup.find_all("a", href=lambda h: h and "data.aspx" in h)
            if not data_links:
                print(f"  [*] 第 {page} 頁無更多資料，結束掃描。")
                break

            print(f"[*] 正在處理第 {page}/{max_pages} 頁（本頁發現 {len(data_links)} 筆案件）...")

            for a_el in data_links:
                link_text = a_el.text.strip()
                rel_url = a_el["href"].strip()
                detail_url = urllib.parse.urljoin(FINT_BASE_URL, rel_url)

                try:
                    detail_html = self._http_get(detail_url, referer=list_url)
                    time.sleep(self.delay_sec)

                    if not detail_html:
                        continue

                    det_soup = BeautifulSoup(detail_html, "html.parser")
                    full_text = det_soup.text

                    # 1. 裁判字號
                    m_case = re.search(r'裁判字號[：:\s]*\n*([^\n\r]+)', full_text)
                    case_no = ""
                    if m_case:
                        case_no = re.sub(r'\s+', ' ', m_case.group(1)).strip()
                    if not case_no:
                        case_no = link_text

                    if not case_no or case_no in parsed_cases:
                        continue
                    parsed_cases.add(case_no)

                    # 2. 裁判日期
                    m_date = re.search(r'裁判日期[：:\s]*\n*([^\n\r]+)', full_text)
                    date_s = ""
                    if m_date:
                        date_s = re.sub(r'\s+', '', m_date.group(1)).strip()

                    # 3. 案由
                    m_cause = re.search(r'裁判案由[：:\s]*\n*([^\n\r]+)', full_text)
                    title = ""
                    if m_cause:
                        title = re.sub(r'\s+', ' ', m_cause.group(1)).strip()
                    if not title:
                        title = f"{case_no} 憲法裁判"

                    # 4. 主文 (Holding)
                    m_main = re.search(r'主\s*文\s*([\s\S]*?)(?:理\s*由|中\s*華\s*民\s*國|$)', full_text)
                    holding = ""
                    if m_main:
                        holding = re.sub(r'\s+', ' ', m_main.group(1)).strip()
                    if not holding:
                        holding = "詳見裁定或判決全文。"

                    # 5. 理由 (Reasoning)
                    m_reason = re.search(r'理\s*由\s*([\s\S]*?)(?:中\s*華\s*民\s*國\s*[0-9]{1,3}\s*年|$)', full_text)
                    reasoning = ""
                    if m_reason:
                        reasoning = m_reason.group(1).strip()
                    if not reasoning:
                        reasoning = full_text

                    # 6. 裁判類型與審裁分類 (判決 / 實體裁定 / 審查庭裁定)
                    if "憲判字" in case_no or "判決" in link_text:
                        sub_type = "憲法法庭判決"
                        status = "實體確定判決"
                    elif "審裁字" in case_no or "審查庭" in full_text:
                        sub_type = "憲法法庭審裁"
                        status = "審查庭不受理裁定" if "不受理" in holding else "審查庭裁定"
                    elif "憲裁字" in case_no or "裁定" in link_text:
                        sub_type = "憲法法庭實體裁定"
                        status = "實體裁定"
                    else:
                        sub_type = "憲法法庭裁判"
                        status = "一般裁判"

                    # 若指定了過濾條件則進行篩選
                    if sub_type_filter and sub_type not in sub_type_filter:
                        continue

                    # 7. 提取法條引用
                    laws = self.extract_laws_cited(holding + " " + reasoning)

                    rec = {
                        "id": case_no,
                        "category": "CONSTITUTIONAL_COURT",
                        "sub_type": sub_type,
                        "case_no": case_no,
                        "date": date_s,
                        "court": "憲法法庭",
                        "title": title,
                        "holding": holding,
                        "reasoning": reasoning,
                        "laws_cited": laws,
                        "status": status,
                        "extra_meta": {
                            "source": "司法院憲法法庭端點",
                            "source_url": detail_url
                        }
                    }

                    self.engine.upsert_record(rec)
                    added_count += 1
                    print(f"  [✓] 成功入庫: 【{case_no}】({sub_type}) - {status} ｜ 日期: {date_s}")

                except Exception as pe:
                    print(f"  [!] 解析案件內頁失敗 {detail_url}: {pe}")
                    time.sleep(0.5)

        print(f"[✓] 憲法法庭端點採集完畢，累計入庫 {added_count} 筆憲法判決與審裁。")
        return added_count

    # =========================================================================
    # 3. 完整權威見解整合採集流程 (Full Pipeline)
    # =========================================================================
    def run_full_crawler(self, constitutional_pages: int = 5) -> Dict[str, int]:
        """完整執行所有司法院高階權威見解採集流程"""
        results = {}
        print("=" * 60)
        print("🚀 啟動司法院高階權威司法見解即時採集管線")
        print("=" * 60)

        # 1. 採集最高法院大法庭
        results["tps_grand"] = self.crawl_tps_endpoint(ENDPOINT_TPS_GRAND, "GRAND_BENCH", "民事大法庭")
        # 2. 採集最高法院民事重要裁定
        results["tps_civil"] = self.crawl_tps_endpoint(ENDPOINT_TPS_CIVIL, "GRAND_BENCH", "民事大法庭")
        # 3. 採集最高法院刑事重要裁定
        results["tps_crim"] = self.crawl_tps_endpoint(ENDPOINT_TPS_CRIM, "GRAND_BENCH", "刑事大法庭")
        # 4. 採集憲法法庭（憲裁字、憲審裁字、憲判字）
        results["constitutional_orders"] = self.crawl_constitutional_orders_endpoint(max_pages=constitutional_pages)

        return results


def main():
    parser = argparse.ArgumentParser(description="司法院高階權威見解即時採集管線 2.0")
    parser.add_argument("--constitutional-only", action="store_true", help="僅採集憲法法庭裁判與審裁端點")
    parser.add_argument("--tps-only", action="store_true", help="僅採集最高法院大法庭端點")
    parser.add_argument("--pages", type=int, default=3, help="憲法法庭採集頁數（每頁 20 筆，預設 3 頁）")
    parser.add_argument("--delay", type=float, default=1.0, help="禮貌延遲秒數（預設 1.0 秒）")
    parser.add_argument("--status", action="store_true", help="顯示目前權威裁判庫統計")

    args = parser.parse_args()
    crawler = AuthorityCrawler(delay_sec=args.delay)

    if args.status:
        st = crawler.engine.get_authority_stats()
        print("\n" + "=" * 60)
        print("📊 司法權威裁判庫目前統計")
        print("=" * 60)
        for k, v in st.items():
            print(f"• {k}: {v}")
        print("=" * 60)
        return

    if args.constitutional_only:
        cnt = crawler.crawl_constitutional_orders_endpoint(max_pages=args.pages)
        print(f"\n[✓] 憲法法庭採集作業完成，共入庫 {cnt} 筆。")
        return

    if args.tps_only:
        r_grand = crawler.crawl_tps_endpoint(ENDPOINT_TPS_GRAND, "GRAND_BENCH", "民事大法庭")
        r_civ = crawler.crawl_tps_endpoint(ENDPOINT_TPS_CIVIL, "GRAND_BENCH", "民事大法庭")
        r_crim = crawler.crawl_tps_endpoint(ENDPOINT_TPS_CRIM, "GRAND_BENCH", "刑事大法庭")
        print(f"\n[✓] 最高法院端點採集完成: 大法庭 {r_grand} 筆, 民事 {r_civ} 筆, 刑事 {r_crim} 筆。")
        return

    # 全量執行
    stats = crawler.run_full_crawler(constitutional_pages=args.pages)
    print("\n" + "=" * 60)
    print("🎉 全量採集作業完成！各端點入庫成果：", stats)
    total_stats = crawler.engine.get_authority_stats()
    print("📈 最新權威庫累積總計：", total_stats)
    print("=" * 60)


if __name__ == "__main__":
    main()
