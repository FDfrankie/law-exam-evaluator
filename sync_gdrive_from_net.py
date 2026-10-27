#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Drive CloudStorage Network Synchronizer & Materializer (Cross-Platform)
=============================================================================
支援 Windows、macOS 與 Linux 全平台 Google Drive 雲端檔案偵測與實體化下載。
- Windows: 透過讀取區塊觸發 Google Drive 虛擬檔案系統 (Cloud Files) 串流下載實體檔案
- macOS: 支援 Apple Foundation / NSFileManager API 與區塊回退讀取
- 全平台: 自動關聯 config.py 路徑，並於下載完成後自動同步筆記清單與 Manifest
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional

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

# macOS / Windows Dataless 屬性常數
SF_DATALESS = 0x40000000
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_ATTRIBUTE_OFFLINE = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000


def get_default_target_dir() -> Path:
    """智慧偵測 Google Drive 本地掛載資料夾（相容 Windows、Mac 與 Linux）"""
    # 優先順序 1: 由 config.py 取得 DATA_DIR.parent
    try:
        from config import DATA_DIR, PROJECT_ROOT
        if DATA_DIR and DATA_DIR.exists():
            return DATA_DIR.parent
        if PROJECT_ROOT and PROJECT_ROOT.exists():
            return PROJECT_ROOT
    except Exception:
        pass

    # 優先順序 2: Windows 常見 Google Drive 路徑
    for win_p in [
        Path(r"G:\我的雲端硬碟\LawExamData"),
        Path(r"G:\My Drive\LawExamData"),
        Path(r"C:\Users\mis\Google Drive\LawExamData")
    ]:
        if win_p.exists():
            return win_p

    # 優先順序 3: macOS 常見 CloudStorage 路徑
    mac_cs = Path.home() / "Library" / "CloudStorage"
    if mac_cs.exists():
        for gd_dir in mac_cs.glob("GoogleDrive*"):
            shortcut = gd_dir / ".shortcut-targets-by-id"
            if shortcut.exists():
                for target in shortcut.glob("*/LawExamData"):
                    if target.exists():
                        return target
            if (gd_dir / "我的雲端硬碟" / "LawExamData").exists():
                return gd_dir / "我的雲端硬碟" / "LawExamData"
            if (gd_dir / "My Drive" / "LawExamData").exists():
                return gd_dir / "My Drive" / "LawExamData"

    # 兜底：目前工作目錄上一層
    return Path(__file__).resolve().parent.parent


TARGET_DIR = get_default_target_dir()


def is_dataless_or_cloud_file(path: Path) -> bool:
    """跨平台檢測檔案是否為僅存於雲端、本機尚未實體化之預留檔 (Dataless / Sparse / Offline)"""
    try:
        st = os.stat(path, follow_symlinks=False)
        # 1. 檔案大小大於 0 但磁區佔用為 0 (通用雲端預留檔特徵)
        if hasattr(st, "st_blocks") and st.st_blocks == 0 and st.st_size > 0:
            return True
        # 2. macOS BSD flags 檢查
        if hasattr(st, "st_flags") and bool(st.st_flags & SF_DATALESS):
            return True
        # 3. Windows File Attributes 檢查
        if sys.platform == "win32":
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs != -1:
                if attrs & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS):
                    return True
    except Exception:
        pass
    return False


def get_dataless_files(root_dir: Path) -> List[Tuple[Path, int]]:
    """掃描所有尚未下載至本地的雲端預留檔案 (Dataless Faults)"""
    dataless = []
    if not root_dir.exists():
        return dataless

    for root, dirs, files in os.walk(root_dir):
        if ".git" in root or "__pycache__" in root:
            continue
        for f in files:
            if f.startswith("."):
                continue
            p = Path(root) / f
            if is_dataless_or_cloud_file(p):
                try:
                    dataless.append((p, p.stat().st_size))
                except Exception:
                    pass
    return dataless


def trigger_file_download(path: Path, fm: Any = None) -> bool:
    """跨平台觸發 Google Drive 雲端檔案串流下載並實體化至本機"""
    # 模式 A: macOS Foundation 原生 API
    if FOUNDATION_AVAILABLE and fm:
        try:
            url = NSURL.fileURLWithPath_(str(path))
            ok, _ = fm.startDownloadingUbiquitousItemAtURL_error_(url, None)
            if ok:
                return True
        except Exception:
            pass

    # 模式 B: 通用跨平台區塊讀取（Windows / Linux / macOS 通用）
    # 在 Windows / Google Drive 虛擬磁碟上，讀取檔案前端即會強制喚醒驅動程式自雲端下載完整檔案
    try:
        with open(path, "rb") as f:
            _ = f.read(4096)
        return True
    except Exception:
        return False


def run_sync(target_path: Optional[Path] = None, batch_size: int = 100):
    if target_path is None:
        target_path = get_default_target_dir()

    print("=" * 65)
    print("🌐 Google Drive 跨平台全量雲端實體化下載引擎 (Windows / macOS / Linux)")
    print(f"🎯 目標路徑: {target_path}")
    print(f"⏰ 開始時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    if not target_path.exists():
        print(f"❌ 錯誤: 目標資料夾不存在: {target_path}")
        return

    fm = NSFileManager.defaultManager() if FOUNDATION_AVAILABLE else None

    # macOS: 優先向目錄發送遞迴下載請求
    if FOUNDATION_AVAILABLE and fm:
        try:
            dir_url = NSURL.fileURLWithPath_(str(target_path))
            fm.startDownloadingUbiquitousItemAtURL_error_(dir_url, None)
        except Exception:
            pass

    # 掃描待下載檔案
    dataless = get_dataless_files(target_path)
    total_count = len(dataless)
    total_bytes = sum(s for _, s in dataless)

    print(f"📊 總計偵測到待下載雲端檔案: {total_count:,} 份 (約 {total_bytes / (1024*1024*1024):.2f} GB)")

    if total_count == 0:
        print("✅ 所有檔案皆已下載至本機（無任何雲端暫存檔），同步已是最新狀態！")
    else:
        # 按目錄統計分佈
        sub_stats = {}
        for p, s in dataless:
            try:
                rel = p.relative_to(target_path)
                top_part = rel.parts[0] if len(rel.parts) > 1 else "根目錄"
            except Exception:
                top_part = "其他"
            sub_stats[top_part] = sub_stats.get(top_part, 0) + 1

        print("\n📁 待下載子目錄分佈：")
        for sub, count in sorted(sub_stats.items(), key=lambda x: -x[1]):
            print(f"  - {sub}: {count:,} 份檔案")

        print(f"\n🚀 正在逐批次發送下載指令 (平台: {sys.platform})...")
        for idx, (p, s) in enumerate(dataless, 1):
            trigger_file_download(p, fm)
            if idx % 100 == 0 or idx == total_count:
                print(f"  [進度] 已發送 {idx}/{total_count} ({idx/total_count*100:.1f}%)")

        print("\n⏳ 下載佇列已全部送達 Google Drive。")

    # 同步更新筆記庫清單與快取
    print("\n🔄 正在同步更新 SamsungNotes 筆記清單與 Manifest...")
    try:
        from ingest_user_notes_to_sft import sync_all_drive_notes_to_samsung_notes
        c = sync_all_drive_notes_to_samsung_notes()
        print(f"✅ 筆記庫同步完成，共收錄 {c} 份法學筆記。")
    except Exception as e:
        print(f"[!] 筆記庫同步失敗: {e}")

    print("=" * 65)


if __name__ == "__main__":
    run_sync()
