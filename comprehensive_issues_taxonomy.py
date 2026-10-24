# -*- coding: utf-8 -*-
"""
code/comprehensive_issues_taxonomy.py
千級全量法學爭點資料庫架構與延遲加載（Lazy Load）API

支援 7 大學門：
1. 民事財產與身分法 (民法總則、債編、物權編、親屬繼承編、民法實體大典)
2. 刑事實體法 (刑法總則、刑法分則、中華民國刑法全典)
3. 公法專題 (憲法與憲法訴訟、行政法實體與程序)
4. 民事程序法 (民事訴訟法、家事事件法與強制執行法)
5. 刑事程序法 (刑事訴訟法、國民法官法)
6. 商事法專題 (公司法、證券交易法、保險法)
7. 智慧財產權法專題 (專利法、商標法、著作權法、營業秘密法)

架構特色：
- 延遲加載（Lazy Loading）自 data/statute_issues_massive.json，避免龐大資料常駐記憶體與前端卡頓。
- 完整提供四級下鑽 API：學門 ➔ 法典 ➔ 編章專題 ➔ 節次/條文 ➔ 具體考點清單。
- 全庫支援 14,000+ 個具備實務字號、學說肯否二說與 IRAC 考點之具體爭點。
"""

import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

# Windows 終端編碼防護
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from config import DATA_DIR
    BASE_DATA_DIR = Path(DATA_DIR)
except Exception:
    BASE_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_MASSIVE_TAXONOMY_CACHE: Optional[Dict[str, Any]] = None


def _load_massive_taxonomy() -> Dict[str, Any]:
    """延遲加載大型爭點 JSON 資料庫，具備多重後備路徑機制"""
    global _MASSIVE_TAXONOMY_CACHE
    if _MASSIVE_TAXONOMY_CACHE is not None:
        return _MASSIVE_TAXONOMY_CACHE

    candidate_paths = [
        BASE_DATA_DIR / "statute_issues_massive.json",
        Path(__file__).resolve().parent.parent / "data" / "statute_issues_massive.json",
        Path(__file__).resolve().parent / "data" / "statute_issues_massive.json",
        Path(r"G:\我的雲端硬碟\LawExamData\data\statute_issues_massive.json"),
        Path(r"G:\我的雲端硬碟\LawExamData\statute_issues_massive.json")
    ]

    for p in candidate_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    _MASSIVE_TAXONOMY_CACHE = json.load(f)
                return _MASSIVE_TAXONOMY_CACHE
            except Exception as e:
                print(f"[Taxonomy] 載入 {p} 失敗: {e}")

    # 若尚未建置實體 JSON，由建置模組動態建置或調用預設
    try:
        from build_massive_issues_db import build_massive_taxonomy
        _MASSIVE_TAXONOMY_CACHE = build_massive_taxonomy()
        return _MASSIVE_TAXONOMY_CACHE
    except Exception as e_gen:
        print(f"[Taxonomy] 動態建置失敗: {e_gen}")
        _MASSIVE_TAXONOMY_CACHE = {}
        return _MASSIVE_TAXONOMY_CACHE


def get_available_domains() -> List[str]:
    """回傳所有可用的法學大領域清單（7大學門）"""
    db = _load_massive_taxonomy()
    if db:
        return list(db.keys())
    return [
        "民事財產與身分法",
        "刑事實體法",
        "公法專題",
        "民事程序法",
        "刑事程序法",
        "商事法專題",
        "智慧財產權法專題"
    ]


def get_statutes_by_domain(domain: str) -> List[str]:
    """回傳指定學門轄下之法典/科目清單"""
    db = _load_massive_taxonomy()
    if domain in db and isinstance(db[domain], dict):
        return list(db[domain].keys())
    return []


def get_chapters(domain: str, statute: str) -> List[str]:
    """回傳指定法典轄下之編次或大章/專題清單"""
    db = _load_massive_taxonomy()
    if (
        domain in db
        and isinstance(db[domain], dict)
        and statute in db[domain]
        and isinstance(db[domain][statute], dict)
    ):
        return list(db[domain][statute].keys())
    return []


def get_sections(domain: str, statute: str, chapter: str) -> List[str]:
    """回傳指定編章轄下之節次或條文專題清單"""
    db = _load_massive_taxonomy()
    if (
        domain in db
        and statute in db[domain]
        and chapter in db[domain][statute]
    ):
        target = db[domain][statute][chapter]
        if isinstance(target, dict):
            return list(target.keys())
        elif isinstance(target, list):
            return ["本單元焦點爭點"]
    return []


def get_issues(domain: str, statute: str, chapter: str, section: str = "") -> List[str]:
    """回傳指定節/條文之核心實務與學說爭點清單"""
    db = _load_massive_taxonomy()
    if (
        domain in db
        and statute in db[domain]
        and chapter in db[domain][statute]
    ):
        target = db[domain][statute][chapter]
        if isinstance(target, dict):
            if section and section in target:
                val = target[section]
                return val if isinstance(val, list) else []
            # 若無特別指定 section，彙整該 chapter 所有 sections 的爭點
            all_iss = []
            for sec_name, iss_list in target.items():
                if isinstance(iss_list, list):
                    all_iss.extend(iss_list)
            return all_iss
        elif isinstance(target, list):
            return target
    return []


def get_massive_taxonomy_chapters(domain: str, subject: str) -> List[str]:
    """相容規範別名：取得特定科目的體系編章清單"""
    return get_chapters(domain, subject)


def get_massive_issues_by_section(domain: str, subject: str, chapter: str, section: str = "") -> Dict[str, str]:
    """
    相容規範別名：依編章節精準回傳該單元專屬之核心考點爭點對照表 {爭點名稱: 詳細考點說明}
    """
    issues_list = get_issues(domain, subject, chapter, section)
    res_map = {}
    for idx, iss in enumerate(issues_list, 1):
        key = f"【考點 {idx}】{iss[:35]}"
        res_map[key] = iss
    return res_map


def get_all_issues_flat_for_subject(subject_query: str) -> Dict[str, str]:
    """
    相容舊版介面：若需要快速攤平某科目的所有爭點對照表，回傳 {爭點標題: 說明}
    """
    db = _load_massive_taxonomy()
    flat_map = {}
    q = subject_query.strip()
    
    for d, statutes in db.items():
        if not isinstance(statutes, dict):
            continue
        for st_name, chapters in statutes.items():
            if q in st_name or st_name in q or (q and q in d):
                if not isinstance(chapters, dict):
                    continue
                for ch_name, sections in chapters.items():
                    if isinstance(sections, dict):
                        for sec_name, issues in sections.items():
                            if isinstance(issues, list):
                                for iss in issues:
                                    label = f"【{st_name}・{sec_name}】{iss[:30]}"
                                    flat_map[label] = f"【{ch_name} / {sec_name}】{iss}"
                    elif isinstance(sections, list):
                        for iss in sections:
                            label = f"【{st_name}・{ch_name}】{iss[:30]}"
                            flat_map[label] = f"【{ch_name}】{iss}"
    return flat_map
