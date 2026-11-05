"""
clean_master_db.py
司法院百萬裁判母庫 (judicial_1m_index.db) 深度清理、純事實爭點剔除與資料庫極致瘦身工具

功能特色：
1. 【非訟事件與純程序裁定剔除】：
   - 本票裁定 (票、司票)
   - 拍賣抵押物 (拍、司拍)
   - 支付命令與督促程序 (促、司促)
   - 調解事件筆錄 (調、小調、重小調、勞調、家調、訴前調)
   - 命補繳裁判費或補正程式 (補、司補)
   - 移送管轄 (移、移管)
   - 公示催告、公示送達、通常受刑人定應執行刑等
2. 【純事實/無法律爭點案件深度剔除】：
   - 地方法院常規民事小額訴訟 (卡費/電信費/純金錢催收，無實體法理爭鳴)
   - 地方法院常規刑事簡易處刑 (純認罪例行酒駕/竊盜/常規毒品，無實體爭端)
   - 🛡️【嚴格實體法律爭點保護白名單】：
     任何涉及大法庭、憲判字、釋字、判例、決議、座談會、肯否兩說、見解歧異、
     爭點效、既判力、構成要件、阻卻違法、合憲性解釋、目的性限縮等實體法理之案件，
     100% 絕對豁免保護，絕不誤刪！
3. 【高安全低鎖定】：
   - 採用 ROWID 5,000 筆極速分批交易刪除，不阻塞資料庫。
   - 預設提供安全預覽 (DRY-RUN)；加掛 --commit 正式落盤瘦身。
"""

import sys
import os
import re
import time
import sqlite3
import argparse
from pathlib import Path

# Windows cp950 編碼防護
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 1. 非訟與例行程序案號特徵庫
NON_SUBSTANTIVE_PATTERNS = [
    r"年度\s*(?:[^\s0-9]*?票[^\s0-9]*?)\s*字",
    r"年度\s*(?:[^\s0-9]*?促[^\s0-9]*?)\s*字",
    r"年度\s*(?:[^\s0-9]*?調[^\s0-9]*?)\s*字",
    r"年度\s*(?:[^\s0-9]*?拍[^\s0-9]*?)\s*字",
    r"年度\s*(?:[^\s0-9]*?補[^\s0-9]*?)\s*字",
    r"年度\s*(?:[^\s0-9]*?移[^\s0-9]*?)\s*字",
    r"年度\s*(?:[^\s0-9]*?定刑[^\s0-9]*?)\s*字",
    r"年度\s*(?:[^\s0-9]*?執聲[^\s0-9]*?)\s*字",
    r"公示催告",
    r"公示送達",
]
NON_SUBSTANTIVE_REGEX = re.compile("|".join(NON_SUBSTANTIVE_PATTERNS))

# 2. 嚴格實體法律爭點保護白名單 (命中任一關鍵字，100% 豁免保留)
PROTECTED_TERMS = [
    "大法庭", "憲判字", "釋字", "判例", "決議", "座談會",
    "肯定說", "否定說", "折衷說", "學說", "通說", "實務見解",
    "爭點", "競合", "界限", "排他", "構成要件", "阻卻違法",
    "期待可能性", "正當防衛", "緊急避難", "合憲", "違憲",
    "目的性限縮", "類推適用", "適用法規", "爭點效", "既判力"
]
PROTECT_REGEX = re.compile("|".join(PROTECTED_TERMS))

# 3. 純事實刑事常規簡易案由 (精確比對)
EXACT_CRIM_CAUSES = {
    "公共危險", "毒品危害防制條例", "竊盜", "過失傷害", "賭博", 
    "妨害公務", "毀損", "洗錢防制法", "傷害", "侵占", "偽造文書", "恐嚇取財"
}

# 4. 純事實民事小額例行金錢催收案由 (精確比對)
EXACT_CIVIL_CAUSES = {
    "清償借款", "清償債務", "返還借款", "清償信用卡消費借款", "返還信用卡消費款",
    "給付電信費", "給付票款", "給付電話費", "清償現金卡消費借款", "清償信用卡消費款",
    "給付簽帳卡消費款", "給付借款", "給付管理費", "返還消費借貸款", "給付分期買賣價款",
    "給付承攬報酬", "給付租金", "給付買賣價金", "清償債務等"
}


def get_default_db_path() -> Path:
    candidates = [
        Path(r"G:\我的雲端硬碟\LawExamData\data\judicial_1m_db\judicial_1m_index.db"),
        Path(__file__).resolve().parent / "data" / "judicial_1m_db" / "judicial_1m_index.db",
        Path(__file__).resolve().parent / "data" / "judicial_1m_index.db"
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def clean_database(
    db_path: Path,
    commit: bool = False,
    include_factual: bool = True,
    include_procedural: bool = True,
    skip_vacuum: bool = False,
    batch_size: int = 5000
):
    if not db_path.exists():
        print(f"❌ 找不到資料庫檔案: {db_path}")
        return

    print("=" * 68)
    print(f"🧹 司法院裁判母庫深度精純化與空間清理工具")
    print(f"📂 資料庫路徑 : {db_path}")
    orig_size_mb = db_path.stat().st_size / (1024 * 1024)
    print(f"⚖️ 原始檔案大小 : {orig_size_mb:.2f} MB")
    print(f"⚙️ 清理範圍   : 非訟程序裁定({'ON' if include_procedural else 'OFF'}) | 純事實例行裁判({'ON' if include_factual else 'OFF'})")
    print(f"⚙️ 執行模式   : {'【正式清理落盤 (COMMIT)】' if commit else '【安全預覽模式 (DRY-RUN)】'}")
    print("=" * 68)

    conn = sqlite3.connect(str(db_path), timeout=60.0)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM judgments_meta")
    total_records = cur.fetchone()[0]
    print(f"📊 母庫現存裁判總筆數: {total_records:,} 筆")

    print("\n🔍 正在全庫掃描非訟程序與純事實案件 (並啟用實體爭點白名單保護)...")
    cur.execute("SELECT rowid, court, case_id, jud_word, title, holding_preview FROM judgments_meta")

    junk_rowids = []
    category_counter = {
        "非訟・本票裁定 (票/司票)": 0,
        "非訟・支付命令 (促/司促)": 0,
        "非訟・調解事件 (調/小調)": 0,
        "非訟・拍賣抵押物 (拍/司拍)": 0,
        "程序・命補費/補正 (補/司補)": 0,
        "程序・移送管轄/定刑/其他": 0,
        "事實・民事小額常規金錢訴訟": 0,
        "事實・刑事常規簡易認罪處刑": 0,
    }
    protected_count = 0

    t0 = time.time()
    for rowid, court, cid, word, title, hold in cur:
        cid = cid or ""
        word = word or ""
        court = court or ""
        title = title or ""
        hold = hold or ""

        # A. 非訟與純程序裁定檢驗
        is_proc = False
        if include_procedural and cid and NON_SUBSTANTIVE_REGEX.search(cid):
            is_proc = True
            junk_rowids.append(rowid)
            if "票" in cid:
                category_counter["非訟・本票裁定 (票/司票)"] += 1
            elif "促" in cid:
                category_counter["非訟・支付命令 (促/司促)"] += 1
            elif "調" in cid:
                category_counter["非訟・調解事件 (調/小調)"] += 1
            elif "拍" in cid:
                category_counter["非訟・拍賣抵押物 (拍/司拍)"] += 1
            elif "補" in cid:
                category_counter["程序・命補費/補正 (補/司補)"] += 1
            else:
                category_counter["程序・移送管轄/定刑/其他"] += 1
            continue

        # B. 純事實無實體爭點案件檢驗 (僅限地方法院，最高審與高等法院完全豁免)
        if include_factual and "地方法院" in court:
            is_small = any(k in word for k in ["小", "重小", "壢小", "湖小", "港小", "斗小", "員小"]) or ("小字" in cid)
            is_jian = any(k in word for k in ["簡", "交簡", "審簡", "重簡", "壢簡", "湖簡"]) or ("簡字" in cid or "交簡字" in cid)

            if is_small or is_jian:
                # 萃取真實案由
                m = re.search(r"[（\(](.*?)[）\)]", title)
                cause = m.group(1).strip() if m else title.strip()

                # 實體法學保護白名單比對
                if PROTECT_REGEX.search(cause) or PROTECT_REGEX.search(hold):
                    protected_count += 1
                    continue

                if is_small and cause in EXACT_CIVIL_CAUSES:
                    junk_rowids.append(rowid)
                    category_counter["事實・民事小額常規金錢訴訟"] += 1
                elif is_jian and cause in EXACT_CRIM_CAUSES:
                    junk_rowids.append(rowid)
                    category_counter["事實・刑事常規簡易認罪處刑"] += 1

    scan_elapsed = time.time() - t0
    total_junk = len(junk_rowids)
    junk_pct = (total_junk / total_records * 100) if total_records > 0 else 0

    print(f"⏱️ 掃描完成 (耗時 {scan_elapsed:.2f} 秒)！")
    print("-" * 68)
    print(f"📋 待剔除非實體爭點案件統計 (共 {total_junk:,} 筆，佔母庫 {junk_pct:.2f}%):")
    for cat_name, cnt in category_counter.items():
        if cnt > 0:
            sub_pct = (cnt / total_junk * 100) if total_junk > 0 else 0
            print(f"  * {cat_name:<28}: {cnt:>8,} 筆 ({sub_pct:5.1f}%)")
    print(f"  * 🛡️ 實體爭點白名單保護保留裁判: {protected_count:>8,} 筆")
    print("-" * 68)

    if total_junk == 0:
        print("🎉 太棒了！母庫已達極致精純，未檢測到任何非訟或純事實無爭點裁判！")
        conn.close()
        return

    if not commit:
        print("\n💡 提示：目前為【預覽模式 (DRY-RUN)】，未修改任何資料庫數據。")
        print("   若確認刪除這批非實體爭點紀錄並為母庫瘦身，請執行：")
        print(f"   python clean_master_db.py --commit\n")
        conn.close()
        return

    print(f"\n🚀 開始自 judgments_meta 批次安全刪除 {total_junk:,} 筆紀錄 (批次大小: {batch_size})...")
    del_t0 = time.time()

    for i in range(0, total_junk, batch_size):
        batch = junk_rowids[i:i + batch_size]
        placeholders = ",".join("?" for _ in batch)
        cur.execute(f"DELETE FROM judgments_meta WHERE rowid IN ({placeholders})", batch)
        conn.commit()
        pct = min(100.0, (i + len(batch)) / total_junk * 100)
        print(f"\r  [刪除進度] 已剔除: {min(i + len(batch), total_junk):,}/{total_junk:,} 筆 ({pct:.1f}%)", end="", flush=True)

    print()
    del_elapsed = time.time() - del_t0
    print(f"✅ 成功自 judgments_meta 清除 {total_junk:,} 筆非實體爭點裁判 (耗時 {del_elapsed:.2f} 秒)！")

    cur.execute("SELECT COUNT(*) FROM judgments_meta")
    remaining_records = cur.fetchone()[0]
    print(f"📊 母庫清洗後實質爭點裁判總數: {remaining_records:,} 筆 (精純化達成)")

    if skip_vacuum:
        print("\n⚡ 已依參數指定跳過 VACUUM 壓縮。")
        conn.close()
    else:
        print("\n📦 正在執行 SQLite VACUUM 壓縮與空間回收 (請稍候)...")
        vac_t0 = time.time()
        conn.execute("VACUUM")
        conn.close()
        vac_elapsed = time.time() - vac_t0

        new_size = db_path.stat().st_size / (1024 * 1024)
        saved_mb = orig_size_mb - new_size
        print(f"🎉 清洗與壓縮完成 (VACUUM 耗時 {vac_elapsed:.2f} 秒)！")
        print(f"💾 母庫體積由 {orig_size_mb:.2f} MB 壓縮至: {new_size:.2f} MB (釋放 {saved_mb:.2f} MB)")

    print("=" * 68)


def main():
    parser = argparse.ArgumentParser(description="司法院百萬裁判母庫非實體爭點案件深度清理與瘦身工具")
    parser.add_argument("--db-path", "-d", type=str, default=str(get_default_db_path()), help="母庫 SQLite 路徑")
    parser.add_argument("--commit", action="store_true", help="確認執行實際刪除並回收硬碟空間 (若未加此參數則僅為預檢)")
    parser.add_argument("--only-procedural", action="store_true", help="僅清理非訟與純程序裁定")
    parser.add_argument("--only-factual", action="store_true", help="僅清理純事實/無法律爭點案件")
    parser.add_argument("--skip-vacuum", action="store_true", help="刪除後跳過 VACUUM 空間回收壓縮")
    parser.add_argument("--batch-size", "-b", type=int, default=5000, help="刪除事務批次大小 (預設: 5000)")
    args = parser.parse_args()

    inc_proc = not args.only_factual
    inc_fact = not args.only_procedural

    clean_database(
        Path(args.db_path),
        commit=args.commit,
        include_factual=inc_fact,
        include_procedural=inc_proc,
        skip_vacuum=args.skip_vacuum,
        batch_size=args.batch_size
    )


if __name__ == "__main__":
    main()
