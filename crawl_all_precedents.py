# -*- coding: utf-8 -*-
"""
全量最高法院與行政法院判例本機入庫管線 (Precedent Crawler Pipeline)
===================================================================
功能目標：
1. 全面採集最高法院（民事、刑事）與最高行政法院歷史全量判例。
2. 支援清單自動發現 (Queue Population) 與斷點續傳 (Resume Capability)。
3. 採用禮貌延遲 (0.3 ~ 0.8s) 與隨機 User-Agent，並內建 3 次指數退避重試防護。
4. 本機資料庫儲存於 data/judicial_authority.db 的 precedents 表。
5. 自動掛載與同步 FTS5 全文索引，支援毫秒級法條與關鍵字檢索。
"""

import os
import sys
import time
import random
import re
import sqlite3
import argparse
import urllib.parse
import ssl
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

# 設置標準輸出編碼為 UTF-8，防止 Windows OEM 編碼 (cp950) 報錯
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
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

# 路徑設定
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DB_PATH = PROJECT_ROOT / "data" / "judicial_authority.db"

# 司法院 FINT 系統端點
FINT_BASE_URL = "https://legal.judicial.gov.tw/FINT/"
QRY_ENTRY_URL = "https://legal.judicial.gov.tw/FINT/qryresult.aspx?ty=J1"

# 隨機輪替之合法瀏覽器 User-Agent
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
]


class PrecedentCrawlerPipeline:
    def __init__(self, db_path: Optional[Path] = None, delay_min: float = 0.3, delay_max: float = 0.8):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.session = requests.Session() if requests else None
        self._init_db()

    def _get_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive"
        }
        if referer:
            headers["Referer"] = referer
        else:
            headers["Referer"] = FINT_BASE_URL
        return headers

    def _http_get(self, url: str, referer: Optional[str] = None, max_retries: int = 3) -> str:
        """帶重試機制的 HTTP GET 請求"""
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                headers = self._get_headers(referer)
                if self.session:
                    import urllib3
                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                    resp = self.session.get(url, headers=headers, timeout=20, verify=False)
                    if resp.status_code == 200:
                        return resp.text
                    elif resp.status_code in (500, 502, 503, 504, 429):
                        wait_sec = attempt * 2 + random.uniform(0.5, 1.5)
                        time.sleep(wait_sec)
                        continue
                    else:
                        resp.raise_for_status()
                else:
                    import urllib.request
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                        return resp.read().decode("utf-8", errors="ignore")
            except Exception as e:
                last_error = e
                time.sleep(attempt * 1.5 + random.uniform(0.2, 0.5))
        raise RuntimeError(f"連線失敗 (超過 {max_retries} 次重試): {url}，原因: {last_error}")

    def _polite_sleep(self):
        """動態禮貌延遲"""
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self):
        """初始化資料庫綱要與 FTS5 檢索表"""
        with self._get_conn() as conn:
            # 1. 判例核心表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS precedents (
                    precedent_id TEXT PRIMARY KEY,
                    sys_type TEXT,
                    date TEXT,
                    holding TEXT,
                    full_text TEXT,
                    laws_cited TEXT,
                    status TEXT,
                    abolition_note TEXT,
                    source_url TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_sys ON precedents(sys_type);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_date ON precedents(date);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_status ON precedents(status);")

            # 2. 爬取隊列與斷點續傳表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS precedent_crawl_queue (
                    detail_url TEXT PRIMARY KEY,
                    sys_type TEXT,
                    is_crawled INTEGER DEFAULT 0
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_crawled ON precedent_crawl_queue(is_crawled);")

            # 3. FTS5 全文檢索虛擬表
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS precedents_fts USING fts5(
                    precedent_id,
                    holding,
                    full_text,
                    laws_cited,
                    content='precedents',
                    content_rowid='rowid'
                );
            """)
            conn.commit()

    # =========================================================================
    # 隊列自動發現 (Queue Population)
    # =========================================================================
    def populate_crawl_queue(self, force_refresh: bool = False) -> int:
        """
        遍歷司法院 FINT 系統之全量判例清單（包含停止適用判例、未停止適用之歷史判例池及大法庭裁定），
        自動穿透單一查詢 500 筆上限，採集 data.aspx 連結並裝入 precedent_crawl_queue。
        """
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM precedent_crawl_queue;")
            existing_count = cur.fetchone()[0]

            if existing_count > 0 and not force_refresh:
                print(f"[*] 檢測到隊列表已存在 {existing_count} 筆任務，跳過清單遍歷，直接進入斷點續傳。")
                return existing_count

            if force_refresh:
                print("[!] 強制更新隊列：正在清空舊隊列...")
                cur.execute("DELETE FROM precedent_crawl_queue;")
                conn.commit()

        print(f"[*] 正在連線司法院 FINT 查詢入口: {QRY_ENTRY_URL} ...")
        entry_html = self._http_get(QRY_ENTRY_URL)
        if not BeautifulSoup:
            raise ImportError("需要 bs4 (BeautifulSoup) 模組，請安裝: pip install beautifulsoup4")

        soup = BeautifulSoup(entry_html, "html.parser")
        
        # 尋找 query hash 參數 (q=...)
        q_hash = None
        for a in soup.find_all("a", href=True):
            m = re.search(r'qryresultlst\.aspx\?[^"]*q=([a-f0-9]+)', a["href"], re.I)
            if m:
                q_hash = m.group(1)
                break

        if not q_hash:
            m_q = re.search(r'q=([a-f0-9]{32})', entry_html)
            if m_q:
                q_hash = m_q.group(1)

        if not q_hash:
            raise RuntimeError("無法從 FINT 入口頁面解析查詢識別碼 (q-hash)！")

        print(f"[+] 成功獲取查詢會話識別碼 (q): {q_hash}")

        # =========================================================================
        # 構建全量判例掃描任務矩陣（突破單一查詢 500 筆/25 頁上限）
        # (說明, ty 查詢類型, gc 分類代碼, sort 排序方式, 是否僅過濾「判例」字樣)
        # =========================================================================
        scan_matrix = [
            # --- 1. 停止適用之全量判例池（ty=J1，官方標定停止適用或不再援用，雙向DS/DB穿透500筆上限） ---
            ("停止適用判例-全量不限類別(DS降冪)", "J1", None, "DS", False),
            ("停止適用判例-全量不限類別(DB升冪)", "J1", None, "DB", False),
            ("停止適用判例-民事A編號(DS降冪)", "J1", "A", "DS", False),
            ("停止適用判例-民事A編號(DB升冪)", "J1", "A", "DB", False),
            ("停止適用判例-刑事B編號(DS降冪)", "J1", "B", "DS", False),
            ("停止適用判例-刑事B編號(DB升冪)", "J1", "B", "DB", False),
            ("停止適用判例-家事UA編號(DS降冪)", "J1", "UA", "DS", False),
            ("停止適用判例-家事UA編號(DB升冪)", "J1", "UA", "DB", False),
            ("停止適用判例-行政E編號(DS降冪)", "J1", "E", "DS", False),
            ("停止適用判例-行政E編號(DB升冪)", "J1", "E", "DB", False),

            # --- 2. 未停止適用（現行有效）之歷史判例池（ty=J，民國16年起最高法院及行政法院各庭） ---
            ("未停止適用-最高法院民事判例池(C升冪-早年判例優先)", "J", "C", "DB", True),
            ("未停止適用-最高法院民事判例池(C降冪-近年判例優先)", "J", "C", "DS", True),
            ("未停止適用-最高法院刑事判例池(D升冪-早年判例優先)", "J", "D", "DB", True),
            ("未停止適用-最高法院刑事判例池(D降冪-近年判例優先)", "J", "D", "DS", True),
            ("未停止適用-最高行政法院判例池(F升冪-早年判例優先)", "J", "F", "DB", True),
            ("未停止適用-最高行政法院判例池(F降冪-近年判例優先)", "J", "F", "DS", True),
            ("未停止適用-最高法院家事判例池(UC升冪-早年判例優先)", "J", "UC", "DB", True),
            ("未停止適用-最高法院家事判例池(UC降冪-近年判例優先)", "J", "UC", "DS", True),

            # --- 3. 司法院大法庭專區（ty=J2，具備統一法見解最高效力裁定） ---
            ("司法院大法庭專區裁定(J2全量)", "J2", None, "DS", False),
        ]

        total_added = 0
        batch_queue = []

        for task_idx, (task_name, ty, gc, sort_order, filter_prec) in enumerate(scan_matrix, 1):
            if gc:
                base_query_url = f"{FINT_BASE_URL}qryresultlst.aspx?ty={ty}&q={q_hash}&sort={sort_order}&gy=code&gc={gc}"
            else:
                base_query_url = f"{FINT_BASE_URL}qryresultlst.aspx?ty={ty}&q={q_hash}&sort={sort_order}"

            first_page_url = f"{base_query_url}&page=1"
            try:
                first_html = self._http_get(first_page_url, referer=QRY_ENTRY_URL)
                first_soup = BeautifulSoup(first_html, "html.parser")

                # 解析最末頁
                cat_pages = 1
                for a in first_soup.find_all("a", href=True):
                    if "最末頁" in a.text or "last" in a.text.lower():
                        m_p = re.search(r'page=([0-9]+)', a["href"], re.I)
                        if m_p:
                            cat_pages = int(m_p.group(1))
                            break

                # FINT 系統單一檢索上限為 25 頁 (500 筆)
                scan_pages = min(cat_pages, 25)
                task_precedents_count = 0

                print(f"[{task_idx}/{len(scan_matrix)}] 正在掃描【{task_name}】: 檢測到 {cat_pages} 頁，排程掃描 {scan_pages} 頁 ...")

                for p in range(1, scan_pages + 1):
                    if p == 1:
                        p_soup = first_soup
                    else:
                        p_url = f"{base_query_url}&page={p}"
                        p_html = self._http_get(p_url, referer=first_page_url)
                        p_soup = BeautifulSoup(p_html, "html.parser")

                    data_links = p_soup.find_all("a", href=lambda h: h and "data.aspx" in h)
                    if not data_links:
                        break

                    for a_el in data_links:
                        rel_url = a_el["href"].strip()
                        abs_url = urllib.parse.urljoin(FINT_BASE_URL, rel_url)
                        link_txt = a_el.text.strip()

                        # 若需過濾，檢查標題是否含「判例」或 URL 是否為判例編號 (A, B, E, UA)
                        if filter_prec:
                            is_prec = ("判例" in link_txt) or any(prefix in rel_url for prefix in [
                                "id=A%2c", "id=B%2c", "id=E%2c", "id=UA%2c",
                                "id=A,", "id=B,", "id=E,", "id=UA,"
                            ])
                            if not is_prec:
                                continue

                        # 判定領域 (民事 / 刑事 / 行政 / 家事)
                        if "刑事" in link_txt or gc in ("B", "D"):
                            sys_type = "刑事"
                        elif "行政" in link_txt or "判字" in link_txt or gc in ("E", "F"):
                            sys_type = "行政"
                        elif "家事" in link_txt or gc in ("UA", "UC"):
                            sys_type = "家事"
                        else:
                            sys_type = "民事"

                        batch_queue.append((abs_url, sys_type, 0))
                        task_precedents_count += 1

                    if len(batch_queue) >= 50 or p == scan_pages:
                        with self._get_conn() as conn:
                            conn.executemany("""
                                INSERT OR IGNORE INTO precedent_crawl_queue (detail_url, sys_type, is_crawled)
                                VALUES (?, ?, ?);
                            """, batch_queue)
                            conn.commit()
                        total_added += len(batch_queue)
                        batch_queue.clear()

                    self._polite_sleep()

                print(f"  [✓] 【{task_name}】掃描完畢，提取 {task_precedents_count} 筆判例連結。")

            except Exception as pe:
                print(f"  [!] 【{task_name}】掃描略過或錯誤: {pe}")
                time.sleep(1.0)

        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM precedent_crawl_queue;")
            final_queue_cnt = cur.fetchone()[0]
            cur.execute("SELECT sys_type, COUNT(*) FROM precedent_crawl_queue GROUP BY sys_type;")
            sys_breakdown = {r[0]: r[1] for r in cur.fetchall()}

        print("\n" + "=" * 60)
        print(f"🎉 全量判例清單填裝完成！隊列中共有 {final_queue_cnt} 筆待採集判例任務。")
        print(f"📊 隊列審判系統分佈: {sys_breakdown}")
        print("=" * 60 + "\n")
        return final_queue_cnt

    # =========================================================================
    # 單筆詳細內頁剖析 (Detail Parser)
    # =========================================================================

    def parse_precedent_detail(self, html: str, url: str, fallback_sys_type: str = "民事") -> Optional[Dict[str, Any]]:
        """從 data.aspx 解析出所有標準化欄位"""
        if not BeautifulSoup:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # 1. 裁判字號與案號
        title_el = soup.find(class_="itemtitle")
        raw_title = title_el.text.strip() if title_el else ""
        raw_title = re.sub(r'^(停|不再援用)\s*', '', raw_title).strip()
        clean_title = re.sub(r'\s+', ' ', raw_title)

        # 提取 precedent_id 如 "48年台上字第481號"、"20年上字第1234號"
        m_case = re.search(r'([0-9]{1,3}\s*年\s*[^\s0-9]{1,10}\s*字第\s*[0-9\-]+\s*號)', clean_title)
        if m_case:
            precedent_id = re.sub(r'\s+', '', m_case.group(1))
        else:
            precedent_id = clean_title.replace("最高法院", "").replace("行政法院", "").strip()

        if not precedent_id:
            return None

        # 2. 系統類別 sys_type (民事 / 刑事 / 行政)
        if "民事" in clean_title:
            sys_type = "民事"
        elif "刑事" in clean_title:
            sys_type = "刑事"
        elif "行政" in clean_title or "判字" in clean_title:
            sys_type = "行政"
        else:
            sys_type = fallback_sys_type

        # 3. 裁判日期 date
        date_str = ""
        for r in soup.find_all("div", class_="row"):
            if "裁判日期" in r.text:
                m_date = re.search(r'裁判日期[：:\s]*(民國\s*[0-9]{1,3}\s*年(?:\s*[0-9]{1,2}\s*月(?:\s*[0-9]{1,2}\s*日)?)?)', r.text)
                if m_date:
                    date_str = re.sub(r'\s+', '', m_date.group(1))
                else:
                    date_str = r.text.replace("裁判日期：", "").strip()
                break

        # 4. 判例要旨 holding
        holding_div = soup.find("div", id="plJData")
        holding = ""
        if holding_div:
            holding = holding_div.text.strip()
            holding = re.sub(r'^裁判要旨[：:\s]*', '', holding).strip()

        # 5. 裁判全文 / 理由 full_text
        full_div = soup.find("div", id="plFull")
        full_text = ""
        if full_div:
            full_text = full_div.text.strip()
            full_text = re.sub(r'^裁判全文[：:\s]*', '', full_text).strip()

        # 6. 相關法條 laws_cited
        laws_panel = soup.find("div", class_="panel-body")
        laws_cited = ""
        if laws_panel:
            laws_cited = re.sub(r'\s+', ' ', laws_panel.text).strip()

        # 7. 狀態 status & 加註廢止說明 abolition_note
        lbl_fei = soup.find("span", id="lblJFei")
        fei_text = lbl_fei.text.strip() if lbl_fei else ""
        note_div = soup.find("div", id="plNote")
        note_text = ""
        if note_div:
            note_text = note_div.text.strip()
            note_text = re.sub(r'^編\s*註[：:\s]*', '', note_text).strip()

        if "停" in fei_text or "停止適用" in note_text:
            status = "停止適用"
        elif "不再援用" in fei_text or "不再援用" in note_text:
            status = "不再援用"
        else:
            status = "未停止適用"

        return {
            "precedent_id": precedent_id,
            "sys_type": sys_type,
            "date": date_str,
            "holding": holding,
            "full_text": full_text,
            "laws_cited": laws_cited,
            "status": status,
            "abolition_note": note_text,
            "source_url": url
        }

    # =========================================================================
    # 核心工作迴圈 (Crawler Execution Loop)
    # =========================================================================
    def run_crawler(self, limit: Optional[int] = None) -> int:
        """
        執行斷點續傳採集作業。
        若指定 limit，採集達到指定數量後平順停止。
        """
        # 1. 確保隊列已填充
        self.populate_crawl_queue(force_refresh=False)

        # 2. 獲取待抓取項目
        with self._get_conn() as conn:
            cur = conn.cursor()
            query = "SELECT detail_url, sys_type FROM precedent_crawl_queue WHERE is_crawled = 0"
            if limit:
                query += f" LIMIT {int(limit)}"
            cur.execute(query)
            pending_items = cur.fetchall()

            cur.execute("SELECT COUNT(*) FROM precedent_crawl_queue WHERE is_crawled = 1;")
            already_done = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM precedent_crawl_queue;")
            total_queue = cur.fetchone()[0]

        print(f"[*] 啟動採集引擎：當前進度 {already_done}/{total_queue} (本次待採集: {len(pending_items)} 筆)")

        crawled_count = 0
        batch_records = []
        batch_done_urls = []

        for idx, row in enumerate(pending_items, 1):
            url = row["detail_url"]
            sys_type = row["sys_type"]

            try:
                html = self._http_get(url)
                rec = self.parse_precedent_detail(html, url, fallback_sys_type=sys_type)

                if rec and rec.get("precedent_id"):
                    batch_records.append(rec)
                    batch_done_urls.append(url)
                    crawled_count += 1
                    status_badge = rec.get("status", "未停止適用")
                    print(f"  [{already_done + crawled_count}/{total_queue}] 成功入庫: 【{rec['precedent_id']}】({rec['sys_type']}) - {status_badge}")
                else:
                    # 標記為已處理避免反覆卡死
                    batch_done_urls.append(url)

                # 每 10 筆或最後一筆批次提交
                if len(batch_records) >= 10 or idx == len(pending_items):
                    self._commit_batch(batch_records, batch_done_urls)
                    batch_records.clear()
                    batch_done_urls.clear()

                self._polite_sleep()

            except Exception as e:
                print(f"  [!] 採集失敗 {url}: {e}")
                time.sleep(1.0)

        # 3. 採集完畢後自動重建/更新 FTS5 全文索引
        print("[*] 正在同步/重建 FTS5 全文檢索索引...")
        self.rebuild_fts_index()

        print(f"[✓] 本次採集作業順利完成！新增入庫 {crawled_count} 筆判例。")
        return crawled_count

    def _commit_batch(self, records: List[Dict[str, Any]], done_urls: List[str]):
        """將批次結果寫入 SQLite 並更新隊列"""
        if not records and not done_urls:
            return

        with self._get_conn() as conn:
            # 寫入 precedents 表
            for r in records:
                conn.execute("""
                    INSERT OR REPLACE INTO precedents (
                        precedent_id, sys_type, date, holding, full_text, laws_cited, status, abolition_note, source_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    r["precedent_id"],
                    r["sys_type"],
                    r["date"],
                    r["holding"],
                    r["full_text"],
                    r["laws_cited"],
                    r["status"],
                    r["abolition_note"],
                    r["source_url"]
                ))

            # 標記隊列已抓取
            for u in done_urls:
                conn.execute("UPDATE precedent_crawl_queue SET is_crawled = 1 WHERE detail_url = ?;", (u,))

            conn.commit()

    # =========================================================================
    # FTS5 全文檢索索引重構
    # =========================================================================
    def rebuild_fts_index(self):
        """重建 FTS5 虛擬表以支援毫秒級檢索"""
        with self._get_conn() as conn:
            # 使用 FTS5 external content 表官方標準指令 rebuild
            try:
                conn.execute("INSERT INTO precedents_fts(precedents_fts) VALUES('rebuild');")
            except Exception:
                conn.execute("DROP TABLE IF EXISTS precedents_fts;")
                conn.execute("""
                    CREATE VIRTUAL TABLE precedents_fts USING fts5(
                        precedent_id,
                        holding,
                        full_text,
                        laws_cited,
                        content='precedents',
                        content_rowid='rowid'
                    );
                """)
                conn.execute("INSERT INTO precedents_fts(precedents_fts) VALUES('rebuild');")
            conn.commit()

    # =========================================================================
    # 狀態統計與診斷
    # =========================================================================
    def get_status_report(self) -> Dict[str, Any]:
        """產出當前資料庫與隊列統計報表"""
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM precedent_crawl_queue;")
            total_queue = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM precedent_crawl_queue WHERE is_crawled = 1;")
            crawled_queue = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM precedents;")
            total_precedents = cur.fetchone()[0]

            # 依類別統計
            cur.execute("SELECT sys_type, COUNT(*) FROM precedents GROUP BY sys_type;")
            by_sys = {row[0]: row[1] for row in cur.fetchall()}

            # 依狀態統計
            cur.execute("SELECT status, COUNT(*) FROM precedents GROUP BY status;")
            by_status = {row[0]: row[1] for row in cur.fetchall()}

            # 抽樣最新 2 筆
            cur.execute("SELECT precedent_id, sys_type, date, status, holding, laws_cited FROM precedents ORDER BY rowid DESC LIMIT 2;")
            samples = [dict(row) for row in cur.fetchall()]

        return {
            "total_queue": total_queue,
            "crawled_queue": crawled_queue,
            "pending_queue": total_queue - crawled_queue,
            "total_precedents": total_precedents,
            "by_sys_type": by_sys,
            "by_status": by_status,
            "samples": samples
        }


def main():
    parser = argparse.ArgumentParser(description="司法院全量最高法院與行政法院判例採集管線")
    parser.add_argument("--limit", type=int, default=None, help="限制本次採集筆數（如 200 筆驗證）")
    parser.add_argument("--populate-only", action="store_true", help="僅執行隊列掃描與填裝，不抓取內頁")
    parser.add_argument("--force-refresh", action="store_true", help="強制重新掃描並覆寫排隊清單")
    parser.add_argument("--status", action="store_true", help="顯示目前資料庫與隊列狀態報表")
    parser.add_argument("--rebuild-fts", action="store_true", help="重新建置 FTS5 全文索引")

    args = parser.parse_args()

    pipeline = PrecedentCrawlerPipeline()

    if args.status:
        st = pipeline.get_status_report()
        print("\n" + "=" * 60)
        print("📊 司法判例本機入庫管線狀態報表")
        print("=" * 60)
        print(f"• 隊列總數: {st['total_queue']} 筆 | 已採集: {st['crawled_queue']} 筆 | 待採集: {st['pending_queue']} 筆")
        print(f"• 已入庫判例總數: {st['total_precedents']} 筆")
        print(f"• 依審判系統分佈: {st['by_sys_type']}")
        print(f"• 依適用狀態分佈: {st['by_status']}")
        if st["samples"]:
            print("\n📋 入庫判例欄位內容抽樣：")
            for idx, s in enumerate(st["samples"], 1):
                print(f"[{idx}] 【{s['precedent_id']}】({s['sys_type']}) ｜ 日期: {s['date']} ｜ 狀態: {s['status']}")
                print(f"    相關法條: {s['laws_cited']}")
                print(f"    要旨摘錄: {s['holding'][:80]}...\n")
        print("=" * 60)
        return

    if args.rebuild_fts:
        print("[*] 正在手動重構 FTS5 全文檢索索引...")
        pipeline.rebuild_fts_index()
        print("[✓] FTS5 索引重構完成！")
        return

    if args.populate_only:
        pipeline.populate_crawl_queue(force_refresh=args.force_refresh)
        return

    # 執行採集（支援 limit）
    pipeline.run_crawler(limit=args.limit)


if __name__ == "__main__":
    main()
