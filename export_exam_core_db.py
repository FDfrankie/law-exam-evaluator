#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
司法考試核心精華子庫一鍵提煉工具 (export_exam_core_db.py)
=============================================================================
【設計目標】：
直接從本機全量 Total 母庫（judicial_1m_index.db + judicial_authority.db）
以唯讀分層索引查詢，快速提煉出專供線上 Streamlit Cloud 部署與國考 AI 閱卷的
輕量化精華子庫 (judicial_exam_core.db + .db.gz)。

【核心架構】：
1. 全量授權唯讀連線 (mode=ro URI)：絕不鎖定本機母庫，亦避免全表 COUNT(*)/LIKE 掃描。
2. 結構完全相容：直接建立標準 judgments_meta / judgments_fts / judgment_redirects /
   authority_records / authority_fts / precedents / precedents_fts / core_manifest，
   並附加 exam_judgments_meta 相容檢視表，讓所有檢索引擎零縫接切換至 Core DB。
3. 國考分層精萃策略：
   - Tier 1 (100% 收錄)：憲法法庭、司法院大法官解釋、大法庭裁定、最高法院庭會議決議、
     高院座談會與全量判例要旨。
   - Tier 2 (~65% 配額)：最高法院、最高行政法院、智慧財產及商業法院近年實質爭點裁判。
   - Tier 3 (~35% 配額)：高等法院、高等行政法院具實質法條與爭點之代表性裁判。
=============================================================================
"""

import os
import sys
import gzip
import time
import shutil
import sqlite3
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple

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
    from config import DATA_DIR
except ImportError:
    DATA_DIR = Path(__file__).resolve().parent / "data"


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def get_ro_conn(db_path: Path) -> sqlite3.Connection:
    """以唯讀 URI 模式開啟來源資料庫，確保絕不阻礙母庫讀寫。"""
    uri = f"file:///{Path(db_path).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=120.0, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 120000;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        conn.execute("PRAGMA cache_size = -65536;")
    except Exception:
        pass
    return conn


TIER1_COURTS = (
    "憲法法庭",
    "司法院大法官",
    "憲法法庭 / 司法院大法官",
    "最高法院民事大法庭",
    "最高法院刑事大法庭",
    "最高法院民事庭會議",
    "最高法院刑事庭會議",
    "最高行政法院庭長法官聯席會議",
    "臺灣高等法院暨所屬法院法律座談會",
)

TIER2_COURTS = (
    "最高法院",
    "最高行政法院",
    "智慧財產及商業法院",
)

TIER3_COURTS = (
    "臺灣高等法院",
    "臺北高等行政法院",
    "臺中高等行政法院",
    "高雄高等行政法院",
    "臺灣高等法院臺中分院",
    "臺灣高等法院臺南分院",
    "臺灣高等法院高雄分院",
    "臺灣高等法院花蓮分院",
)

GRAND_WORDS = ("台上大", "台抗大", "台上大字", "台抗大字", "大字")
SUPREME_EXCLUSIVE_WORDS = ("台上", "台抗", "台再", "台簡上")
RECENT_YEARS_SUPREME = tuple(str(y) for y in range(114, 99, -1))
HIGH_COURT_WEIGHTS = (
    ("臺灣高等法院", 0.45),
    ("臺北高等行政法院", 0.25),
    ("臺中高等行政法院", 0.15),
    ("高雄高等行政法院", 0.15),
)


def _resolve_total_db(total_db_path: Optional[Path]) -> Path:
    base_data = Path(DATA_DIR)
    if total_db_path and Path(total_db_path).exists():
        return Path(total_db_path)
    cand_totals = [
        base_data / "judicial_1m_db" / "judicial_1m_index.db",
        base_data / "judicial_1m_index.db",
        Path(r"D:\LawExamData\judicial_1m_db\judicial_1m_index.db"),
        Path(r"C:\LawExamData\judicial_1m_db\judicial_1m_index.db"),
        Path(__file__).resolve().parent / "data" / "judicial_1m_db" / "judicial_1m_index.db",
        Path("G:/我的雲端硬碟/LawExamData/data/judicial_1m_db/judicial_1m_index.db"),
    ]
    found = next((p for p in cand_totals if p.exists() and p.stat().st_size > 10000), None)
    if not found:
        raise FileNotFoundError(f"找不到 Total 百萬裁判母庫，請以 --total-db 指定路徑。嘗試過: {cand_totals}")
    return found


def _resolve_auth_db(auth_db_path: Optional[Path]) -> Optional[Path]:
    base_data = Path(DATA_DIR)
    if auth_db_path and Path(auth_db_path).exists():
        return Path(auth_db_path)
    cand_auths = [
        base_data / "judicial_authority.db",
        Path(__file__).resolve().parent / "data" / "judicial_authority.db",
        Path("G:/我的雲端硬碟/LawExamData/data/judicial_authority.db"),
    ]
    return next((p for p in cand_auths if p.exists() and p.stat().st_size > 10000), None)


def _create_core_schema(out_conn: sqlite3.Connection):
    # 1. authority_records & authority_fts (100% 相容 authority_engine.py)
    out_conn.execute("""
        CREATE TABLE IF NOT EXISTS authority_records (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            sub_type TEXT NOT NULL,
            case_no TEXT NOT NULL,
            date TEXT,
            court TEXT,
            title TEXT,
            holding TEXT,
            reasoning TEXT,
            laws_cited TEXT,
            status TEXT,
            extra_meta TEXT
        )
    """)
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_cat ON authority_records(category);")
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_subtype ON authority_records(sub_type);")
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_caseno ON authority_records(case_no);")
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_date ON authority_records(date);")
    out_conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS authority_fts USING fts5(
            id UNINDEXED,
            case_no,
            title,
            holding,
            reasoning,
            laws_cited,
            tokenize='unicode61'
        )
    """)

    # 2. precedents & precedents_fts (100% 相容 authority_engine.py)
    out_conn.execute("""
        CREATE TABLE IF NOT EXISTS precedents (
            id TEXT PRIMARY KEY,
            precedent_id TEXT,
            sys_type TEXT NOT NULL,
            case_no TEXT NOT NULL,
            year TEXT,
            court TEXT,
            title TEXT,
            holding TEXT,
            reasoning TEXT,
            laws_cited TEXT,
            status TEXT,
            subject TEXT,
            sub_category TEXT,
            date TEXT,
            extra_meta TEXT,
            abolition_note TEXT,
            source_url TEXT
        )
    """)
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_sys ON precedents(sys_type);")
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_caseno ON precedents(case_no);")
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_prec_status ON precedents(status);")
    out_conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS precedents_fts USING fts5(
            id UNINDEXED,
            case_no,
            title,
            holding,
            reasoning,
            laws_cited,
            tokenize='unicode61'
        )
    """)

    # 3. judgments_meta, judgments_fts, judgment_redirects (100% 相容 MillionJudgmentsSQLiteEngine)
    out_conn.execute("""
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
            history_instances TEXT DEFAULT '',
            substantive_prior TEXT DEFAULT '',
            history_cases TEXT DEFAULT ''
        )
    """)
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_ywn ON judgments_meta(jud_year, jud_word, jud_no);")
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_court_type ON judgments_meta(court, case_type);")
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_legal_issue ON judgments_meta(has_legal_issue);")
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_jid ON judgments_meta(jid);")
    out_conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS judgments_fts USING fts5(
            case_id UNINDEXED,
            title,
            holding_preview,
            issue,
            laws_cited,
            tokenize='unicode61'
        )
    """)
    out_conn.execute("""
        CREATE TABLE IF NOT EXISTS judgment_redirects (
            dismissed_case_id TEXT PRIMARY KEY,
            substantive_prior_id TEXT,
            discard_reason TEXT,
            court TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    out_conn.execute("CREATE INDEX IF NOT EXISTS idx_redirect_dismissed ON judgment_redirects(dismissed_case_id);")

    # Compatibility views
    out_conn.execute("CREATE VIEW IF NOT EXISTS exam_judgments_meta AS SELECT * FROM judgments_meta;")

    # 4. Manifest
    out_conn.execute("""
        CREATE TABLE IF NOT EXISTS core_manifest (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)


def _select_meta_columns_expr(avail_cols: Set[str]) -> str:
    cols = [
        "case_id", "jid", "court", "level", "case_type", "subject",
        "jud_year", "jud_word", "jud_no", "date", "title",
        "laws_cited", "issue", "holding_preview", "shard_key",
    ]
    exprs = [c if c in avail_cols else f"'' AS {c}" for c in cols]
    exprs.append("has_legal_issue" if "has_legal_issue" in avail_cols else "1 AS has_legal_issue")
    for opt_col in ("history_instances", "substantive_prior", "history_cases"):
        exprs.append(opt_col if opt_col in avail_cols else f"'' AS {opt_col}")
    return ", ".join(exprs)


def export_exam_core_database(
    total_db_path: Optional[Path] = None,
    auth_db_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    max_judgments: int = 35000,
    dry_run: bool = False,
    verbose: bool = True,
    gzip_output: bool = False,
) -> Path:
    base_data = Path(DATA_DIR)
    total_db = _resolve_total_db(total_db_path)
    auth_db = _resolve_auth_db(auth_db_path)

    if not output_path:
        output_path = base_data / "judicial_exam_core.db"
    else:
        output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 預設建議上限 35,000（壓縮後輕鬆低於 GitHub 50MB 安全線）；若傳 0 表示最高法院/高院旗艦 100,000 筆配額
    target_cap = int(max_judgments) if int(max_judgments) > 0 else 100000

    if verbose:
        print("=================================================================")
        print("[*] 啟動司法考試核心精華子庫提煉作業 (Core Extraction v2)")
        print(f"[*] Total 百萬母庫 : {total_db} ({total_db.stat().st_size / (1024*1024):.1f} MB)")
        if auth_db and auth_db.exists():
            print(f"[*] 權威判例母庫   : {auth_db} ({auth_db.stat().st_size / (1024*1024):.1f} MB)")
        print(f"[*] 輸出目標子庫   : {output_path}")
        print(f"[*] 裁判精萃上限   : {target_cap:,} 筆 (含全量釋字、憲判、大法庭與經典判例)")
        if dry_run:
            print("[*] 模式           : 【乾跑統計 (Dry Run)，不實際寫入磁碟】")
        print("=================================================================\n")

    t_start = time.time()

    if dry_run:
        with get_ro_conn(total_db) as conn:
            max_row = conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM judgments_meta").fetchone()[0]
            t1_placeholders = ",".join("?" for _ in TIER1_COURTS)
            t1_cnt = conn.execute(
                f"SELECT COUNT(*) FROM judgments_meta WHERE court IN ({t1_placeholders})", TIER1_COURTS
            ).fetchone()[0]
            t2_placeholders = ",".join("?" for _ in TIER2_COURTS)
            t2_cnt = conn.execute(
                f"SELECT COUNT(*) FROM judgments_meta WHERE court IN ({t2_placeholders})", TIER2_COURTS
            ).fetchone()[0]
            t3_placeholders = ",".join("?" for _ in ("臺灣高等法院", "臺北高等行政法院", "臺中高等行政法院", "高雄高等行政法院"))
            t3_cnt = conn.execute(
                f"SELECT COUNT(*) FROM judgments_meta WHERE court IN ({t3_placeholders})",
                ("臺灣高等法院", "臺北高等行政法院", "臺中高等行政法院", "高雄高等行政法院")
            ).fetchone()[0]
        auth_cnt = 0
        prec_cnt = 0
        if auth_db and auth_db.exists():
            with get_ro_conn(auth_db) as aconn:
                auth_cnt = aconn.execute("SELECT COUNT(*) FROM authority_records").fetchone()[0]
                prec_cnt = aconn.execute("SELECT COUNT(*) FROM precedents").fetchone()[0]
        print(f"    - 母庫 MAX(rowid) 總規模      : {max_row:,} 筆")
        print(f"    - 憲法法庭/大法庭/會議/座談會 : {t1_cnt:,} 筆")
        print(f"    - 最高法院/最高行/智財商院    : {t2_cnt:,} 筆")
        print(f"    - 主要高等法院/高等行政法院   : {t3_cnt:,} 筆")
        print(f"    - 權威資料庫(釋字+憲判+判例)  : {auth_cnt + prec_cnt:,} 則 (將 100% 完整注入)")
        return output_path

    # 先清理舊輸出
    if output_path.exists():
        try:
            output_path.unlink()
        except Exception:
            pass

    out_conn = sqlite3.connect(str(output_path), timeout=60.0)
    out_conn.execute("PRAGMA journal_mode = MEMORY;")
    out_conn.execute("PRAGMA synchronous = OFF;")
    out_conn.execute("PRAGMA temp_store = MEMORY;")
    _create_core_schema(out_conn)

    # -------------------------------------------------------------------------
    # [1/4] 匯入 authority_records + authority_fts (同步 rowid)
    # -------------------------------------------------------------------------
    auth_imported = 0
    if auth_db and auth_db.exists():
        if verbose:
            print("[1/4] 正在自權威資料庫匯入憲法法庭判決、釋字與大法庭裁定...")
        with get_ro_conn(auth_db) as in_conn:
            rows = in_conn.execute("SELECT * FROM authority_records").fetchall()
            rec_batch = []
            fts_batch = []
            for idx, r in enumerate(rows, start=1):
                rd = dict(r)
                rec_batch.append((
                    idx,
                    rd.get("id"), rd.get("category") or "CONSTITUTIONAL", rd.get("sub_type") or "裁判",
                    rd.get("case_no") or "", rd.get("date") or "", rd.get("court") or "",
                    rd.get("title") or "", rd.get("holding") or "", rd.get("reasoning") or "",
                    rd.get("laws_cited") or "", rd.get("status") or "", rd.get("extra_meta") or ""
                ))
                fts_batch.append((
                    idx,
                    rd.get("id") or "", rd.get("case_no") or "", rd.get("title") or "",
                    rd.get("holding") or "", rd.get("reasoning") or "", rd.get("laws_cited") or ""
                ))
            out_conn.executemany("""
                INSERT INTO authority_records
                (rowid, id, category, sub_type, case_no, date, court, title, holding, reasoning, laws_cited, status, extra_meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rec_batch)
            out_conn.executemany("""
                INSERT INTO authority_fts (rowid, id, case_no, title, holding, reasoning, laws_cited)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, fts_batch)
            auth_imported = len(rec_batch)
        if verbose:
            print(f"    -> 成功注入權威憲法與大庭裁判: {auth_imported:,} 筆")

    # -------------------------------------------------------------------------
    # [2/4] 匯入 precedents + precedents_fts (同步 rowid)
    # -------------------------------------------------------------------------
    prec_imported = 0
    if auth_db and auth_db.exists():
        if verbose:
            print("[2/4] 正在自判例資料庫匯入最高法院經典判例要旨...")
        with get_ro_conn(auth_db) as in_conn:
            p_cols = {c[1] for c in in_conn.execute("PRAGMA table_info(precedents)").fetchall()}
            want_p_cols = [
                ("id", "id" if "id" in p_cols else "'' AS id"),
                ("precedent_id", "precedent_id" if "precedent_id" in p_cols else "'' AS precedent_id"),
                ("sys_type", "sys_type" if "sys_type" in p_cols else "'民事' AS sys_type"),
                ("case_no", "case_no" if "case_no" in p_cols else "'' AS case_no"),
                ("year", "year" if "year" in p_cols else "'' AS year"),
                ("court", "court" if "court" in p_cols else "'最高法院' AS court"),
                ("title", "title" if "title" in p_cols else "'' AS title"),
                ("holding", "holding" if "holding" in p_cols else "'' AS holding"),
                ("reasoning", "substr(COALESCE(reasoning,''), 1, 1500) AS reasoning" if "reasoning" in p_cols else "'' AS reasoning"),
                ("laws_cited", "laws_cited" if "laws_cited" in p_cols else "'' AS laws_cited"),
                ("status", "status" if "status" in p_cols else "'' AS status"),
                ("subject", "subject" if "subject" in p_cols else "'' AS subject"),
                ("sub_category", "sub_category" if "sub_category" in p_cols else "'' AS sub_category"),
                ("date", "date" if "date" in p_cols else "'' AS date"),
                ("extra_meta", "extra_meta" if "extra_meta" in p_cols else "'' AS extra_meta"),
                ("abolition_note", "abolition_note" if "abolition_note" in p_cols else "'' AS abolition_note"),
                ("source_url", "source_url" if "source_url" in p_cols else "'' AS source_url"),
            ]
            p_sql = "SELECT " + ", ".join(expr for _, expr in want_p_cols) + " FROM precedents"
            rows = in_conn.execute(p_sql).fetchall()
            p_batch = []
            p_fts_batch = []
            seen_pids: Set[str] = set()
            row_idx = 0
            for r in rows:
                p_id = str(r["id"] or r["precedent_id"] or r["case_no"] or "").strip()
                if not p_id or p_id in seen_pids:
                    continue
                seen_pids.add(p_id)
                row_idx += 1
                c_no = str(r["case_no"] or r["precedent_id"] or p_id).strip()
                reasoning_txt = (r["reasoning"] or "")[:1500]
                p_batch.append((
                    row_idx, p_id, r["precedent_id"] or p_id,
                    r["sys_type"] or "民事", c_no, r["year"] or "",
                    r["court"] or "最高法院", r["title"] or "", r["holding"] or "",
                    reasoning_txt, r["laws_cited"] or "", r["status"] or "",
                    r["subject"] or "", r["sub_category"] or "", r["date"] or "",
                    r["extra_meta"] or "", r["abolition_note"] or "", r["source_url"] or ""
                ))
                p_fts_batch.append((
                    row_idx, p_id, c_no, r["title"] or "", r["holding"] or "",
                    reasoning_txt, r["laws_cited"] or ""
                ))
            out_conn.executemany("""
                INSERT INTO precedents
                (rowid, id, precedent_id, sys_type, case_no, year, court, title, holding, reasoning, laws_cited, status, subject, sub_category, date, extra_meta, abolition_note, source_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, p_batch)
            out_conn.executemany("""
                INSERT INTO precedents_fts (rowid, id, case_no, title, holding, reasoning, laws_cited)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, p_fts_batch)
            prec_imported = len(p_batch)
        if verbose:
            print(f"    -> 成功注入最高法院經典判例要旨: {prec_imported:,} 筆 ({time.time() - t_start:.1f}s)")

    # -------------------------------------------------------------------------
    # [3/4] 自 Total 母庫進行分層索引精萃 (judgments_meta + judgments_fts)
    # -------------------------------------------------------------------------
    if verbose:
        print("[3/4] 正在自 Total 母庫依審級與爭點分層精萃實務裁判...")

    seen_case_ids: Set[str] = set()
    extracted_rows: List[Tuple[Any, ...]] = []

    def _score_and_add(rows_iter, limit_remaining: Optional[int] = None, min_preview_len: int = 15) -> int:
        added = 0
        for r in rows_iter:
            if limit_remaining is not None and added >= limit_remaining:
                break
            cid = str(r["case_id"] or "").strip()
            if not cid or cid in seen_case_ids:
                continue
            hp = (r["holding_preview"] or "").strip()
            if len(hp) < min_preview_len and (r["court"] not in TIER1_COURTS):
                continue
            seen_case_ids.add(cid)
            extracted_rows.append((
                cid,
                r["jid"] or cid,
                r["court"] or "",
                r["level"] or "",
                r["case_type"] or "",
                r["subject"] or "",
                r["jud_year"] or "",
                r["jud_word"] or "",
                r["jud_no"] or "",
                r["date"] or "",
                (r["title"] or "")[:300],
                (r["laws_cited"] or "")[:1200],
                (r["issue"] or "")[:600],
                hp[:800],
                r["shard_key"] or "",
                r["has_legal_issue"] if r["has_legal_issue"] is not None else 1,
                (r["history_instances"] or "")[:1000],
                (r["substantive_prior"] or "")[:120],
                (r["history_cases"] or "")[:1000],
            ))
            added += 1
        return added

    with get_ro_conn(total_db) as in_conn:
        avail_cols = {c[1] for c in in_conn.execute("PRAGMA table_info(judgments_meta)").fetchall()}
        cols_expr = _select_meta_columns_expr(avail_cols)
        has_li_filter = "(has_legal_issue IS NULL OR has_legal_issue = 1)" if "has_legal_issue" in avail_cols else "1=1"

        # Tier 1A: 憲法法庭 / 大法官 / 大法庭 / 最高院庭會議 / 高院座談會 (100%)
        ph_t1 = ",".join("?" for _ in TIER1_COURTS)
        t1_rows = in_conn.execute(
            f"SELECT {cols_expr} FROM judgments_meta WHERE court IN ({ph_t1})", TIER1_COURTS
        ).fetchall()
        t1a_cnt = _score_and_add(t1_rows, min_preview_len=0)

        # Tier 1B: 最高法院與最高行政法院大法庭 / 徵詢庭 (108~115 年全數大字案件)
        ph_gw = ",".join("?" for _ in GRAND_WORDS)
        t1b_cnt = 0
        for yr in ("115", "114", "113", "112", "111", "110", "109", "108"):
            gw_rows = in_conn.execute(
                f"SELECT {cols_expr} FROM judgments_meta WHERE jud_year = ? AND jud_word IN ({ph_gw})",
                (yr, *GRAND_WORDS)
            ).fetchall()
            t1b_cnt += _score_and_add(gw_rows, min_preview_len=0)

        if verbose:
            print(f"    -> Tier 1 (憲法/大法庭/會議/座談會): {t1a_cnt + t1b_cnt:,} 筆")

        # Tier 2: 最高法院、最高行政法院、智慧財產及商業法院 (~65% 剩餘配額，全數走精準索引)
        rem_total = max(0, target_cap - len(extracted_rows))
        t2_quota = int(rem_total * 0.65)
        t2_collected = 0
        ph_sw = ",".join("?" for _ in SUPREME_EXCLUSIVE_WORDS)

        # 2A. 最高行政法院與智慧財產及商業法院 (直接走 idx_meta_court_type + LIMIT)
        sup_admin_quota = max(1000, int(t2_quota * 0.15))
        ip_quota = max(500, int(t2_quota * 0.08))
        for court_name, c_quota in (("最高行政法院", sup_admin_quota), ("智慧財產及商業法院", ip_quota)):
            if t2_collected >= t2_quota:
                break
            take = min(c_quota, t2_quota - t2_collected)
            c_rows = in_conn.execute(
                f"""
                SELECT {cols_expr} FROM judgments_meta INDEXED BY idx_meta_court_type
                WHERE court = ?
                  AND {has_li_filter}
                  AND holding_preview IS NOT NULL AND length(trim(holding_preview)) >= 35
                LIMIT ?
                """,
                (court_name, int(take * 1.4))
            ).fetchall()
            t2_collected += _score_and_add(c_rows, limit_remaining=take, min_preview_len=35)

        # 2B. 最高法院近年實質字別 (台上/台抗/台簡上/台再 — 100% 專屬於最高法院，絕無地院雜訊)
        for yr in RECENT_YEARS_SUPREME:
            if t2_collected >= t2_quota:
                break
            need = min(t2_quota - t2_collected, 2200)
            cand_rows = in_conn.execute(
                f"""
                SELECT {cols_expr} FROM judgments_meta INDEXED BY idx_meta_ywn
                WHERE jud_year = ? AND jud_word IN ({ph_sw})
                  AND court = '最高法院'
                  AND {has_li_filter}
                  AND holding_preview IS NOT NULL AND length(trim(holding_preview)) >= 30
                LIMIT ?
                """,
                (yr, *SUPREME_EXCLUSIVE_WORDS, int(need * 1.3))
            ).fetchall()
            cand_sorted = sorted(
                cand_rows,
                key=lambda x: (1 if (x["laws_cited"] or "").strip() else 0, 1 if (x["issue"] or "").strip() else 0),
                reverse=True
            )
            t2_collected += _score_and_add(cand_sorted, limit_remaining=need, min_preview_len=30)

        # 2C. 若仍有剩餘最高法院配額，走 court='最高法院' 索引補足
        if t2_collected < t2_quota:
            need = t2_quota - t2_collected
            fallback_rows = in_conn.execute(
                f"""
                SELECT {cols_expr} FROM judgments_meta INDEXED BY idx_meta_court_type
                WHERE court = '最高法院'
                  AND {has_li_filter}
                  AND holding_preview IS NOT NULL AND length(trim(holding_preview)) >= 35
                LIMIT ?
                """,
                (int(need * 1.4),)
            ).fetchall()
            t2_collected += _score_and_add(fallback_rows, limit_remaining=need, min_preview_len=35)

        if verbose:
            print(f"    -> Tier 2 (最高法院/最高行/智財商院): {t2_collected:,} 筆")

        # Tier 3: 高等法院與高等行政法院 (~35% 剩餘配額，直接走 idx_meta_court_type + LIMIT)
        t3_quota = max(0, target_cap - len(extracted_rows))
        t3_collected = 0
        for hc_name, ratio in HIGH_COURT_WEIGHTS:
            if t3_collected >= t3_quota:
                break
            hc_need = min(max(300, int(t3_quota * ratio)), t3_quota - t3_collected)
            hc_rows = in_conn.execute(
                f"""
                SELECT {cols_expr} FROM judgments_meta INDEXED BY idx_meta_court_type
                WHERE court = ?
                  AND {has_li_filter}
                  AND holding_preview IS NOT NULL AND length(trim(holding_preview)) >= 35
                LIMIT ?
                """,
                (hc_name, int(hc_need * 1.2))
            ).fetchall()
            hc_sorted = sorted(
                hc_rows,
                key=lambda x: (1 if (x["laws_cited"] or "").strip() else 0, 1 if (x["issue"] or "").strip() else 0),
                reverse=True
            )
            t3_collected += _score_and_add(hc_sorted, limit_remaining=hc_need, min_preview_len=35)
            if verbose:
                print(f"       · {hc_name}: 累計 Tier 3 {t3_collected:,} 筆 ({time.time() - t_start:.1f}s)")

        if t3_collected < t3_quota:
            need = t3_quota - t3_collected
            fallback_t3 = in_conn.execute(
                f"""
                SELECT {cols_expr} FROM judgments_meta INDEXED BY idx_meta_court_type
                WHERE court = '臺灣高等法院'
                  AND {has_li_filter}
                  AND holding_preview IS NOT NULL AND length(trim(holding_preview)) >= 35
                LIMIT ?
                """,
                (int(need * 1.2),)
            ).fetchall()
            t3_collected += _score_and_add(fallback_t3, limit_remaining=need, min_preview_len=35)

        if verbose:
            print(f"    -> Tier 3 (高等法院/高等行政法院)  : {t3_collected:,} 筆 ({time.time() - t_start:.1f}s)")

        # Redirects subset linking into extracted core judgments
        redirects_batch: List[Tuple[str, str, str, str]] = []
        has_redir_tbl = bool(
            in_conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='judgment_redirects'").fetchone()
        )
        if has_redir_tbl and seen_case_ids:
            try:
                cur_red = in_conn.execute(
                    "SELECT dismissed_case_id, substantive_prior_id, discard_reason, court FROM judgment_redirects LIMIT 100000"
                )
                for rr in cur_red:
                    sp_id = rr["substantive_prior_id"] or ""
                    if sp_id in seen_case_ids:
                        redirects_batch.append((
                            rr["dismissed_case_id"], sp_id, rr["discard_reason"] or "", rr["court"] or ""
                        ))
                    if len(redirects_batch) >= 15000:
                        break
            except Exception:
                pass
        if verbose:
            print(f"    -> Redirects (程序駁回關聯對應)   : {len(redirects_batch):,} 筆")

    # 批次寫入 judgments_meta & judgments_fts (同步 rowid)
    meta_insert_batch = []
    fts_insert_batch = []
    for idx, row_t in enumerate(extracted_rows, start=1):
        meta_insert_batch.append((idx, *row_t))
        fts_insert_batch.append((idx, row_t[0], row_t[10], row_t[13], row_t[12], row_t[11]))

    out_conn.executemany("""
        INSERT INTO judgments_meta
        (rowid, case_id, jid, court, level, case_type, subject, jud_year, jud_word, jud_no, date,
         title, laws_cited, issue, holding_preview, shard_key, has_legal_issue,
         history_instances, substantive_prior, history_cases)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, meta_insert_batch)
    out_conn.executemany("""
        INSERT INTO judgments_fts (rowid, case_id, title, holding_preview, issue, laws_cited)
        VALUES (?, ?, ?, ?, ?, ?)
    """, fts_insert_batch)

    if redirects_batch:
        out_conn.executemany("""
            INSERT OR IGNORE INTO judgment_redirects (dismissed_case_id, substantive_prior_id, discard_reason, court)
            VALUES (?, ?, ?, ?)
        """, redirects_batch)

    jud_extracted = len(extracted_rows)

    # -------------------------------------------------------------------------
    # [4/4] Manifest & VACUUM / GZIP
    # -------------------------------------------------------------------------
    manifest_data = {
        "version": "2.0.0-exam-core",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "authority_count": auth_imported,
        "precedents_count": prec_imported,
        "judgments_count": jud_extracted,
        "redirects_count": len(redirects_batch),
        "total_legal_assets": auth_imported + prec_imported + jud_extracted,
    }
    for k, v in manifest_data.items():
        out_conn.execute("INSERT OR REPLACE INTO core_manifest (key, value) VALUES (?, ?)", (k, str(v)))

    out_conn.commit()
    out_conn.execute("PRAGMA optimize;")
    out_conn.close()

    if verbose:
        print("\n[*] 正在執行 SQLite VACUUM 緊實化...")
    vac_conn = sqlite3.connect(str(output_path))
    vac_conn.execute("VACUUM;")
    vac_conn.close()

    final_size_mb = output_path.stat().st_size / (1024 * 1024)
    gz_path = Path(str(output_path) + ".gz")
    gz_size_mb = 0.0
    if gzip_output:
        with open(output_path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=9) as f_out:
            shutil.copyfileobj(f_in, f_out, length=1024 * 1024)
        gz_size_mb = gz_path.stat().st_size / (1024 * 1024)

    t_end = time.time()
    if verbose:
        print("\n=================================================================")
        print("[🎉] 核心精華子庫提煉完成！")
        print(f"[*] 產出子庫檔案   : {output_path}")
        print(f"[*] 未壓縮容量     : {final_size_mb:.2f} MB")
        if gzip_output:
            print(f"[*] GZIP 壓縮版    : {gz_path} ({gz_size_mb:.2f} MB)")
        print(f"[*] 總納入法學資產 : {manifest_data['total_legal_assets']:,} 筆")
        print(f"    - 憲判字與釋字 : {auth_imported:,} 則")
        print(f"    - 經典判例要旨 : {prec_imported:,} 則")
        print(f"    - 實務精萃裁判 : {jud_extracted:,} 筆")
        print(f"    - 程序導向對照 : {len(redirects_batch):,} 筆")
        print(f"[*] 總執行耗時     : {t_end - t_start:.2f} 秒")
        print("=================================================================")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="從 Total 百萬裁判母庫提煉司律考試核心子庫 (judicial_exam_core.db)")
    parser.add_argument("-t", "--total-db", type=str, default="", help="Total 百萬母庫路徑 (預設自動偵測 judicial_1m_index.db)")
    parser.add_argument("-a", "--auth-db", type=str, default="", help="權威判例母庫路徑 (預設自動偵測 judicial_authority.db)")
    parser.add_argument("-o", "--output", type=str, default="", help="輸出之核心子庫路徑 (預設 data/judicial_exam_core.db)")
    parser.add_argument("-m", "--max-judgments", type=int, default=35000, help="最多萃取之實務裁判上限 (預設 35000；0 = 100000 旗艦配額)")
    parser.add_argument("--dry-run", action="store_true", help="乾跑模式：僅統計母庫可萃取筆數，不實際產生檔案")
    parser.add_argument("--gzip", action="store_true", help="同步產生 .db.gz 高壓縮包供 Streamlit Cloud / Git 使用")
    args = parser.parse_args()

    export_exam_core_database(
        total_db_path=Path(args.total_db) if args.total_db else None,
        auth_db_path=Path(args.auth_db) if args.auth_db else None,
        output_path=Path(args.output) if args.output else None,
        max_judgments=args.max_judgments,
        dry_run=args.dry_run,
        gzip_output=args.gzip,
    )


if __name__ == "__main__":
    main()
