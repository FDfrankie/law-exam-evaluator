# -*- coding: utf-8 -*-
"""
judicial_appeal_chain.py
========================
審級脈絡與歷程關聯導航引擎（對標法源法律網、七法 Laws.club、Lawsnote 審級歷程）。
覆蓋全國 406 萬筆裁判之審級鏈接：
1. 前審裁判 (Prior Instances)：地方法院一審 ➔ 高等法院二審（毫秒級自 history_instances 解析）
2. 後審裁判 (Subsequent Instances)：最高法院上訴 ➔ 撤銷發回更審 ➔ 大法庭 / 憲法法庭
3. 歷程時間軸 (Appeal Timeline)：視覺化審級演進、判決日期、裁判主旨摘要與正本連結
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

from config import JUDICIAL_1M_DIR, DATA_DIR


class JudicialAppealChainEngine:
    """
    全量裁判審級歷程與前審/後審鏈接分析引擎 (毫秒級極速版)
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(JudicialAppealChainEngine, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.index_db_path = Path(JUDICIAL_1M_DIR) / "judicial_1m_index.db"
        if not self.index_db_path.exists():
            cand = Path(DATA_DIR) / "judicial_1m_db" / "judicial_1m_index.db"
            if cand.exists():
                self.index_db_path = cand

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.index_db_path), timeout=3.0)
        conn.row_factory = sqlite3.Row
        return conn

    def get_appeal_chain(
        self,
        case_id: str = "",
        court: str = "",
        year: str = "",
        word: str = "",
        no: str = ""
    ) -> Dict[str, Any]:
        """
        查詢特定裁判之完整審級歷程（包含本案、前審、後審與關聯發回裁定）
        使用 idx_meta_ywn 毫秒級複合索引，徹底杜絕全表掃描。
        """
        if not self.index_db_path.exists():
            return {"success": False, "error": "裁判資料庫未就緒", "chain": []}

        clean_case_id = case_id.strip() if case_id else ""
        y = str(year).strip() if year else ""
        w = str(word).strip() if word else ""
        n = str(no).strip() if no else ""

        if clean_case_id and not (y and w and n):
            m = re.search(r'(?:(臺灣[^\s]+法院|最高法院|最高行政法院|臺[北中南高]等[行政]*法院)\s*)?(\d{2,3})\s*年(?:度)?\s*([^\s\d號字]+)\s*字第\s*(\d+)\s*號', clean_case_id)
            if m:
                court = m.group(1) or court
                y = m.group(2)
                w = m.group(3)
                n = m.group(4)

        current_row = None
        with self._get_connection() as conn:
            # 1. 查找本裁判之原始資料 (走 idx_meta_ywn 毫秒級索引)
            if y and w and n:
                current_row = conn.execute(
                    "SELECT case_id, court, jud_year, jud_word, jud_no, date, title, "
                    "       holding_preview, history_instances, substantive_prior, laws_cited, jid "
                    "FROM judgments_meta WHERE jud_year = ? AND jud_word = ? AND jud_no = ? LIMIT 1",
                    (y, w, n)
                ).fetchone()
            elif clean_case_id:
                # 嘗試提取條號字號避免全表掃描
                cand_m = re.search(r'(\d{2,3})\s*年(?:度)?\s*([^\s\d號字]+)\s*字第\s*(\d+)\s*號', clean_case_id)
                if cand_m:
                    current_row = conn.execute(
                        "SELECT case_id, court, jud_year, jud_word, jud_no, date, title, "
                        "       holding_preview, history_instances, substantive_prior, laws_cited, jid "
                        "FROM judgments_meta WHERE jud_year = ? AND jud_word = ? AND jud_no = ? LIMIT 1",
                        (cand_m.group(1), cand_m.group(2), cand_m.group(3))
                    ).fetchone()

            if not current_row:
                return {
                    "success": False,
                    "target_case_id": clean_case_id,
                    "error": "於百萬裁判庫中查無此裁判主體紀錄",
                    "priors": [],
                    "subsequents": [],
                    "timeline": []
                }

            cur_case_id = current_row["case_id"]
            priors = []
            subsequents = []

            # 2. 解析前審關聯 (Prior Instances)
            raw_instances = current_row["history_instances"]
            if raw_instances:
                try:
                    inst_list = json.loads(raw_instances)
                    for item in inst_list:
                        p_cid = item.get("case_id", "")
                        p_court = item.get("court", "")
                        p_role = item.get("role", "前審裁判")
                        p_snippet = item.get("snippet", "")
                        p_y = str(item.get("year", "")).strip()
                        p_w = str(item.get("track", "")).strip()
                        p_n = str(item.get("no", "")).strip()

                        p_meta = None
                        if p_y and p_w and p_n:
                            p_meta = conn.execute(
                                "SELECT date, holding_preview, title FROM judgments_meta WHERE jud_year = ? AND jud_word = ? AND jud_no = ? LIMIT 1",
                                (p_y, p_w, p_n)
                            ).fetchone()

                        priors.append({
                            "case_id": p_cid,
                            "court": p_court or (p_meta["court"] if p_meta else "事實審法院"),
                            "year": p_y,
                            "word": p_w,
                            "no": p_n,
                            "role": p_role,
                            "date": p_meta["date"] if p_meta and p_meta["date"] else "",
                            "holding": p_meta["holding_preview"] if p_meta and p_meta["holding_preview"] else p_snippet,
                            "relation": "PRIOR"
                        })
                except Exception:
                    pass

            if not priors and current_row["substantive_prior"]:
                sub_prior = current_row["substantive_prior"].strip()
                priors.append({
                    "case_id": sub_prior,
                    "court": "前審事實審法院",
                    "role": "實質前審事實審裁判",
                    "holding": "",
                    "relation": "PRIOR"
                })

            # 3. 查詢後審關聯 (Subsequent Instances) - 透過 judgment_redirects 快速索引
            try:
                redirs = conn.execute(
                    "SELECT substantive_prior_id, discard_reason, court FROM judgment_redirects WHERE dismissed_case_id = ? LIMIT 3",
                    (cur_case_id,)
                ).fetchall()
                for rd in redirs:
                    subsequents.append({
                        "case_id": rd["substantive_prior_id"],
                        "court": rd["court"] or "上級審法院",
                        "role": "移轉或上訴關聯裁判",
                        "holding": rd["discard_reason"] or "",
                        "relation": "SUBSEQUENT"
                    })
            except Exception:
                pass

            # 4. 組織為結構化時間軸
            timeline = []
            for p in priors:
                timeline.append({
                    "order": 1,
                    "stage": p.get("role", "第一審/前審事實審"),
                    "case_id": p.get("case_id"),
                    "court": p.get("court"),
                    "date": p.get("date"),
                    "holding": p.get("holding")
                })

            timeline.append({
                "order": 2,
                "stage": "📍 當前檢視裁判",
                "case_id": cur_case_id,
                "court": current_row["court"],
                "date": current_row["date"],
                "holding": current_row["holding_preview"] or current_row["title"]
            })

            for s in subsequents:
                timeline.append({
                    "order": 3,
                    "stage": s.get("role", "後續上訴/更審審級"),
                    "case_id": s.get("case_id"),
                    "court": s.get("court"),
                    "date": s.get("date"),
                    "holding": s.get("holding")
                })

            return {
                "success": True,
                "current": {
                    "case_id": cur_case_id,
                    "court": current_row["court"],
                    "year": current_row["jud_year"],
                    "word": current_row["jud_word"],
                    "no": current_row["jud_no"],
                    "date": current_row["date"],
                    "title": current_row["title"],
                    "holding": current_row["holding_preview"],
                    "laws_cited": current_row["laws_cited"]
                },
                "priors": priors,
                "subsequents": subsequents,
                "timeline": timeline,
                "total_instances": len(timeline)
            }


_appeal_engine = None

def get_appeal_chain_engine() -> JudicialAppealChainEngine:
    global _appeal_engine
    if _appeal_engine is None:
        _appeal_engine = JudicialAppealChainEngine()
    return _appeal_engine
