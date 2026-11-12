"""
百萬級裁判書 SQLite FTS5 全文檢索資料庫引擎 (Million Judgments DB Engine)
支援：
1. 主索引層 (judicial_1m_index.db) / 考試核心子庫 (judicial_exam_core.db) / 遠端本地橋接 (LOCAL_DB_API_URL)
   - 全表 RO URI 唯讀查詢 + B-Tree 複合索引 (idx_meta_ywn, idx_meta_court_type) + FTS5 全文檢索
   - 預設 Index-Only 入庫架構（不再強制寫入 25GB+ shards 全文分片；若有歷史分片則相容讀取）
2. 管線 A：--ingest-inbox 掃描 opendata_inbox 資料夾批次解壓入庫
3. 管線 B：--download-opendata 串接司法院資料開放平臺 API 自動下載各月裁判包
4. 管線 C：--migrate-local 一鍵遷移本機既有真實判決、大法庭、憲判字、原判例、決議與座談會
5. 管線 D：--prune [--commit] 非訟程序與純事實案件清理（具實體法學爭點白名單保護）
"""
import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
import gzip
import json
import re
import glob
import zlib
import sqlite3
import zipfile
import tempfile
import subprocess
import shutil
import argparse
import logging
import time
import urllib.error
import urllib.request
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

try:
    from config import (
        DATA_DIR, RAW_DATA_DIR, STANDARDS_DIR, CONSTITUTIONAL_DIR,
        TRAINING_DATA_DIR, GOOGLE_DRIVE_DATA_DIR
    )
    try:
        from config import JUDICIAL_1M_DIR, OPENDATA_INBOX_DIR
    except ImportError:
        JUDICIAL_1M_DIR = DATA_DIR / "judicial_1m_db"
        OPENDATA_INBOX_DIR = DATA_DIR / "opendata_inbox"
    try:
        from config import safe_requests_get
    except ImportError:
        safe_requests_get = None
except ImportError:
    BASE_DIR = Path(__file__).resolve().parent
    DATA_DIR = BASE_DIR / "data" if (BASE_DIR / "data").exists() else BASE_DIR
    RAW_DATA_DIR = DATA_DIR / "raw_exams"
    STANDARDS_DIR = DATA_DIR / "scoring_standards"
    CONSTITUTIONAL_DIR = DATA_DIR / "constitutional_cases"
    TRAINING_DATA_DIR = DATA_DIR / "training_data"
    JUDICIAL_1M_DIR = DATA_DIR / "judicial_1m_db"
    OPENDATA_INBOX_DIR = DATA_DIR / "opendata_inbox"
    GOOGLE_DRIVE_DATA_DIR = str(DATA_DIR)
    safe_requests_get = None


class ClosingConnection(sqlite3.Connection):
    """
    自定義 SQLite 連線物件，在 with 區塊離開時強制呼叫 close()，
    立即釋放 Windows / Google Drive 虛擬檔案系統底層的 OS 檔案鎖。
    """
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


class MillionJudgmentsSQLiteEngine:
    """
    797 萬+ 筆真實裁判書雙軌高效檢索引擎：
    1. 本機全量母庫 (judicial_1m_index.db) 或 雲端核心精華子庫 (judicial_exam_core.db)
    2. 選用遠端橋接 API (LOCAL_DB_API_URL) 供雲端即時穿透查詢本機全量母庫
    """

    @staticmethod
    def _unpack_gz_if_needed(db_path: Path) -> Optional[Path]:
        """若存在壓縮版 .db.gz 且尚未解壓，自動快速解壓至目標路徑或 /tmp。"""
        if db_path.exists():
            return db_path
        gz_path = Path(str(db_path) + ".gz")
        if not gz_path.exists():
            return None
        targets = [db_path, Path(tempfile.gettempdir()) / db_path.name]
        for tgt in targets:
            try:
                if tgt.exists() and tgt.stat().st_size > 10000:
                    return tgt
                tgt.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(gz_path, "rb") as f_in, open(tgt, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
                return tgt
            except Exception:
                continue
        return None

    @staticmethod
    def is_valid_db(db_path: Path) -> bool:
        """
        以唯讀 URI 驗證 SQLite 資料庫檔案是否真實存在、具備有效 SQLite 3 Header 且非未水合幽靈檔。
        """
        if not db_path:
            return False
        try:
            p = Path(db_path)
            if not p.exists() or p.stat().st_size == 0:
                return False
            with open(p, "rb") as f:
                if f.read(16) != b"SQLite format 3\x00":
                    return False
            uri = f"file:///{p.resolve().as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=5, factory=ClosingConnection) as test_conn:
                test_conn.execute("PRAGMA schema_version;").fetchone()
            return True
        except Exception:
            return False

    def __init__(self, base_dir: Path = None, inbox_dir: Path = None, remote_api_url: str = ""):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            candidates = [
                Path(JUDICIAL_1M_DIR),
                Path(DATA_DIR) / "judicial_1m_db",
                Path(DATA_DIR) / "data" / "judicial_1m_db",
                Path(__file__).resolve().parent / "data" / "judicial_1m_db",
                Path(__file__).resolve().parent.parent / "data" / "judicial_1m_db"
            ]
            matched = next((p for p in candidates if p.exists() or p.parent.exists()), None)
            self.base_dir = matched if matched else Path(JUDICIAL_1M_DIR)

        self.shards_dir = self.base_dir / "shards"
        self.remote_api_url = (remote_api_url or os.environ.get("LOCAL_DB_API_URL", "")).strip().rstrip("/")
        self._meta_table = "judgments_meta"
        self._fts_table = "judgments_fts"
        self._has_redirects_table = True
        self._has_manifest_table = False
        self._table_cols: set = set()

        master_candidates = [
            self.base_dir / "judicial_1m_index.db",
            Path(DATA_DIR) / "judicial_1m_db" / "judicial_1m_index.db",
            Path("D:/LawExamData/judicial_1m_db/judicial_1m_index.db"),
            Path("C:/LawExamData/judicial_1m_db/judicial_1m_index.db"),
            Path("G:/我的雲端硬碟/LawExamData/data/judicial_1m_db/judicial_1m_index.db"),
            Path(__file__).resolve().parent / "data" / "judicial_1m_db" / "judicial_1m_index.db"
        ]
        core_candidates = [
            Path(DATA_DIR) / "judicial_exam_core.db",
            Path(__file__).resolve().parent / "data" / "judicial_exam_core.db",
            Path(__file__).resolve().parent / "judicial_exam_core.db",
            self.base_dir / "judicial_exam_core.db",
            Path(tempfile.gettempdir()) / "judicial_exam_core.db",
            Path("G:/我的雲端硬碟/LawExamData/data/judicial_exam_core.db"),
        ]
        for cc in list(core_candidates):
            self._unpack_gz_if_needed(cc)

        found_master = next((p for p in master_candidates if p.exists() and self.is_valid_db(p)), None)
        found_core = next((p for p in core_candidates if p.exists() and self.is_valid_db(p)), None)

        if found_master:
            self.index_db_path = found_master
            self.db_mode = "master"
            self.db_title = "🏛️ 百萬裁判全量母庫 (7,975,000+ 筆索引)"
        elif found_core:
            self.index_db_path = found_core
            self.db_mode = "core"
            self.db_title = "⚖️ 司律核心精華子庫 (國考精選版)"
        elif self.remote_api_url:
            self.index_db_path = self.base_dir / "judicial_1m_index.db"
            self.db_mode = "remote"
            self.db_title = "🌐 本機百萬裁判遠端即時橋接"
        else:
            self.index_db_path = self.base_dir / "judicial_1m_index.db"
            self.db_mode = "empty"
            self.db_title = "📂 裁判資料庫 (初始化中)"

        if inbox_dir:
            self.inbox_dir = Path(inbox_dir)
        else:
            inbox_cands = [
                Path(OPENDATA_INBOX_DIR),
                Path(DATA_DIR) / "opendata_inbox",
                Path(__file__).resolve().parent / "opendata_inbox",
                Path(__file__).resolve().parent.parent / "opendata_inbox"
            ]
            matched_inbox = next((p for p in inbox_cands if p.exists() or p.parent.exists()), None)
            self.inbox_dir = matched_inbox if matched_inbox else Path(OPENDATA_INBOX_DIR)

        if self.db_mode in ("master", "core"):
            self._detect_schema_tables()
            self._index_db_initialized = True
        elif self.db_mode == "empty":
            try:
                self.base_dir.mkdir(parents=True, exist_ok=True)
                self.inbox_dir.mkdir(parents=True, exist_ok=True)
                self._init_index_db()
            except Exception as e:
                print(f"[MillionJudgmentsDB Init Warning] {e}")

    def is_available(self) -> bool:
        return bool(self.remote_api_url or (self.index_db_path and self.index_db_path.exists() and self.db_mode in ("master", "core")))

    def _get_ro_conn(self, db_path: Path) -> sqlite3.Connection:
        """零鎖定唯讀連線，絕對不觸發檔案刪除、更名或 WAL/TRUNCATE 寫鎖。"""
        uri = f"file:///{Path(db_path).resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=60, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=60000;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA cache_size=-65536;")
        return conn

    def _detect_schema_tables(self):
        """自動辨識 master (judgments_meta) 與 core (judgments_meta / exam_judgments_meta) 資料表名稱。"""
        if not self.index_db_path or not self.index_db_path.exists():
            return
        try:
            with self._get_ro_conn(self.index_db_path) as conn:
                objs = {
                    r[0] for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                    ).fetchall()
                }
                self._meta_table = "judgments_meta" if "judgments_meta" in objs else (
                    "exam_judgments_meta" if "exam_judgments_meta" in objs else "judgments_meta"
                )
                self._fts_table = "judgments_fts" if "judgments_fts" in objs else (
                    "exam_judgments_fts" if "exam_judgments_fts" in objs else "judgments_fts"
                )
                self._has_redirects_table = "judgment_redirects" in objs
                self._has_manifest_table = "core_manifest" in objs
                cols = conn.execute(f"PRAGMA table_info({self._meta_table})").fetchall()
                self._table_cols = {c[1] for c in cols}
        except Exception:
            pass

    @staticmethod
    def _get_remote_auth_token() -> str:
        for env_key in ("DB_BRIDGE_TOKEN", "LOCAL_DB_API_TOKEN"):
            val = os.getenv(env_key, "").strip()
            if val:
                return val
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                for sec_key in ("DB_BRIDGE_TOKEN", "LOCAL_DB_API_TOKEN"):
                    if sec_key in st.secrets:
                        val = str(st.secrets[sec_key]).strip()
                        if val:
                            return val
        except Exception:
            pass
        return ""

    def _remote_get_json(self, endpoint: str, params: Optional[Dict[str, Any]] = None, timeout: float = 4.0) -> Optional[Any]:
        if not self.remote_api_url:
            return None
        qs = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{self.remote_api_url}{endpoint}{qs}"
        headers = {"Accept": "application/json", "User-Agent": "LawExamEvaluator/1.0"}
        token = self._get_remote_auth_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8", errors="ignore"))
                logger.warning("Remote DB API %s returned HTTP %s", endpoint, resp.status)
        except urllib.error.HTTPError as exc:
            logger.warning("Remote DB API HTTP error on %s: %s %s", endpoint, exc.code, exc.reason)
        except Exception as exc:
            logger.debug("Remote DB API request failed on %s: %s", endpoint, exc)
        return None

    def _get_conn(self, db_path: Path) -> sqlite3.Connection:
        max_connect_retries = 5
        conn = None
        for c_attempt in range(max_connect_retries):
            try:
                if db_path.exists():
                    sz = db_path.stat().st_size
                    # 嚴格安全防護：絕不因瞬態異常自動更名或刪除超過 50MB 之既有大庫
                    if sz < 50_000_000 and (sz == 0 or not self.is_valid_db(db_path)):
                        corrupted_bak = db_path.with_name(f"{db_path.name}.corrupted_{int(time.time())}.bak")
                        print(f"[!] 偵測到無效或損壞之資料庫: {db_path}，自動隔離至 {corrupted_bak.name} 並重新初始化...")
                        try:
                            db_path.rename(corrupted_bak)
                        except Exception:
                            try:
                                db_path.unlink()
                            except Exception:
                                pass
                conn = sqlite3.connect(str(db_path), timeout=120, factory=ClosingConnection)
                break
            except (sqlite3.OperationalError, sqlite3.DatabaseError) as oe:
                err_msg = str(oe).lower()
                if ("file is not a database" in err_msg or "malformed" in err_msg) and (not db_path.exists() or db_path.stat().st_size < 50_000_000):
                    corrupted_bak = db_path.with_name(f"{db_path.name}.corrupted_{int(time.time())}.bak")
                    print(f"[!] SQLite 資料庫損壞 ({oe}): {db_path}，自動隔離至 {corrupted_bak.name} 並重新建立...")
                    try:
                        if conn:
                            conn.close()
                    except Exception:
                        pass
                    try:
                        if db_path.exists():
                            db_path.rename(corrupted_bak)
                    except Exception:
                        pass
                    conn = sqlite3.connect(str(db_path), timeout=120, factory=ClosingConnection)
                    break
                elif ("disk i/o" in err_msg or "locked" in err_msg or "busy" in err_msg) and c_attempt < max_connect_retries - 1:
                    time.sleep((c_attempt + 1) * 1.5)
                else:
                    raise

        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=120000;")

        path_str = str(db_path).replace(chr(92), "/")
        is_cloud_sync = any(k in path_str for k in ["我的雲端硬碟", "Google Drive", "G:/", "g:/", "OneDrive"])

        try:
            cur_m = conn.execute("PRAGMA journal_mode;").fetchone()
            cur_mode = str(cur_m[0]).lower() if cur_m else ""
            if is_cloud_sync:
                if cur_mode != "truncate":
                    conn.execute("PRAGMA journal_mode=TRUNCATE;")
            else:
                if cur_mode != "wal":
                    conn.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass

        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
        conn.execute("PRAGMA cache_size=-64000;")
        return conn

    def _init_index_db(self, force: bool = False):
        if not force and getattr(self, "_index_db_initialized", False):
            return
        if not force and self.index_db_path.exists():
            if self.is_valid_db(self.index_db_path):
                self._index_db_initialized = True
                return
            else:
                corrupted_bak = self.index_db_path.with_name(f"{self.index_db_path.name}.corrupted_{int(time.time())}.bak")
                print(f"[!] 偵測到損壞或未水合之主索引庫: {self.index_db_path}，自動隔離至 {corrupted_bak.name} 並重建全新主庫...")
                try:
                    self.index_db_path.rename(corrupted_bak)
                except Exception:
                    try:
                        self.index_db_path.unlink()
                    except Exception:
                        pass

        with self._get_conn(self.index_db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS judgments_meta (
                    case_id TEXT PRIMARY KEY,
                    jid TEXT,
                    court TEXT,
                    level TEXT,
                    case_type TEXT,
                    subject TEXT,
                    jud_year TEXT,
                    jud_word TEXT,
                    jud_no TEXT,
                    date TEXT,
                    title TEXT,
                    laws_cited TEXT,
                    issue TEXT,
                    holding_preview TEXT,
                    shard_key TEXT,
                    has_legal_issue INTEGER DEFAULT 1,
                    history_instances TEXT,
                    substantive_prior TEXT DEFAULT '',
                    history_cases TEXT DEFAULT ''
                )
            """)
            try:
                conn.execute("ALTER TABLE judgments_meta ADD COLUMN has_legal_issue INTEGER DEFAULT 1;")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE judgments_meta ADD COLUMN history_instances TEXT;")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE judgments_meta ADD COLUMN substantive_prior TEXT DEFAULT '';")
            except Exception:
                pass
            try:
                conn.execute("ALTER TABLE judgments_meta ADD COLUMN history_cases TEXT DEFAULT '';")
            except Exception:
                pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_ywn ON judgments_meta(jud_year, jud_word, jud_no);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_court_type ON judgments_meta(court, case_type);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_legal_issue ON judgments_meta(has_legal_issue);")
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS judgments_fts USING fts5(
                    case_id UNINDEXED,
                    title,
                    holding_preview,
                    issue,
                    laws_cited,
                    tokenize='unicode61'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS judgment_redirects (
                    dismissed_case_id TEXT PRIMARY KEY,
                    substantive_prior_id TEXT,
                    discard_reason TEXT,
                    court TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_redirect_dismissed ON judgment_redirects(dismissed_case_id);")
            self._index_db_initialized = True

    def _init_shard_db(self, shard_key: str) -> Path:
        self.shards_dir.mkdir(parents=True, exist_ok=True)
        clean_key = re.sub(r"[^0-9a-zA-Z_]", "_", shard_key) or "general"
        shard_path = self.shards_dir / f"judgments_{clean_key}.db"
        if not hasattr(self, "_initialized_shards"):
            self._initialized_shards = set()
        if shard_path in self._initialized_shards and shard_path.exists():
            try:
                if shard_path.stat().st_size > 0:
                    return shard_path
            except Exception:
                pass

        max_init_retries = 5
        for i_attempt in range(max_init_retries):
            try:
                with self._get_conn(shard_path) as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS judgments_blob (
                            case_id TEXT PRIMARY KEY,
                            full_text_zlib BLOB
                        )
                    """)
                break
            except sqlite3.OperationalError as oe:
                err_msg = str(oe).lower()
                if ("disk i/o" in err_msg or "locked" in err_msg or "busy" in err_msg) and i_attempt < max_init_retries - 1:
                    time.sleep((i_attempt + 1) * 1.5)
                else:
                    raise

        self._initialized_shards.add(shard_path)
        return shard_path

    @staticmethod
    def _extract_ywn(case_id: str, jid: str = "", date_str: str = ""):
        jud_year, jud_word, jud_no = "", "", ""
        if jid and "," in jid:
            parts = jid.split(",")
            if len(parts) >= 4:
                jud_year, jud_word, jud_no = parts[1].strip(), parts[2].strip(), parts[3].strip()

        if not jud_year or not jud_no:
            m = re.search(r"(\d{2,3})\s*年(?:度)?\s*([^\d\s]{1,8}?)\s*字\s*第?\s*(\d+)\s*號", case_id)
            if m:
                jud_year, jud_word, jud_no = m.group(1), m.group(2), m.group(3)
            else:
                m_const = re.search(r"(?:釋字第|憲判字第)\s*(\d+)\s*號", case_id)
                if m_const:
                    jud_no = m_const.group(1)
                    jud_word = "憲判" if "憲判" in case_id else "釋字"
                    m_yr = re.search(r"(\d{2,3})年", case_id)
                    jud_year = m_yr.group(1) if m_yr else ""

        shard_key = "general"
        if date_str:
            d_clean = re.sub(r"[^\d]", "", str(date_str))
            if len(d_clean) >= 6:
                shard_key = d_clean[:6]
        elif jud_year:
            shard_key = f"roc_{jud_year}"

        return jud_year, jud_word, jud_no, shard_key


    @staticmethod
    def get_official_url(case_id: str, jid: str = "") -> str:
        """
        生成司法院官方裁判書系統直連穿透連結：
        1. 若帶有標準 JID (如 TPSM,108,台上,1719,20190523,1)，直接進入官方完整裁判內容頁面
        2. 若僅有案號字串，精準導向司法院裁判書查詢系統 qryresultlst 頁面
        """
        if jid and "," in str(jid) and len(str(jid).split(",")) >= 4:
            return f"https://judgment.judicial.gov.tw/FJUD/data.aspx?ty=JD&id={str(jid).strip()}"
        import urllib.parse
        clean_cid = re.sub(r'\(.*?\)|（.*?）', '', str(case_id or "")).strip()
        return f"https://judgment.judicial.gov.tw/FJUD/qryresultlst.aspx?q={urllib.parse.quote(clean_cid)}"

    def get_db_info(self) -> Dict[str, Any]:
        """取得當前資料庫連線類型、收錄總筆數與狀態"""
        cnt = self.get_total_count()
        mode = getattr(self, "db_mode", "master")
        if mode == "master" and cnt > 0:
            title = f"🏛️ 百萬裁判全量母庫 (已收錄 {cnt:,} 筆索引)"
        elif mode == "core" and cnt > 0:
            title = f"⚖️ 司律核心精華子庫 (已收錄 {cnt:,} 筆國考精華)"
        elif mode == "remote" and cnt > 0:
            title = f"🌐 本機百萬裁判遠端橋接 ({cnt:,} 筆實時連動)"
        elif cnt > 0:
            title = f"📚 裁判資料庫 (已收錄 {cnt:,} 筆裁判)"
        else:
            title = "📂 裁判資料庫 (尚未建立或空庫)"
        return {
            "mode": mode,
            "title": title,
            "count": cnt,
            "path": self.remote_api_url if mode == "remote" else str(self.index_db_path),
            "has_shards": bool(self.shards_dir.exists() and any(self.shards_dir.glob("*.db"))),
            "meta_table": self._meta_table,
            "fts_table": self._fts_table,
            "remote_api_url": self.remote_api_url,
        }

    def get_total_count(self, exact: bool = False) -> int:
        now = time.time()
        cached = getattr(self, "_cached_count", None)
        last_t = getattr(self, "_last_count_time", 0)
        if not exact and cached is not None and (now - last_t < 600):
            return cached

        if getattr(self, "db_mode", "") == "remote" and self.remote_api_url:
            stats = self._remote_get_json("/stats")
            if isinstance(stats, dict) and stats.get("count") is not None:
                cnt = int(stats["count"])
                self._cached_count = cnt
                self._last_count_time = now
                return cnt
            return 0

        if not self.index_db_path or not self.index_db_path.exists():
            return 0
        try:
            sz = self.index_db_path.stat().st_size
            with self._get_ro_conn(self.index_db_path) as conn:
                if self._has_manifest_table and not exact:
                    try:
                        mrow = conn.execute("SELECT value FROM core_manifest WHERE key = 'judgments_count' LIMIT 1").fetchone()
                        if mrow and str(mrow[0]).isdigit():
                            cnt = int(mrow[0])
                            self._cached_count = cnt
                            self._last_count_time = now
                            return cnt
                    except Exception:
                        pass

                # 對 500MB 以上大庫（如 16.35GB G:\ 母庫），以 O(log N) MAX(rowid) 避免 COUNT(*) 全表掃描逾時
                if not exact and sz > 500 * 1024 * 1024:
                    row = conn.execute(f"SELECT MAX(rowid) AS cnt FROM {self._meta_table}").fetchone()
                else:
                    row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {self._meta_table}").fetchone()
                cnt = int(row["cnt"] or 0) if row else 0
                self._cached_count = cnt
                self._last_count_time = now
                return cnt
        except Exception:
            return 0

    def get_full_text(self, case_id: str, shard_key: str = "") -> str:
        if not case_id or not self.shards_dir.exists() or not self.index_db_path.exists():
            return ""
        try:
            if not shard_key:
                with self._get_ro_conn(self.index_db_path) as conn:
                    r = conn.execute(
                        f"SELECT shard_key, holding_preview FROM {self._meta_table} WHERE case_id = ?",
                        (case_id,)
                    ).fetchone()
                    if not r:
                        return ""
                    shard_key = r["shard_key"] or "general"

            clean_key = re.sub(r"[^0-9a-zA-Z_]", "_", shard_key) or "general"
            shard_path = self.shards_dir / f"judgments_{clean_key}.db"
            if shard_path.exists():
                with self._get_ro_conn(shard_path) as sconn:
                    brow = sconn.execute("SELECT full_text_zlib FROM judgments_blob WHERE case_id = ?", (case_id,)).fetchone()
                    if brow and brow["full_text_zlib"]:
                        return zlib.decompress(brow["full_text_zlib"]).decode("utf-8", errors="ignore")
        except Exception:
            pass
        return ""

    def batch_upsert_records(self, records: List[Dict[str, Any]], batch_size: int = 5000, write_shards: bool = False) -> int:
        if not records:
            return 0
        self._init_index_db()

        self._cached_count = None
        total_inserted = 0

        for i in range(0, len(records), batch_size):
            chunk = records[i:i + batch_size]
            meta_rows = []
            fts_rows = []
            shard_buckets = {}

            for rec in chunk:
                cid = str(rec.get("case_id", "")).strip()
                if not cid:
                    continue
                jid = str(rec.get("jid", "")).strip()
                court = str(rec.get("court", "")).strip()
                level = str(rec.get("level", "")).strip()
                date_s = str(rec.get("date", "")).strip()
                title = str(rec.get("title", "")).strip()
                subject = str(rec.get("subject", "法學專業實務")).strip()
                laws_list = rec.get("laws_cited", [])
                laws_str = "、".join(laws_list) if isinstance(laws_list, list) else str(laws_list or "")
                issue = str(rec.get("issue", "")).strip()
                holding = str(rec.get("holding", "")).strip()
                full_text = str(rec.get("full_text", "") or holding).strip()
                holding_prev = holding[:500] if holding else full_text[:500]

                full_tag = f"{cid} {level} {court} {title}"
                if "判例" in full_tag:
                    c_type = "原判例"
                elif any(k in full_tag for k in ["決議", "庭長法官聯席會議", "民事庭會議", "刑事庭會議"]):
                    c_type = "最高院/最高行決議"
                elif "座談會" in full_tag:
                    c_type = "高院法律座談會"
                elif any(k in full_tag for k in ["憲判", "釋字", "憲法法庭", "大法官"]):
                    c_type = "憲法裁判/大法官解釋"
                elif "裁定" in full_tag:
                    c_type = "裁定"
                else:
                    c_type = "判決"

                y, w, n, s_key = self._extract_ywn(cid, jid, date_s)

                has_issue_val = rec.get("has_legal_issue")
                hist_inst_val = rec.get("extracted_history_instances") or rec.get("history_instances")
                if has_issue_val is None:
                    from legal_judgment_analyzer import evaluate_judgment_substance
                    sub_res = evaluate_judgment_substance(full_text or holding, title=cid, doc_type=c_type)
                    has_issue_val = 1 if sub_res.get("has_legal_issue", True) else 0
                    if not hist_inst_val:
                        hist_inst_val = sub_res.get("extracted_history_instances", [])
                else:
                    has_issue_val = 1 if has_issue_val else 0

                hist_json_str = json.dumps(hist_inst_val, ensure_ascii=False) if hist_inst_val else ""

                sub_prior_val = rec.get("substantive_prior") or ""
                if not sub_prior_val and rec.get("substantive_prior_instance"):
                    spi = rec.get("substantive_prior_instance")
                    sub_prior_val = spi.get("case_id", "") if isinstance(spi, dict) else str(spi)

                hist_cases_str = rec.get("history_cases_str") or rec.get("history_cases") or ""
                if not hist_cases_str and hist_inst_val:
                    if isinstance(hist_inst_val, list):
                        hist_cases_str = "、".join([x.get("case_id", "") if isinstance(x, dict) else str(x) for x in hist_inst_val if x])
                    else:
                        hist_cases_str = str(hist_inst_val)

                meta_rows.append((cid, jid, court, level, c_type, subject, y, w, n, date_s, title, laws_str, issue, holding_prev, s_key, has_issue_val, hist_json_str, sub_prior_val, hist_cases_str))
                fts_rows.append((cid, title, holding_prev, issue, laws_str))
                if write_shards and full_text:
                    compressed_blob = zlib.compress(full_text.encode("utf-8", errors="ignore"), level=6)
                    shard_buckets.setdefault(s_key, []).append((cid, compressed_blob))

            if not meta_rows:
                continue

            # 寫入主索引庫 (帶防護、零 FTS 全表掃描與重試退避機制)
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    with self._get_conn(self.index_db_path) as conn:
                        cur = conn.cursor()
                        # 1. 快速判定本批次有哪些案號已存在於資料庫（利用 judgments_meta 主鍵索引 O(1) 快速比對）
                        # 徹底避免對 UNINDEXED 的 judgments_fts 全表掃描造成硬碟 I/O 阻塞
                        cids_in_batch = [r[0] for r in fts_rows]
                        existing_in_db = set()
                        if cids_in_batch:
                            for sub_i in range(0, len(cids_in_batch), 500):
                                sub_cids = cids_in_batch[sub_i:sub_i + 500]
                                placeholders = ",".join("?" for _ in sub_cids)
                                cur.execute(f"SELECT case_id FROM judgments_meta WHERE case_id IN ({placeholders})", sub_cids)
                                existing_in_db.update(row[0] for row in cur.fetchall() if row[0])

                        cur.executemany("""
                            INSERT OR REPLACE INTO judgments_meta
                            (case_id, jid, court, level, case_type, subject, jud_year, jud_word, jud_no, date, title, laws_cited, issue, holding_preview, shard_key, has_legal_issue, history_instances, substantive_prior, history_cases)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, meta_rows)

                        # 2. 僅對全新未收錄案號寫入 judgments_fts，徹底杜絕對 UNINDEXED case_id 執行 DELETE 的百萬級全表掃描
                        new_fts_rows = [r for r in fts_rows if r[0] not in existing_in_db]
                        if new_fts_rows:
                            cur.executemany("""
                                INSERT INTO judgments_fts (case_id, title, holding_preview, issue, laws_cited)
                                VALUES (?, ?, ?, ?, ?)
                            """, new_fts_rows)
                        conn.commit()
                    break
                except (sqlite3.OperationalError, sqlite3.DatabaseError) as oe:
                    err_msg = str(oe).lower()
                    if ("disk i/o" in err_msg or "locked" in err_msg or "busy" in err_msg) and attempt < max_retries - 1:
                        backoff = (attempt + 1) * 2.0
                        print(f"[!] 主索引庫寫入遇到暫態異常 ({oe})，等待 {backoff:.1f} 秒後進行第 {attempt + 2}/{max_retries} 次重試...")
                        time.sleep(backoff)
                    elif "file is not a database" in err_msg or "malformed" in err_msg:
                        print(f"[!] 主索引庫損壞 ({oe})，自動觸發自癒修復並重新初始化...")
                        self._init_index_db(force=True)
                        time.sleep(1.0)
                    else:
                        raise

            # 寫入分片本文 BLOB 庫 (亦帶重試保護)
            for s_key, blob_rows in shard_buckets.items():
                for s_attempt in range(max_retries):
                    try:
                        s_path = self._init_shard_db(s_key)
                        with self._get_conn(s_path) as sconn:
                            sconn.executemany("""
                                INSERT OR REPLACE INTO judgments_blob (case_id, full_text_zlib)
                                VALUES (?, ?)
                            """, blob_rows)
                            sconn.commit()
                        break
                    except (sqlite3.OperationalError, sqlite3.DatabaseError) as soe:
                        err_msg = str(soe).lower()
                        if ("disk i/o" in err_msg or "locked" in err_msg or "busy" in err_msg) and s_attempt < max_retries - 1:
                            backoff = (s_attempt + 1) * 2.0
                            print(f"[!] 分片庫 ({s_key}) 寫入遇到暫態異常 ({soe})，等待 {backoff:.1f} 秒重試...")
                            time.sleep(backoff)
                        elif "file is not a database" in err_msg or "malformed" in err_msg:
                            print(f"[!] 分片庫 ({s_key}) 損壞 ({soe})，重新建立該分片...")
                            if hasattr(self, "_initialized_shards"):
                                self._initialized_shards.discard(s_path)
                            self._init_shard_db(s_key)
                            time.sleep(1.0)
                        else:
                            raise

            total_inserted += len(meta_rows)

        if total_inserted > 0 and getattr(self, "db_mode", "empty") == "empty" and self.index_db_path and self.index_db_path.exists():
            self._detect_schema_tables()
            if self._meta_table == "exam_judgments_meta":
                self.db_mode = "core"
                self.db_title = "⚖️ 司律核心精華子庫 (國考精選版)"
            else:
                self.db_mode = "master"
                self.db_title = "🏛️ 百萬裁判全量母庫 (7,975,000+ 筆索引)"

        return total_inserted

    @staticmethod
    def _expand_court_system_filter(court_system: str) -> List[str]:
        if not court_system or "全部法院" in court_system or "全部" == court_system.strip():
            return []
        mapping = {
            "憲法": ["憲法法庭", "司法院大法官", "憲法法庭 / 司法院大法官"],
            "大法官": ["憲法法庭", "司法院大法官", "憲法法庭 / 司法院大法官"],
            "原判例": ["最高法院", "最高行政法院"],
            "決議": ["最高法院", "最高法院民事庭會議", "最高法院刑事庭會議", "最高行政法院", "最高行政法院庭長法官聯席會議"],
            "座談會": ["臺灣高等法院暨所屬法院法律座談會", "臺灣高等法院"],
            "最高法院": ["最高法院", "最高法院民事大法庭", "最高法院刑事大法庭", "最高法院民事庭會議", "最高法院刑事庭會議"],
            "最高行政法院": ["最高行政法院", "最高行政法院庭長法官聯席會議"],
            "高等行政法院": ["臺北高等行政法院", "臺中高等行政法院", "高雄高等行政法院", "臺灣高等行政法院"],
            "高等法院": [
                "臺灣高等法院", "臺灣高等法院臺中分院", "臺灣高等法院臺南分院",
                "臺灣高等法院高雄分院", "臺灣高等法院花蓮分院", "福建高等法院",
                "臺灣高等法院暨所屬法院法律座談會",
            ],
            "智慧財產": ["智慧財產及商業法院", "智慧財產法院"],
            "懲戒": ["懲戒法院", "公務員懲戒委員會"],
        }
        matched = []
        for k, courts in mapping.items():
            if k in court_system:
                for c in courts:
                    if c not in matched:
                        matched.append(c)
        return matched

    @staticmethod
    def _normalize_cited_laws(cited_laws: str) -> str:
        """Collapse spaces within a single statute citation without fusing adjacent citations."""
        cleaned = (cited_laws or "").replace("\x00", "").strip()
        if not cleaned:
            return ""
        # Merge "民法 第 184 條" -> "民法第184條", while keeping spaces between "民法第184條 刑法第271條"
        cleaned = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=第\s*[\d一二三四五六七八九十百千])", "", cleaned)
        cleaned = re.sub(r"(?<=第)\s+(?=[\d一二三四五六七八九十百千])", "", cleaned)
        cleaned = re.sub(r"(?<=[\d一二三四五六七八九十百千])\s+(?=(?:之\s*\d+|條|項|款|目))", "", cleaned)
        cleaned = re.sub(r"(?<=之)\s+(?=\d+)", "", cleaned)
        return cleaned

    @staticmethod
    def _build_fts_expr(text: str, col_prefix: str = "") -> str:
        clean_fts = (text or "").replace("\x00", "")
        clean_fts = re.sub(r"""["';:\*\(\)\^\{\}\[\]<>+~|&]""", " ", clean_fts)
        raw_tokens = [t.strip("- ") for t in re.split(r"[\s,，、＆＋\+]+", clean_fts) if t.strip("- ")]
        tokens = [t for t in raw_tokens if t.upper() not in ("AND", "OR", "NOT", "NEAR")]
        if not tokens:
            return ""
        parts = []
        for tok in tokens[:5]:
            pref = f"{col_prefix} : " if col_prefix else ""
            use_prefix = (
                len(tok) >= 2
                and not re.fullmatch(r"[\d\-]+", tok)
                and not re.search(r"-\d+$", tok)
            )
            parts.append(f'{pref}"{tok}"*' if use_prefix else f'{pref}"{tok}"')
        return " AND ".join(parts)

    def _row_to_search_dict(self, r: sqlite3.Row) -> Dict[str, Any]:
        r_keys = set(r.keys())
        raw_hist = r["history_instances"] if "history_instances" in r_keys else ""
        hist_list = []
        if raw_hist:
            try:
                hist_list = json.loads(raw_hist)
            except Exception:
                hist_list = []
        sub_prior = (r["substantive_prior"] if "substantive_prior" in r_keys else "") or ""
        hist_cases_raw = (r["history_cases"] if "history_cases" in r_keys else "") or ""
        laws_raw = (r["laws_cited"] if "laws_cited" in r_keys else "") or ""
        laws_arr = [x.strip() for x in laws_raw.split("、") if x.strip()]
        has_issue = bool(r["has_legal_issue"]) if "has_legal_issue" in r_keys and r["has_legal_issue"] is not None else True
        cid = r["case_id"]
        jid = (r["jid"] if "jid" in r_keys else "") or ""
        return {
            "case_id": cid,
            "jid": jid,
            "court": (r["court"] if "court" in r_keys else "") or "",
            "level": (r["level"] if "level" in r_keys else "") or "",
            "case_type": (r["case_type"] if "case_type" in r_keys else "") or "",
            "subject": (r["subject"] if "subject" in r_keys else "") or "",
            "jud_year": (r["jud_year"] if "jud_year" in r_keys else "") or "",
            "jud_word": (r["jud_word"] if "jud_word" in r_keys else "") or "",
            "jud_no": (r["jud_no"] if "jud_no" in r_keys else "") or "",
            "date": (r["date"] if "date" in r_keys else "") or "",
            "title": (r["title"] if "title" in r_keys else "") or cid,
            "laws_cited": laws_arr,
            "issue": (r["issue"] if "issue" in r_keys else "") or "",
            "holding": (r["holding_preview"] if "holding_preview" in r_keys else "") or "",
            "shard_key": (r["shard_key"] if "shard_key" in r_keys else "") or "",
            "has_legal_issue": has_issue,
            "history_instances": hist_list,
            "extracted_history_instances": hist_list,
            "substantive_prior": sub_prior,
            "substantive_prior_instance": sub_prior,
            "history_cases": [x.strip() for x in hist_cases_raw.split("、") if x.strip()],
            "official_url": self.get_official_url(cid, jid),
        }

    def search_fts_and_meta(self, **kwargs) -> List[Dict[str, Any]]:
        if getattr(self, "db_mode", "") == "remote" and self.remote_api_url:
            res = self._remote_get_json("/search", {k: v for k, v in kwargs.items() if v is not None})
            return res if isinstance(res, list) else []

        if not self.index_db_path or not self.index_db_path.exists():
            return []

        query = str(kwargs.get("query", "")).replace("\x00", "").strip()
        jud_year = str(kwargs.get("jud_year", "")).strip()
        jud_word = str(kwargs.get("jud_word", "")).replace("全部字別 (不限)", "").strip()
        jud_no = str(kwargs.get("jud_no", "")).strip()
        case_cause = str(kwargs.get("case_cause", "")).replace("\x00", "").strip()
        main_holding = str(kwargs.get("main_holding", "")).replace("\x00", "").strip()
        argument_issue = str(kwargs.get("argument_issue", "")).replace("\x00", "").strip()
        cited_laws = str(kwargs.get("cited_laws", "")).replace("\x00", "").strip()
        case_type = str(kwargs.get("case_type", "全部")).strip()
        court_system = str(kwargs.get("court_system", "全部法院 (全體司法體系)")).strip()
        filter_no_legal_issue = bool(kwargs.get("filter_no_legal_issue", True))
        top_k = int(kwargs.get("top_k", 50))

        meta_tbl = self._meta_table
        fts_tbl = self._fts_table

        where_clauses = ["1=1"]
        params: List[Any] = []
        fts_parts = []

        if filter_no_legal_issue and "has_legal_issue" in self._table_cols:
            where_clauses.append("(m.has_legal_issue IS NULL OR m.has_legal_issue = 1)")

        base_fts_text = query or f"{main_holding} {argument_issue}".strip()
        if base_fts_text:
            expr = self._build_fts_expr(base_fts_text)
            if expr:
                fts_parts.append(expr)

        if cited_laws:
            norm_law = self._normalize_cited_laws(cited_laws)
            law_expr = self._build_fts_expr(norm_law, col_prefix="laws_cited")
            if law_expr:
                fts_parts.append(law_expr)

        if case_cause and not base_fts_text:
            cause_expr = self._build_fts_expr(case_cause, col_prefix="title")
            if cause_expr:
                fts_parts.append(cause_expr)

        use_fts_join = bool(fts_parts)
        if use_fts_join:
            where_clauses.append(f"{fts_tbl} MATCH ?")
            params.append(" AND ".join(fts_parts))

        has_narrow_index = False
        if jud_year:
            where_clauses.append("m.jud_year = ?")
            params.append(jud_year)
            has_narrow_index = True
        if jud_word:
            w_clean = re.sub(r"字$", "", jud_word).strip()
            w_cands = list(dict.fromkeys([x for x in [jud_word, w_clean] if x]))
            if w_clean == "台上":
                w_cands.extend(["台上大", "台抗"])
            ph = ",".join("?" for _ in w_cands)
            where_clauses.append(f"m.jud_word IN ({ph})")
            params.extend(w_cands)
        if jud_no:
            where_clauses.append("m.jud_no = ?")
            params.append(jud_no)
            has_narrow_index = True
        if case_type and case_type != "全部":
            where_clauses.append("m.case_type = ?")
            params.append(case_type)

        expanded_courts = self._expand_court_system_filter(court_system)
        if expanded_courts:
            ph = ",".join("?" for _ in expanded_courts)
            where_clauses.append(f"m.court IN ({ph})")
            params.extend(expanded_courts)
        elif court_system and "全部法院" not in court_system and court_system != "全部":
            where_clauses.append("(m.court LIKE ? OR m.level LIKE ?)")
            params.extend([f"%{court_system}%", f"%{court_system}%"])

        # 若無精確年份/案號且啟用 FTS（含單獨指定法院），禁止 SQL 層跨頁排序數十萬列；
        # 僅抽樣有限候選後於 Python 依審級權威度與年度排序，杜絕 G:\ 隨機磁碟讀取阻塞！
        sql_limit = min(max(top_k * 8, 120), 400) if (use_fts_join and not has_narrow_index) else top_k
        use_sql_order = (has_narrow_index or (not use_fts_join and not expanded_courts))
        order_clause = "ORDER BY CAST(m.jud_year AS INTEGER) DESC" if use_sql_order else ""
        table_source = f"{fts_tbl} f JOIN {meta_tbl} m ON f.case_id = m.case_id" if use_fts_join else f"{meta_tbl} m"
        sql = f"""
            SELECT m.*
            FROM {table_source}
            WHERE {' AND '.join(where_clauses)}
            {order_clause}
            LIMIT ?
        """
        params.append(sql_limit)

        def _court_rank(c_name: str, lvl: str) -> int:
            s = f"{c_name} {lvl}"
            if any(k in s for k in ("憲法", "大法官", "釋字")):
                return 4
            if any(k in s for k in ("大法庭", "最高法院", "最高行政")):
                return 3
            if any(k in s for k in ("高等", "智慧財產", "懲戒")):
                return 2
            return 1

        results = []
        try:
            with self._get_ro_conn(self.index_db_path) as conn:
                rows = conn.execute(sql, params).fetchall()
                # 若 FTS 長詞精準前綴 0 命中（如無空白斷詞「借名登記」），改以雙字前綴重試
                if not rows and use_fts_join and base_fts_text and len(base_fts_text) >= 4:
                    cjk_chunks = re.findall(r"[\u4e00-\u9fff]{4,}", base_fts_text)
                    if cjk_chunks:
                        alt_fts = " AND ".join(f'"{ch[:2]}"*' for ch in cjk_chunks[:2])
                        if cited_laws:
                            law_expr = self._build_fts_expr(self._normalize_cited_laws(cited_laws), col_prefix="laws_cited")
                            if law_expr:
                                alt_fts = f"{alt_fts} AND {law_expr}"
                        alt_params = [alt_fts] + list(params[1:])
                        try:
                            rows = conn.execute(sql, alt_params).fetchall()
                        except Exception:
                            pass

                for r in rows:
                    d = self._row_to_search_dict(r)
                    if case_cause and base_fts_text and case_cause not in d["title"] and case_cause not in d["holding"]:
                        continue
                    results.append(d)

                if not use_sql_order:
                    results.sort(
                        key=lambda x: (
                            _court_rank(x.get("court", ""), x.get("level", "")),
                            int(re.sub(r"\D", "", str(x.get("jud_year", "0"))) or 0),
                            str(x.get("date", ""))
                        ),
                        reverse=True
                    )
        except Exception as e:
            print(f"[Search FTS Error] {e}")

        if not results and self.remote_api_url and getattr(self, "db_mode", "") != "remote":
            remote_res = self._remote_get_json("/search", {k: v for k, v in kwargs.items() if v is not None})
            if isinstance(remote_res, list):
                return remote_res[:top_k]

        return results[:top_k]

    def find_by_citation(self, citation: str) -> Optional[Dict[str, Any]]:
        if not citation:
            return None
        if getattr(self, "db_mode", "") == "remote" and self.remote_api_url:
            res = self._remote_get_json("/lookup", {"citation": citation})
            return res if isinstance(res, dict) and res.get("found") else None

        if not self.index_db_path or not self.index_db_path.exists():
            return None
        q_clean = re.sub(r"\s+", "", citation.strip())
        meta_tbl = self._meta_table
        try:
            with self._get_ro_conn(self.index_db_path) as conn:
                m = re.search(r"(\d{2,3})(?:年|年度)?([^\d\s號第]{1,8}?)(?:字)?(?:第)?(\d+)", q_clean)
                row = None
                if m:
                    y, w, n = m.group(1), m.group(2), m.group(3)
                    w_base = re.sub(r"(?:民事|刑事|行政)?(?:字)?$", "", w).strip() or w
                    word_candidates = list(dict.fromkeys([
                        x for x in [w, w_base] + (
                            ["台上大", "台上", "台上大四", "台抗", "台非"] if "台上" in w_base else []
                        ) if x
                    ]))
                    # 1. 優先走三欄等值複合索引 idx_meta_ywn (0.01~0.04s 毫秒級精準定位，避免 LIKE 全掃)
                    for wc in word_candidates:
                        row = conn.execute(
                            f"SELECT * FROM {meta_tbl} WHERE jud_year = ? AND jud_word = ? AND jud_no = ? LIMIT 1",
                            (y, wc, n)
                        ).fetchone()
                        if row:
                            break
                    # 2. 次優先走 (jud_year, jud_no) 前導索引並於 Python 過濾字別 (0.04s)
                    if not row:
                        cand_rows = conn.execute(
                            f"SELECT * FROM {meta_tbl} WHERE jud_year = ? AND jud_no = ? LIMIT 25",
                            (y, n)
                        ).fetchall()
                        for cr in cand_rows:
                            cw = (cr["jud_word"] or "")
                            ccid = (cr["case_id"] or "")
                            if w_base in cw or w_base in ccid:
                                row = cr
                                break
                        if not row and cand_rows:
                            row = cand_rows[0]
                else:
                    row = conn.execute(
                        f"SELECT * FROM {meta_tbl} WHERE case_id = ? OR jid = ? LIMIT 1",
                        (citation.strip(), q_clean)
                    ).fetchone()
                    if not row:
                        m_const = re.search(r"(?:(\d{2,3})年)?\s*(?:釋字|憲判字?|憲裁字?)\s*第?\s*(\d+)\s*號", q_clean)
                        if m_const:
                            c_y, c_no = m_const.group(1), m_const.group(2)
                            w_list = ("憲判", "憲裁") if "憲" in q_clean else ("釋字",)
                            ph = ",".join("?" for _ in w_list)
                            if c_y:
                                row = conn.execute(
                                    f"SELECT * FROM {meta_tbl} WHERE jud_year = ? AND jud_word IN ({ph}) AND jud_no = ? LIMIT 1",
                                    (c_y, *w_list, c_no)
                                ).fetchone()
                            if not row:
                                cand_rows = conn.execute(
                                    f"SELECT * FROM {meta_tbl} WHERE jud_word IN ({ph}) AND jud_no = ? LIMIT 10",
                                    (*w_list, c_no)
                                ).fetchall()
                                if not cand_rows:
                                    cand_rows = conn.execute(
                                        f"SELECT * FROM {meta_tbl} WHERE jud_word IN ({ph}) AND case_id LIKE ? LIMIT 10",
                                        (*w_list, f"%第{c_no}號%")
                                    ).fetchall()
                                c_no_pat = re.compile(rf"(?<!\d){re.escape(c_no)}(?!\d)")
                                for cr in cand_rows:
                                    cr_no = str(cr["jud_no"] or "").strip()
                                    cr_cid = re.sub(r"\s+", "", cr["case_id"] or "")
                                    if cr_no == c_no or c_no_pat.search(cr_cid):
                                        row = cr
                                        break
                if row:
                    r_keys = set(row.keys())
                    s_key = (row["shard_key"] if "shard_key" in r_keys else "") or ""
                    hold_prev = (row["holding_preview"] if "holding_preview" in r_keys else "") or ""
                    full_txt = self.get_full_text(row["case_id"], s_key) or hold_prev
                    laws_str = (row["laws_cited"] if "laws_cited" in r_keys else "") or ""
                    laws_arr = [x.strip() for x in laws_str.split("、") if x.strip()]
                    sub_prior = (row["substantive_prior"] if "substantive_prior" in r_keys else "") or ""
                    hist_cases = (row["history_cases"] if "history_cases" in r_keys else "") or ""
                    jid_val = (row["jid"] if "jid" in r_keys else "") or ""
                    return {
                        "found": True,
                        "matched": True,
                        "case_id": row["case_id"],
                        "jid": jid_val,
                        "title": row["case_id"],
                        "standard_title": row["case_id"],
                        "court_or_agency": row["court"],
                        "court": row["court"],
                        "jud_year": row["jud_year"] if "jud_year" in r_keys else "",
                        "jud_word": row["jud_word"] if "jud_word" in r_keys else "",
                        "jud_no": row["jud_no"] if "jud_no" in r_keys else "",
                        "date": (row["date"] if "date" in r_keys else "") or "",
                        "doc_type": (row["level"] if "level" in r_keys else "") or (row["case_type"] if "case_type" in r_keys else ""),
                        "laws_cited": laws_arr,
                        "holding_snippet": hold_prev,
                        "text": full_txt,
                        "shard_key": s_key,
                        "substantive_prior": sub_prior,
                        "history_cases": hist_cases,
                        "official_url": self.get_official_url(row["case_id"], jid_val),
                    }
        except Exception:
            pass

        if self.remote_api_url and getattr(self, "db_mode", "") != "remote":
            res = self._remote_get_json("/lookup", {"citation": citation})
            if isinstance(res, dict) and res.get("found"):
                return res
        return None

    def record_redirect(self, dismissed_case_id: str, substantive_prior_id: str, discard_reason: str = "", court: str = "") -> bool:
        """
        記錄程序駁回裁定之實體前審轉址對照 (Redirect Mapping)
        """
        if not dismissed_case_id or not substantive_prior_id:
            return False
        self._init_index_db()
        try:
            with self._get_conn(self.index_db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO judgment_redirects (dismissed_case_id, substantive_prior_id, discard_reason, court)
                    VALUES (?, ?, ?, ?)
                """, (dismissed_case_id.strip(), substantive_prior_id.strip(), (discard_reason or "").strip(), (court or "").strip()))
                conn.commit()
            return True
        except Exception as e:
            print(f"[record_redirect error] {e}")
            return False

    def batch_record_redirects(self, redirects: list) -> int:
        """批次落盤程序駁回轉導映射 (避免逐筆 commit 拖慢雲端虛擬硬碟)"""
        if not redirects or not self.index_db_path.exists():
            return 0
        self._init_index_db()
        try:
            with self._get_conn(self.index_db_path) as conn:
                conn.executemany("""
                    INSERT OR REPLACE INTO judgment_redirects (dismissed_case_id, substantive_prior_id, discard_reason, court)
                    VALUES (?, ?, ?, ?)
                """, redirects)
                conn.commit()
            return len(redirects)
        except Exception as e:
            print(f"[batch_record_redirects error] {e}")
            return 0

    def get_redirect_target(self, case_id: str) -> Optional[Dict[str, Any]]:
        """
        依程序駁回案號查詢實體原審轉址目標，支援案號模糊與標準化匹配
        """
        if not case_id:
            return None
        if getattr(self, "db_mode", "") == "remote" and self.remote_api_url:
            res = self._remote_get_json("/redirect", {"case_id": case_id})
            return res if isinstance(res, dict) and res.get("is_redirect") else None

        if not self.index_db_path or not self.index_db_path.exists() or not self._has_redirects_table:
            if self.remote_api_url and getattr(self, "db_mode", "") != "remote":
                res = self._remote_get_json("/redirect", {"case_id": case_id})
                return res if isinstance(res, dict) and res.get("is_redirect") else None
            return None
        q_raw = case_id.strip()
        q_clean = re.sub(r"\s+", "", q_raw)
        try:
            with self._get_ro_conn(self.index_db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM judgment_redirects WHERE dismissed_case_id = ? LIMIT 1",
                    (q_raw,)
                ).fetchone()

                if not row:
                    q_pat_str = (r"(?<!\d)" if q_clean[:1].isdigit() else "") + re.escape(q_clean) + (r"(?!\d)" if q_clean[-1:].isdigit() else "")
                    q_boundary_re = re.compile(q_pat_str)
                    like_cands = conn.execute(
                        "SELECT * FROM judgment_redirects WHERE dismissed_case_id LIKE ? LIMIT 25",
                        (f"%{q_raw}%",)
                    ).fetchall()
                    for cand in like_cands:
                        if q_boundary_re.search(re.sub(r"\s+", "", cand["dismissed_case_id"] or "")):
                            row = cand
                            break

                if not row:
                    m = re.search(r"(\d{2,3})(?:年|年度)?([^\d\s號第]{1,6}?)(?:字)?(?:第)?(\d+)", q_clean)
                    if m:
                        y, w, n = m.group(1), m.group(2), m.group(3)
                        w_base = re.sub(r"(?:民事|刑事|行政)?(?:字)?$", "", w).strip() or w
                        y_pat = re.compile(rf"(?<!\d){re.escape(y)}(?!\d)")
                        n_pat = re.compile(rf"(?<!\d){re.escape(n)}(?!\d)")
                        cand_rows = conn.execute(
                            "SELECT * FROM judgment_redirects "
                            "WHERE dismissed_case_id LIKE ? AND dismissed_case_id LIKE ? "
                            "AND (dismissed_case_id LIKE ? OR dismissed_case_id LIKE ? OR dismissed_case_id LIKE ?) "
                            "LIMIT 50",
                            (f"%{y}%", f"%{w_base}%", f"%{n}號%", f"%{n} 號%", f"%{n}")
                        ).fetchall()
                        if not cand_rows:
                            cand_rows = conn.execute(
                                "SELECT * FROM judgment_redirects WHERE dismissed_case_id LIKE ? AND dismissed_case_id LIKE ? AND dismissed_case_id LIKE ? LIMIT 100",
                                (f"%{y}%", f"%{w_base}%", f"%{n}%")
                            ).fetchall()
                        for cand in cand_rows:
                            cid_cand = re.sub(r"\s+", "", cand["dismissed_case_id"] or "")
                            if y_pat.search(cid_cand) and w_base in cid_cand and n_pat.search(cid_cand):
                                row = cand
                                break

                if row:
                    return {
                        "is_redirect": True,
                        "dismissed_case_id": row["dismissed_case_id"],
                        "substantive_prior_id": row["substantive_prior_id"],
                        "discard_reason": row["discard_reason"],
                        "court": row["court"],
                        "created_at": row["created_at"]
                    }
        except Exception as e:
            logger.warning("get_redirect_target error: %s", e)

        if self.remote_api_url and getattr(self, "db_mode", "") != "remote":
            res = self._remote_get_json("/redirect", {"case_id": case_id})
            return res if isinstance(res, dict) and res.get("is_redirect") else None
        return None

    def prune_non_substantive_records(self, commit: bool = False, batch_size: int = 5000) -> Dict[str, Any]:
        """整合清理非訟與純事實低價值裁判（具實體法律爭點白名單保護）。"""
        if not self.index_db_path or not self.index_db_path.exists():
            return {"success": False, "error": "資料庫尚未建立", "pruned": 0}
        if self.db_mode != "master":
            return {"success": False, "error": "僅限全量母庫執行精純化清理", "pruned": 0}

        non_sub_re = re.compile(
            r"年度\s*(?:[^\s0-9]*?(?:票|促|調|拍|補|移|定刑|執聲)[^\s0-9]*?)\s*字|公示催告|公示送達"
        )
        protect_re = re.compile(
            r"大法庭|憲判字|釋字|判例|決議|座談會|肯定說|否定說|折衷說|學說|通說|實務見解|"
            r"爭點|競合|界限|排他|構成要件|阻卻違法|期待可能性|正當防衛|緊急避難|合憲|違憲|目的性限縮|類推適用|爭點效|既判力"
        )
        junk_entries = []
        protected = 0
        with self._get_ro_conn(self.index_db_path) as conn:
            cur = conn.execute(f"SELECT rowid, court, case_id, title, holding_preview FROM {self._meta_table}")
            while True:
                batch = cur.fetchmany(batch_size)
                if not batch:
                    break
                for rowid, court, cid, title, hold in batch:
                    cid_s = cid or ""
                    if non_sub_re.search(cid_s):
                        if protect_re.search(title or "") or protect_re.search(hold or ""):
                            protected += 1
                            continue
                        junk_entries.append((rowid, cid_s))

        if commit and junk_entries:
            all_drifted_cids = []
            with self._get_conn(self.index_db_path) as wconn:
                for i in range(0, len(junk_entries), batch_size):
                    sub_entries = junk_entries[i:i + batch_size]
                    sub_rowids = [r_id for r_id, _ in sub_entries]
                    ph = ",".join("?" for _ in sub_rowids)
                    wconn.execute(f"DELETE FROM {self._meta_table} WHERE rowid IN ({ph})", sub_rowids)
                    expected_by_rowid = {r_id: c_id for r_id, c_id in sub_entries}
                    try:
                        fts_rows = wconn.execute(
                            f"SELECT rowid, case_id FROM {self._fts_table} WHERE rowid IN ({ph})",
                            sub_rowids,
                        ).fetchall()
                        matched_fts_rowids = [
                            fr[0] for fr in fts_rows if fr[1] == expected_by_rowid.get(fr[0])
                        ]
                        matched_cids = {expected_by_rowid[r_id] for r_id in matched_fts_rowids}
                        if matched_fts_rowids:
                            mph = ",".join("?" for _ in matched_fts_rowids)
                            wconn.execute(f"DELETE FROM {self._fts_table} WHERE rowid IN ({mph})", matched_fts_rowids)
                        if len(matched_fts_rowids) < len(sub_entries):
                            all_drifted_cids.extend(
                                c_id for _, c_id in sub_entries if c_id and c_id not in matched_cids
                            )
                    except Exception as fts_err:
                        logger.warning("FTS prune cleanup failed for batch: %s", fts_err)
                for j in range(0, len(all_drifted_cids), 900):
                    dsub = all_drifted_cids[j:j + 900]
                    dph = ",".join("?" for _ in dsub)
                    try:
                        wconn.execute(f"DELETE FROM {self._fts_table} WHERE case_id IN ({dph})", dsub)
                    except Exception as fts_err:
                        logger.warning("FTS drifted prune cleanup failed: %s", fts_err)
                wconn.commit()
            self._cached_count = None

        return {
            "success": True,
            "candidates": len(junk_entries),
            "protected": protected,
            "pruned": len(junk_entries) if commit else 0,
            "committed": commit,
        }

    # 
    def ingest_inbox_folder(self, folder_path: Path = None, batch_size: int = 5000,
                            max_records: int = 1000000, progress_cb=None) -> Dict[str, Any]:
        try:
            from import_judicial_opendata import parse_official_opendata_record
        except ImportError:
            def parse_official_opendata_record(d): return d if d.get("case_id") else None

        target_dir = Path(folder_path) if folder_path else self.inbox_dir
        if not target_dir.exists():
            return {
                "success": False,
                "error": f"目錄不存在: {target_dir}",
                "added": 0,
                "files_processed": 0,
                "total_in_db": self.get_total_count()
            }

        all_files = sorted(
            list(target_dir.rglob("*.rar")) +
            list(target_dir.rglob("*.7z")) +
            list(target_dir.rglob("*.zip")) +
            list(target_dir.rglob("*.json")) +
            list(target_dir.rglob("*.jsonl"))
        )

        buffer = []
        total_added = 0
        files_done = 0

        def _flush():
            nonlocal buffer, total_added
            if buffer:
                n = self.batch_upsert_records(buffer, batch_size=batch_size)
                total_added += n
                buffer = []

        def _feed_text(text: str):
            nonlocal buffer, total_added
            try:
                obj = json.loads(text)
                items = obj if isinstance(obj, list) else [obj]
                for it in items:
                    if isinstance(it, dict):
                        p = parse_official_opendata_record(it) if ("JID" in it or "JFULL" in it) else it
                        if p and p.get("case_id"):
                            buffer.append(p)
                            if len(buffer) >= batch_size:
                                _flush()
            except Exception:
                pass

        for idx_f, fp in enumerate(all_files, 1):
            if total_added >= max_records:
                break
            if progress_cb:
                progress_cb(idx_f, len(all_files), fp.name, total_added)

            low = fp.name.lower()
            try:
                if low.endswith(".json"):
                    _feed_text(fp.read_text(encoding="utf-8", errors="ignore"))
                    files_done += 1
                elif low.endswith(".jsonl"):
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f_jl:
                        for line in f_jl:
                            if line.strip():
                                _feed_text(line)
                    files_done += 1
                elif low.endswith(".zip"):
                    with zipfile.ZipFile(fp, "r") as zf:
                        for m in zf.namelist():
                            if m.lower().endswith(".json"):
                                try:
                                    _feed_text(zf.read(m).decode("utf-8", errors="ignore"))
                                except Exception:
                                    continue
                    files_done += 1
                elif low.endswith(".rar") or low.endswith(".7z"):
                    with tempfile.TemporaryDirectory() as tmpd:
                        out_d = Path(tmpd) / "extracted"
                        out_d.mkdir(parents=True, exist_ok=True)
                        extracted = False

                        if low.endswith(".rar"):
                            try:
                                import rarfile
                                with rarfile.RarFile(str(fp)) as rf:
                                    rf.extractall(str(out_d))
                                extracted = True
                            except Exception:
                                pass
                        elif low.endswith(".7z"):
                            try:
                                import py7zr
                                with py7zr.SevenZipFile(str(fp), mode="r") as sz:
                                    sz.extractall(path=str(out_d))
                                extracted = True
                            except Exception:
                                pass

                        if not extracted:
                            cli_candidates = [
                                ["unar", "-o", str(out_d), "-f", str(fp)],
                                ["7z", "x", "-y", f"-o{out_d}", str(fp)],
                                [r"C:\Program Files\7-Zip\7z.exe", "x", "-y", f"-o{out_d}", str(fp)],
                                [r"C:\Program Files (x86)\7-Zip\7z.exe", "x", "-y", f"-o{out_d}", str(fp)],
                                ["unrar", "x", "-y", str(fp), str(out_d)],
                                [r"C:\Program Files\WinRAR\UnRAR.exe", "x", "-y", str(fp), str(out_d)],
                                ["bsdtar", "-xf", str(fp), "-C", str(out_d)]
                            ]
                            for cmd in cli_candidates:
                                if shutil.which(cmd[0]) or Path(cmd[0]).exists():
                                    try:
                                        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
                                        if list(out_d.rglob("*.json")):
                                            extracted = True
                                            break
                                    except Exception:
                                        continue

                        for j_file in out_d.rglob("*.json"):
                            try:
                                _feed_text(j_file.read_text(encoding="utf-8", errors="ignore"))
                            except Exception:
                                continue
                    files_done += 1
            except Exception as fe:
                print(f"[Ingest Error] {fp.name}: {fe}")

        _flush()
        return {
            "success": True,
            "added": total_added,
            "files_processed": files_done,
            "total_in_db": self.get_total_count()
        }

    def download_and_ingest_opendata(self, member_account: str = "", pwd: str = "",
                                     target_count: int = 1000000,
                                     progress_cb=None) -> Dict[str, Any]:
        import requests

        allow_insecure = os.getenv("LEGAL_ALLOW_INSECURE_SSL", "0").lower() in ("1", "true", "yes")

        def _safe_get(url: str, **req_kwargs):
            if safe_requests_get is not None:
                return safe_requests_get(url, **req_kwargs)
            try:
                return requests.get(url, verify=True, **req_kwargs)
            except requests.exceptions.SSLError:
                if allow_insecure:
                    return requests.get(url, verify=False, **req_kwargs)
                raise

        def _safe_post(url: str, **req_kwargs):
            try:
                return requests.post(url, verify=True, **req_kwargs)
            except requests.exceptions.SSLError as ssl_err:
                if allow_insecure:
                    logger.warning("LEGAL_ALLOW_INSECURE_SSL enabled; retrying POST %s with verify=False", url)
                    return requests.post(url, verify=False, **req_kwargs)
                raise requests.exceptions.SSLError(
                    f"TLS/SSL 憑證驗證失敗 ({url}): {ssl_err}。預設禁止停用驗證；如確定安全且缺乏 GRCA 根憑證，請設 LEGAL_ALLOW_INSECURE_SSL=1。"
                ) from ssl_err

        headers = {"Content-Type": "application/json", "User-Agent": "LawExamData/1.0"}
        token = ""

        if member_account and pwd:
            try:
                r_tok = _safe_post(
                    "https://opendata.judicial.gov.tw/api/MemberTokens",
                    headers=headers,
                    json={"memberAccount": member_account.strip(), "pwd": pwd.strip()},
                    timeout=20,
                )
                if r_tok.status_code == 200:
                    token = r_tok.json().get("token", "")
            except Exception as e:
                print(f"[Auth Notice] {e}")

        if token:
            headers["Authorization"] = f"Bearer {token}"

        filesets_to_download = []
        try:
            r_cat = _safe_get(
                "https://opendata.judicial.gov.tw/data/api/rest/categories",
                headers=headers, timeout=20
            )
            cats = r_cat.json() if r_cat.status_code == 200 else [{"categoryNo": "001", "categoryName": "裁判書"}]
            for c in cats:
                c_no = c.get("categoryNo", "001")
                r_res = _safe_get(
                    f"https://opendata.judicial.gov.tw/data/api/rest/categories/{c_no}/resources",
                    headers=headers, timeout=25
                )
                if r_res.status_code == 200 and isinstance(r_res.json(), list):
                    for ds in r_res.json():
                        tit = str(ds.get("title", ""))
                        if any(k in tit for k in ["裁判", "判決", "案件", "大法庭", "刑事", "民事", "行政"]):
                            for fs in ds.get("filesets", []):
                                filesets_to_download.append({
                                    "title": tit,
                                    "fileSetId": fs.get("fileSetId"),
                                    "format": str(fs.get("resourceFormat", "RAR")).lower(),
                                    "desc": fs.get("resourceDescription", "")
                                })
        except Exception as e:
            return {"success": False, "error": f"獲取開放資料集清單失敗: {e}"}

        print(f"🌐 成功檢索到 {len(filesets_to_download)} 個司法院月度裁判書資料集檔案！")

        downloaded_count = 0

        for idx_fs, fs_info in enumerate(filesets_to_download, 1):
            if self.get_total_count() >= target_count:
                print(f"🎉 資料庫總筆數已達到目標 {target_count:,} 筆，停止下載！")
                break

            fid = fs_info["fileSetId"]
            fmt = fs_info["format"] or "rar"
            file_name = f"opendata_{fid}.{fmt}"
            dest_file = self.inbox_dir / file_name

            if progress_cb:
                progress_cb("downloading", idx_fs, len(filesets_to_download), fs_info["title"], self.get_total_count())

            dl_url = f"https://opendata.judicial.gov.tw/api/FilesetLists/{fid}/file"
            print(f"⬇️ 正在下載 [{idx_fs}/{len(filesets_to_download)}]: {fs_info['title']} -> {dest_file.name}...")

            try:
                with _safe_get(dl_url, headers=headers, stream=True, timeout=120) as r_dl:
                    if r_dl.status_code == 200:
                        with open(dest_file, "wb") as f_out:
                            for chunk in r_dl.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    f_out.write(chunk)
                        downloaded_count += 1
                        print(f"✅ 下載完成 ({dest_file.stat().st_size / (1024*1024):.1f} MB)，立即啟動解壓入庫...")
                        self.ingest_inbox_folder(folder_path=self.inbox_dir, max_records=target_count)
            except Exception as dl_err:
                print(f"⚠️ 下載異常 {fid}: {dl_err}")

        return {
            "success": True,
            "datasets_found": len(filesets_to_download),
            "files_downloaded": downloaded_count,
            "total_in_db": self.get_total_count()
        }

    def migrate_local_data(self, progress_cb=None) -> Dict[str, Any]:
        try:
            from import_judicial_opendata import import_scoring_standards_judgments
        except ImportError:
            import_scoring_standards_judgments = lambda: []

        records_to_migrate = []
        seen_case_ids = set()

        def _add_rec(r):
            cid = r.get("case_id")
            if cid and cid not in seen_case_ids:
                seen_case_ids.add(cid)
                records_to_migrate.append(r)

        # 1. precedents_catalog.json
        p_cat_candidates = [
            Path(RAW_DATA_DIR) / "precedents_catalog.json",
            Path(DATA_DIR) / "raw_exams" / "precedents_catalog.json",
            Path(__file__).resolve().parent / "data" / "raw_exams" / "precedents_catalog.json",
            Path(__file__).resolve().parent.parent / "raw_exams" / "precedents_catalog.json",
            Path("/tmp/law_repo/data/raw_exams/precedents_catalog.json")
        ]
        p_cat_file = next((p for p in p_cat_candidates if p.exists()), None)
        if p_cat_file:
            print(f"📖 正在讀取權威裁判大典: {p_cat_file}...")
            try:
                with open(p_cat_file, "r", encoding="utf-8") as f:
                    cat_list = json.load(f)
                    for item in cat_list:
                        _add_rec(item)
                print(f"  ✅ 載入 {len(cat_list):,} 筆指標先例裁判、決議與座談會。")
            except Exception as e:
                print(f"  ⚠️ 讀取 precedents_catalog.json 異常: {e}")

        # 2. scoring_standards/*.json
        print("🏛️ 正在解析 scoring_standards 真實裁判庫...")
        try:
            std_recs = import_scoring_standards_judgments()
            for r in std_recs:
                _add_rec(r)
            print(f"  ✅ 成功解析 {len(std_recs):,} 筆真實裁判。")
        except Exception as e:
            print(f"  ⚠️ scoring_standards 解析異常: {e}")

        # 3. 憲法裁判庫 (優先讀取整合之 training_data/law_exam_constitutional_sft.json)
        const_sft_cands = [
            Path(TRAINING_DATA_DIR) / "law_exam_constitutional_sft.json",
            Path(DATA_DIR) / "training_data" / "law_exam_constitutional_sft.json",
            Path(__file__).resolve().parent.parent / "training_data" / "law_exam_constitutional_sft.json"
        ]
        const_sft_file = next((p for p in const_sft_cands if p.exists()), None)
        if const_sft_file:
            print(f"📜 正在解析憲法裁判整合庫: {const_sft_file}...")
            try:
                with open(const_sft_file, "r", encoding="utf-8") as f:
                    c_list = json.load(f)
                for item in c_list:
                    inst = item.get("instruction", "")
                    inp = item.get("input", "")
                    out = item.get("output", "")
                    m_tit = re.search(r'【([^】]+?(?:憲判|釋字|解釋)[^】]*?)】', inst + " " + inp)
                    cid = m_tit.group(1) if m_tit else f"憲法法庭判決_{len(seen_case_ids)+1}"
                    _add_rec({
                        "case_id": cid,
                        "court": "憲法法庭 / 司法院大法官",
                        "level": "憲法裁判 / 大法官解釋",
                        "subject": "憲法與人權保障",
                        "sub_category": "基本權利違憲審查",
                        "date": "",
                        "title": cid,
                        "laws_cited": ["憲法第23條", "憲法第8條"],
                        "issue": inst[:200],
                        "holding": out[:600],
                        "full_text": f"{inst}\n\n【案件事實】：\n{inp}\n\n【憲法評析與主文】：\n{out}",
                        "source": "constitutional_cases"
                    })
                print(f"  ✅ 成功載入 {len(c_list):,} 筆憲法裁判與大法官解釋！")
            except Exception as ce:
                print(f"  ⚠️ 憲法整合庫解析異常: {ce}")

        # 4. training_data/law_exam_verified_sft.jsonl
        sft_files = [
            Path(TRAINING_DATA_DIR) / "law_exam_verified_sft.jsonl",
            Path(DATA_DIR) / "training_data" / "law_exam_verified_sft.jsonl",
            Path(__file__).resolve().parent.parent / "training_data" / "law_exam_verified_sft.jsonl"
        ]
        sft_file = next((p for p in sft_files if p.exists()), None)
        if sft_file:
            print(f"📊 正在抽取已核實真實裁判 SFT: {sft_file}...")
            sft_jud_count = 0
            try:
                with open(sft_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        row = json.loads(line)
                        st_type = str(row.get("source_type", ""))
                        if "judgment" in st_type or "precedent" in st_type or "court" in st_type:
                            inp = row.get("input", "")
                            out = row.get("output", "")
                            m_cid = re.search(r'(臺灣[^\s0-9]+?法院[0-9\s年度字號]+?(?:判決|裁定)|最高法院[0-9\s年度字號]+?(?:判決|裁定|民事大法庭裁定|刑事大法庭裁定)|最高行政法院[0-9\s年度字號]+?(?:判決|裁定))', inp)
                            cid = m_cid.group(1).replace(" ", "") if m_cid else f"核實實務判決_{row.get('id', '')}"
                            _add_rec({
                                "case_id": cid,
                                "court": "各級法院",
                                "level": "實戰裁判SFT",
                                "subject": "實戰實務判解",
                                "sub_category": "司律二試核心爭點",
                                "date": "",
                                "title": cid,
                                "laws_cited": [],
                                "issue": row.get("instruction", "")[:200],
                                "holding": out[:500],
                                "full_text": f"{inp}\n\n【評分與法理分析】：\n{out}",
                                "source": "verified_sft"
                            })
                            sft_jud_count += 1
                print(f"  ✅ 自 verified SFT 抽取 {sft_jud_count:,} 筆真實裁判。")
            except Exception as e:
                print(f"  ⚠️ SFT 抽取異常: {e}")

        print(f"🚀 開始將全部 {len(records_to_migrate):,} 筆裁判與見解寫入 SQLite FTS5 與分片庫...")
        n_inserted = self.batch_upsert_records(records_to_migrate, batch_size=5000)
        total_in_db = self.get_total_count()
        print(f"🎉 本機資料遷移完成！本次成功寫入 {n_inserted:,} 筆，目前 SQLite 大庫總計 **{total_in_db:,} 筆** 裁判！")

        return {
            "success": True,
            "migrated_records": n_inserted,
            "total_in_db": total_in_db
        }


_GLOBAL_MILLION_ENGINE: Optional[MillionJudgmentsSQLiteEngine] = None

def get_million_db_engine() -> MillionJudgmentsSQLiteEngine:
    global _GLOBAL_MILLION_ENGINE
    if _GLOBAL_MILLION_ENGINE is None:
        _GLOBAL_MILLION_ENGINE = MillionJudgmentsSQLiteEngine()
    return _GLOBAL_MILLION_ENGINE


def main():
    parser = argparse.ArgumentParser(description="百萬級裁判書 SQLite FTS5 全文檢索資料庫管理工具")
    parser.add_argument("--migrate-local", action="store_true", help="管線 C：一鍵遷移本機既有裁判、大法庭、憲判字、原判例與決議至 SQLite FTS5")
    parser.add_argument("--ingest-inbox", action="store_true", help="管線 A：掃描 opendata_inbox 資料夾批次解壓入庫")
    parser.add_argument("--inbox-dir", type=str, default="", help="指定 opendata_inbox 資料夾路徑")
    parser.add_argument("--download-opendata", action="store_true", help="管線 B：串接司法院資料開放平臺 API 自動下載月度壓縮包")
    parser.add_argument("--user", type=str, default="", help="司法院資料開放平臺會員帳號")
    parser.add_argument("--pwd", type=str, default="", help="司法院資料開放平臺會員密碼")
    parser.add_argument("--target-count", type=int, default=1000000, help="下載與入庫之目標總筆數 (預設 1,000,000)")
    parser.add_argument("--search", type=str, default="", help="執行 FTS5 關鍵字檢索測試")
    parser.add_argument("--lookup", type=str, default="", help="精準調閱指定裁判案號")
    parser.add_argument("--prune", action="store_true", help="管線 D：掃描非訟與純事實低價值裁判（預設乾跑預覽）")
    parser.add_argument("--commit", action="store_true", help="配合 --prune 正式刪除低價值紀錄")
    parser.add_argument("--stats", action="store_true", help="顯示目前 SQLite 大庫統計")

    args = parser.parse_args()
    engine = get_million_db_engine()

    if args.migrate_local:
        res = engine.migrate_local_data()
        print(f'\n[遷移結果] 成功寫入: {res.get("migrated_records", 0):,} 筆 ｜ 大庫總筆數: {res.get("total_in_db", 0):,} 筆')
    elif args.ingest_inbox:
        inbox_p = Path(args.inbox_dir) if args.inbox_dir else None
        res = engine.ingest_inbox_folder(folder_path=inbox_p, max_records=args.target_count)
        print(f'\n[入庫結果] 處理檔案: {res.get("files_processed", 0)} 個 ｜ 新增: {res.get("added", 0):,} 筆 ｜ 大庫總筆數: {res.get("total_in_db", 0):,} 筆')
    elif args.download_opendata:
        res = engine.download_and_ingest_opendata(member_account=args.user, pwd=args.pwd, target_count=args.target_count)
        print(f'\n[下載入庫結果] 完成！大庫總筆數: {res.get("total_in_db", 0):,} 筆')
    elif args.prune:
        res = engine.prune_non_substantive_records(commit=args.commit)
        print(f"\n[精純化清理] 掃描候選: {res.get('candidates', 0):,} 筆 ｜ 白名單保護: {res.get('protected', 0):,} 筆 ｜ 實際清理: {res.get('pruned', 0):,} 筆 (commit={res.get('committed')})")
    elif args.search:
        results = engine.search_fts_and_meta(query=args.search, top_k=10)
        print(f"\n🔍 檢索關鍵字 '{args.search}' 命中 {len(results)} 筆：")
        for idx, r in enumerate(results, 1):
            print(f"{idx}. [{r.get('level')}] {r.get('case_id')} ｜ {r.get('title')[:40]}")
            print(f"   要旨: {r.get('holding', '')[:100]}...\n")
    elif args.lookup:
        res = engine.find_by_citation(args.lookup)
        if res and res.get("found"):
            print(f'\n✅ 成功找到: {res.get("title")} ({res.get("doc_type")})')
            print(f'要旨: {res.get("holding_snippet")}\n')
            full = res.get("text", "")
            print(f'長度: {len(full)} 字元 ｜ 預覽: {full[:300]}...')
        else:
            print(f'❌ 查無此案號: {args.lookup}')
    else:
        info = engine.get_db_info()
        shards = list(engine.shards_dir.glob("*.db")) if engine.shards_dir.exists() else []
        print(f'\n📊 百萬級裁判大庫現況：')
        print(f'  - 運作模式: {info.get("mode")} ({info.get("title")})')
        print(f'  - 索引庫路徑: {info.get("path")}')
        print(f'  - 目前索引數: {info.get("count", 0):,} 筆')
        print(f'  - 分片狀態: {len(shards)} 個分片檔案 (預設 Index-Only 模式，無需 shards)')
        print(f'  - 待處理收件匣: {engine.inbox_dir}')
        print(f'\n使用範例：')
        print(f'  python build_million_judgments_db.py --migrate-local')
        print(f'  python build_million_judgments_db.py --ingest-inbox')
        print(f'  python build_million_judgments_db.py --download-opendata --target-count 1000000')
        print(f'  python build_million_judgments_db.py --search "借名登記"')
        print(f'  python build_million_judgments_db.py --lookup "108台上大1719"')
        print(f'  python build_million_judgments_db.py --prune')


if __name__ == "__main__":
    main()
