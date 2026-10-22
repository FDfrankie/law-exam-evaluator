#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Drive CloudStorage Network Synchronizer & Materializer
============================================================
Forces downloading and local materialization of all dataless/cloud-only files
in LawExamData from Google Drive via macOS FileProvider / Foundation API.
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Dict, Any

try:
    from Foundation import (
        NSFileManager,
        NSURL,
        NSURLUbiquitousItemDownloadingStatusKey,
        NSURLUbiquitousItemIsDownloadingKey,
        NSURLUbiquitousItemDownloadingStatusCurrent,
        NSURLUbiquitousItemDownloadingStatusDownloaded
    )
    FOUNDATION_AVAILABLE = True
except ImportError:
    FOUNDATION_AVAILABLE = False

TARGET_DIR = Path("/Users/liuguanfu/Library/CloudStorage/GoogleDrive-kennyliu950614@gmail.com/.shortcut-targets-by-id/1pzgFOqjs01oM9ohyn58hYeCDl73D-ihQ/LawExamData")
SF_DATALESS = 0x40000000


def get_dataless_files(root_dir: Path) -> List[Tuple[Path, int]]:
    """掃描所有尚未下載至本地的雲端預留檔案 (Dataless Faults)"""
    dataless = []
    for root, dirs, files in os.walk(root_dir):
        if ".git" in root or "__pycache__" in root:
            continue
        for f in files:
            if f.startswith("."):
                continue
            p = Path(root) / f
            try:
                st = os.stat(p, follow_symlinks=False)
                is_dataless = bool(getattr(st, "st_flags", 0) & SF_DATALESS) or (st.st_size > 0 and st.st_blocks == 0)
                if is_dataless:
                    dataless.append((p, st.st_size))
            except Exception:
                pass
    return dataless


def trigger_file_download(path: Path, fm: Any) -> bool:
    """呼叫 macOS Foundation 觸發檔案自雲端下載"""
    if not FOUNDATION_AVAILABLE:
        # 回退模式：透過小幅讀取觸發 FileProvider 下載
        try:
            with open(path, "rb") as f:
                _ = f.read(1024)
            return True
        except Exception:
            return False

    url = NSURL.fileURLWithPath_(str(path))
    ok, err = fm.startDownloadingUbiquitousItemAtURL_error_(url, None)
    return bool(ok)


def run_sync(target_path: Path = TARGET_DIR, batch_size: int = 100):
    print("=" * 65)
    print("🌐 Google Drive CloudStorage 雲端全量下載與實體同步引擎")
    print(f"🎯 目標路徑: {target_path}")
    print(f"⏰ 開始時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    if not target_path.exists():
        print(f"❌ 錯誤: 目標資料夾不存在: {target_path}")
        return

    fm = NSFileManager.defaultManager() if FOUNDATION_AVAILABLE else None

    # 1. 遞迴請求目錄下載
    if FOUNDATION_AVAILABLE:
        dir_url = NSURL.fileURLWithPath_(str(target_path))
        fm.startDownloadingUbiquitousItemAtURL_error_(dir_url, None)

    # 2. 搜尋待下載檔案
    dataless = get_dataless_files(target_path)
    total_count = len(dataless)
    total_bytes = sum(s for _, s in dataless)

    print(f"📊 總計偵測到待下載雲端檔案: {total_count:,} 份 (約 {total_bytes / (1024*1024*1024):.2f} GB)")

    if total_count == 0:
        print("✅ 所有檔案皆已下載至本機（無任何雲端暫存檔），同步已是最新狀態！")
        return

    # 按目錄統計分佈
    sub_stats = {}
    for p, s in dataless:
        rel = p.relative_to(target_path)
        top_part = rel.parts[0] if len(rel.parts) > 1 else "根目錄"
        sub_stats[top_part] = sub_stats.get(top_part, 0) + 1

    print("\n📁 待下載子目錄分佈：")
    for sub, count in sorted(sub_stats.items(), key=lambda x: -x[1]):
        print(f"  - {sub}: {count:,} 份檔案")

    print("\n🚀 正在逐批次向 macOS FileProvider / Google Drive 發送下載指令...")
    
    # 3. 逐批次發送下載指令
    for idx, (p, s) in enumerate(dataless, 1):
        trigger_file_download(p, fm)
        if idx % 100 == 0 or idx == total_count:
            print(f"  [進度] 已排程發送 {idx}/{total_count} ({idx/total_count*100:.1f}%)")

    print("\n⏳ 下載佇列已全部送達 Google Drive 網路核心。")
    print("   Google Drive 桌面端現正於背景自雲端伺服器全速下載實體檔案...")
    print("=" * 65)


if __name__ == "__main__":
    run_sync()

