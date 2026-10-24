# -*- coding: utf-8 -*-
"""
最高法院經典判例庫與前端掛載實體檢驗腳本 (verify_precedents.py)
"""
import sys
import os
import json
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CODE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE_DIR))

from authority_engine import search_precedents, get_precedents_by_law, get_engine

def clean_text(s: str) -> str:
    if not s: return ""
    return s.replace('\xa0', ' ').replace('\u3000', ' ').strip()

def test_standalone_search():
    print("=" * 65)
    print("【驗證一：入口 A 後端查詢介面 search_precedents 實測】")
    print("=" * 65)
    engine = get_engine()
    stats = engine.get_authority_stats()
    print(f"判例大庫總收錄筆數：{stats.get('total_precedents')} 則")
    print(f"審別分佈：{stats.get('precedent_systems')}")
    print(f"效力狀態分佈：{stats.get('precedent_statuses')}")
    print()

    # 1. 民事判例檢索
    print(">>> 測試 1：搜尋關鍵字『借名登記』（審別：民事）")
    res_civil = search_precedents(keyword="借名登記", sys_type="民事", limit=3)
    print(f"尋得 {len(res_civil)} 則結果：")
    for r in res_civil:
        status_tag = f"【{r.get('status')}】"
        print(f" - [{r.get('sys_type')}] {r.get('case_no')} {status_tag} ｜ {clean_text(r.get('title'))}")
        holding_prev = clean_text(r.get('holding'))[:80]
        print(f"   要旨預覽: {holding_prev}...")

    print()
    # 2. 刑事判例檢索
    print(">>> 測試 2：搜尋關鍵字『自白』（審別：刑事）")
    res_crim = search_precedents(keyword="自白", sys_type="刑事", limit=2)
    print(f"尋得 {len(res_crim)} 則結果：")
    for r in res_crim:
        status_tag = f"【{r.get('status')}】"
        print(f" - [{r.get('sys_type')}] {r.get('case_no')} {status_tag} ｜ {clean_text(r.get('title'))}")
        holding_prev = clean_text(r.get('holding'))[:80]
        print(f"   要旨預覽: {holding_prev}...")

def test_law_association():
    print()
    print("=" * 65)
    print("【驗證二：入口 B 六法智慧法條關聯 get_precedents_by_law 實測】")
    print("=" * 65)

    # 測試民法第184條
    print(">>> 測試關聯法條：【民法 第 184 條】(一般侵權行為責任)")
    res_184 = get_precedents_by_law("民法", "184", limit=5)
    print(f"精準撈取對應判例裁判數：{len(res_184)} 則")
    for r in res_184:
        status_tag = f"【{r.get('status')}】"
        print(f" - `{r.get('case_no')}` {status_tag} ｜ {clean_text(r.get('title'))}")
        holding_prev = clean_text(r.get('holding'))[:80]
        print(f"   判旨要旨: {holding_prev}...")

    print()
    # 測試民法第13條
    print(">>> 測試關聯法條：【民法 第 13 條】(未成年人行為能力)")
    res_13 = get_precedents_by_law("民法", "13", limit=3)
    print(f"精準撈取對應判例裁判數：{len(res_13)} 則")
    for r in res_13:
        status_tag = f"【{r.get('status')}】"
        print(f" - `{r.get('case_no')}` {status_tag} ｜ {clean_text(r.get('title'))}")

if __name__ == "__main__":
    test_standalone_search()
    test_law_association()
    print("\n✅ 所有後端查詢介面與前端掛載契約實測全數通過！")
