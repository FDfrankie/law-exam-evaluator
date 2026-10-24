"""
開發者專屬：檔案庫在線檢視、體系組織與依內容智慧重命名大典
(Developer File Manager: Content-Based Viewing, Organization & Smart Renaming Engine)

功能特色：
1. 【全庫檔案在線檢視器】：深度支援 PDF 內嵌閱讀、照片全彩檢視、Word / Markdown 文字即時調閱與原始檔案下載。
2. 【體系化組織與分類】：支援依考科領域（民法、刑法、公法、商事法、智財等）、講義筆記性質、快取狀態篩選與法理章節體系排序。
3. 【依內容智慧重命名 (Content-Based Renaming)】：
   - 深入剖析手寫筆記 / 講義內文與 OCR 快取
   - 識別核心法條（如民法第184條、保險法第53條）、權威判決字號與具體法學爭點
   - 結合 Gemini Flash 視覺與語意大模型（具備多重後備規則字典），自動將無意義的原始時間戳 / Samsung Notes 檔名
     （如 債各_Notes_250220_100011.pdf、保險法_20251215_152009.jpg）
     轉換為標準法學規格檔名（如 【債各】買賣物之瑕疵擔保責任與危險負擔_Notes_250220.pdf）
   - 提供單檔即時預覽調整、安全磁碟重命名、快取同步遷移、批次依內容自動重命名與一鍵復原 (Undo) 機制。
"""

import os
import sys
import re
import json
import shutil
import time
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

try:
    from PIL import Image
except ImportError:
    Image = None

from config import (
    DATA_DIR,
    get_gemini_api_key,
    DEFAULT_GEMINI_MODEL,
    get_gemini_models_to_try
)

# ------------------------------------------------------------------------------
# 考科爭點字典與規則資料庫 (用於離線與快速語義分類)
# ------------------------------------------------------------------------------
SUBJECT_KEYWORDS_MAP = {
    "身分法": [
        "婚約", "結婚", "夫妻財產", "剩餘財產", "離婚", "親屬", "血親", "姻親", "配偶",
        "婚生推定", "認領", "收養", "監護", "扶養", "繼承", "特留分", "遺產", "扣減",
        "遺囑", "應繼分", "代位繼承", "歸繳", "拋棄繼承", "親屬會議", "侵害特留分"
    ],
    "債各": [
        "買賣", "瑕疵擔保", "危險負擔", "物之瑕疵", "權利瑕疵", "租賃", "買賣不破租賃", "轉租",
        "押租金", "承攬", "工作瑕疵", "瑕疵修補", "解除契約", "減少價金", "委任", "處理事務",
        "受任人", "居間", "行紀", "寄託", "合夥", "合會", "旅遊", "侵權行為", "不法侵害",
        "損害賠償", "侵權責任", "不當得利", "給付型不當得利", "非給付型不當得利", "無因管理"
    ],
    "債總": [
        "給付不能", "不完全給付", "給付遲延", "受領遲延", "債務不履行", "可歸責", "損害賠償",
        "履行利益", "信賴利益", "回復原狀", "金錢賠償", "過失相抵", "損益相抵", "連帶債務",
        "不可分債務", "債權讓與", "債務承擔", "清償", "提存", "抵銷", "免除", "混同",
        "代位權", "撤銷權", "保全", "定金", "違約金", "契約成立", "要約", "承諾"
    ],
    "民總": [
        "意思表示", "法律行為", "意思表示健全", "通謀虛偽", "受詐欺", "受脅迫", "錯誤",
        "權利能力", "行為能力", "受監護宣告", "受輔助宣告", "法人", "社團法人", "財團法人",
        "無權代理", "表見代理", "狹義無權代理", "撤銷", "無效", "效力未定", "條件", "期限",
        "消滅時效", "時效中斷", "時效不完成", "暴利行為", "公序良俗", "權利質權"
    ],
    "物權": [
        "物權法定主義", "物權行為", "公示原則", "公信原則", "善意受讓", "不動產登記",
        "所有權", "相鄰關係", "共有", "分別共有", "公同共有", "共有物分割", "用益物權",
        "地上權", "農育權", "不動產役權", "典權", "擔保物權", "普通抵押權", "最高限額抵押權",
        "抵押權實行", "次序權", "質權", "動產質權", "權利質權", "留置權", "占有", "占有保護"
    ],
    "刑總": [
        "構成要件", "客觀歸責", "因果關係", "條件說", "相當因果關係", "違法性", "阻卻違法",
        "正當防衛", "緊急避難", "依法令之行為", "被害人承諾", "有責性", "責任能力",
        "原因自由行為", "期待可能性", "未遂犯", "著手", "不能未遂", "中止未遂", "正犯",
        "共犯", "共同正犯", "教唆犯", "幫助犯", "間接正犯", "錯誤論", "客體錯誤",
        "打擊錯誤", "因果歷程錯誤", "競合論", "法條競合", "想像競合", "實質競合"
    ],
    "刑分": [
        "殺人罪", "過失致死", "傷害罪", "重傷罪", "遺棄罪", "妨害自由", "強制罪", "剝奪行動自由",
        "妨害性自主", "強制性交", "強盜罪", "準強盜罪", "加重強盜", "搶奪罪", "竊盜罪",
        "侵占罪", "詐欺罪", "背信罪", "恐嚇取財", "重利罪", "贓物罪", "毀損罪", "偽造文書",
        "變造文書", "使公務員登載不實", "偽造有價證券", "偽造印章印文", "瀆職罪", "收受賄賂",
        "公務員圖利", "枉法裁判", "妨害司法", "頂替罪", "偽證罪", "湮滅證據"
    ],
    "保險法": [
        "保險契約", "保險利益", "要保人", "被保險人", "受益人", "保險人", "複保險",
        "惡意複保險", "再保險", "保險費", "據實說明義務", "危險增加", "通知義務",
        "保險代位", "妨害代位", "消滅時效", "責任保險", "火災保險", "人壽保險", "健康保險",
        "傷害保險", "保險事故", "特約條款", "免責條款", "保險競合"
    ],
    "公司法": [
        "股東會", "股東會決議", "決議瑕疵", "無效", "得撤銷", "不存在", "董事會",
        "董事", "董事長", "忠實義務", "注意義務", "商業判斷法則", "代表人", "代表權限制",
        "監察人", "查核權", "發行新股", "特別股", "減資", "資本公積", "公司債",
        "控制公司", "從屬公司", "關係企業", "法人董事", "股份轉讓", "員工認股權"
    ],
    "證券交易法": [
        "內線交易", "重大消息", "消息明確", "獲悉", "內部人", "傳遞消息", "財報不實",
        "主要內容", "重大虛偽", "比例責任", "淨損益法", "真實價值", "操縱股價", "連續買賣",
        "相對成交", "散布流言", "短線交易", "歸入權", "公開收購", "私募", "募集與發行"
    ],
    "憲法": [
        "基本權審查", "比例原則", "適當性原則", "必要性原則", "狹義比例原則", "平等權",
        "差別待遇", "合目的性", "言論自由", "事前審查", "雙軌雙階理論", "人身自由",
        "提審", "正當法律程序", "工作權", "財產權", "生存權", "權力分立", "總統",
        "行政院", "立法院", "司法院", "監察院", "考試院", "違憲審查", "憲法法庭", "法規範憲法審查"
    ],
    "行政法": [
        "行政處分", "一般處分", "定性", "附款", "條件", "負擔", "行政契約", "法規命令",
        "行政規則", "行政指導", "行政罰", "責任條件", "從新從輕", "裁處權時效",
        "訴願", "行政訴訟", "撤銷訴訟", "課予義務訴訟", "確認訴訟", "給付訴訟",
        "暫時權利保護", "停止執行", "假處分", "國家賠償", "公務員賠償", "公共設施設置管理"
    ],
    "民訴": [
        "訴訟標的", "既判力", "實質確定力", "客觀範圍", "主觀範圍", "時間範圍",
        "爭點效", "當事人適格", "原告適格", "被告適格", "共同訴訟", "固有必要共同訴訟",
        "類似必要共同訴訟", "普通共同訴訟", "訴之追加變更", "反訴", "自由心證",
        "證明度", "舉證責任", "第二審", "第三審", "上訴利益", "再審", "假扣押", "假處分"
    ],
    "刑訴": [
        "強制處分", "羈押", "搜索", "扣押", "逕行搜索", "附帶搜索", "盤查",
        "傳聞法則", "傳聞例外", "特信情況", "非供述證據", "私人不法取證", "毒樹果實理論",
        "不正訊問", "自白法則", "調查證據", "勘驗", "鑑定", "公訴", "不起訴",
        "緩起訴", "上訴第三審", "再審", "非常上訴", "國民法官"
    ],
    "專利法": [
        "專利要件", "產業利用性", "新穎性", "進步性", "先申請原則", "專利權侵害",
        "文義讀取", "均等論", "禁反言", "專利舉發", "強制授權", "損害賠償計算"
    ],
    "法理學": [
        "法實證主義", "自然法論", "法與道德", "惡法亦法", "拉德布魯赫公式", "哈特",
        "富勒", "德沃金", "法律原則", "法律規則", "詮釋學", "利益法學", "概念法學"
    ]
}


def sanitize_filename(filename: str) -> str:
    """清理非法的檔名保留字元，替換為安全符號"""
    # Windows / Unix 非法符號: \ / : * ? " < > |
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', filename)
    # 去除前後空白與連續底線
    cleaned = re.sub(r'_+', '_', cleaned).strip()
    return cleaned


def is_raw_uninformative_name(filename: str) -> bool:
    """
    判定是否為未經整理之原始、時間戳或三星預設檔名。
    例如：
      - 債各_Notes_250220_100011.pdf
      - 債各_327_251110_163753.pdf
      - 保險法_20251215_152009.jpg
      - 身分法_Notes_250417_142502.pdf
      - 20250502_100839.jpg
    """
    stem = Path(filename).stem
    # 檢查是否包含 Notes_、純數字或純時間戳模式
    patterns = [
        r'Notes_\d{6}_\d{6}',
        r'Notes_\d{6}',
        r'^\d{6}_\d{6}$',
        r'^\d{8}_\d{6}$',
        r'_\d{6}_\d{6}$',
        r'_\d{6}$',
        r'^[0-9A-Za-z_-]{1,10}$',
        r'_\d{3}_\d{6}_\d{6}'
    ]
    for pat in patterns:
        if re.search(pat, stem, re.IGNORECASE):
            return True
    # 若檔名中僅有科目名稱與時間戳，而完全無中文法理題名
    pure_chinese = re.sub(r'[0-9A-Za-z_\-\.\s]', '', stem)
    if len(pure_chinese) <= 3:
        return True
    return False


def get_all_managed_files() -> List[Dict[str, Any]]:
    """
    掃描本機與雲端硬碟所有法學筆記與講義檔案，彙整完整元數據清單。
    若在雲端環境（如 Streamlit Cloud）實體資料夾無檔案，自動調用 drive_notes_manifest.json。
    """
    samsung_candidates = [
        Path(DATA_DIR) / "SamsungNotes",
        Path(__file__).resolve().parent / "data" / "SamsungNotes",
        Path(r"G:\我的雲端硬碟\LawExamData\SamsungNotes"),
        Path(r"G:\My Drive\LawExamData\SamsungNotes"),
        Path(__file__).resolve().parent.parent / "SamsungNotes",
        Path("/Users/liuguanfu/Library/CloudStorage/GoogleDrive-kennyliu950614@gmail.com/.shortcut-targets-by-id/1pzgFOqjs01oM9ohyn58hYeCDl73D-ihQ/LawExamData/SamsungNotes")
    ]
    samsung_dir = next((p for p in samsung_candidates if p.exists() and any(p.iterdir())), Path(DATA_DIR) / "SamsungNotes")
    try:
        samsung_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    cache_dir = samsung_dir / "_cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # 取得快取索引
    existing_caches = set(os.listdir(cache_dir)) if cache_dir.exists() else set()

    # 支援格式
    valid_exts = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".docx", ".doc", ".txt", ".md"}

    files_found = []
    seen_paths = set()

    # 1. 掃描 SamsungNotes 主目錄候選路徑
    for s_dir in samsung_candidates:
        if s_dir.exists():
            for f in sorted(s_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in valid_exts and not f.name.startswith("."):
                    if f.name == "desktop.ini":
                        continue
                    res_p = str(f.resolve())
                    if res_p not in seen_paths:
                        seen_paths.add(res_p)
                        files_found.append(_build_file_metadata(f, cache_dir, existing_caches))

    # 2. 掃描 community_archives/notes/ 社群筆記庫
    comm_candidates = [
        Path(DATA_DIR) / "community_archives" / "notes",
        Path(DATA_DIR).parent / "community_archives" / "notes",
        Path(__file__).resolve().parent / "data" / "community_archives" / "notes",
        Path(r"G:\我的雲端硬碟\LawExamData\community_archives\notes"),
        Path(r"G:\我的雲端硬碟\LawExamData\code\data\community_archives\notes")
    ]
    for c_dir in comm_candidates:
        if c_dir.exists():
            for f in sorted(c_dir.iterdir()):
                if f.is_file() and f.suffix.lower() in valid_exts and not f.name.startswith("."):
                    res_p = str(f.resolve())
                    if res_p not in seen_paths:
                        seen_paths.add(res_p)
                        files_found.append(_build_file_metadata(f, cache_dir, existing_caches, is_community=True))

    # 3. 雲端部署回退（例如 Streamlit Cloud，若實體資料夾無檔案，由 drive_notes_manifest.json 補齊）
    if not files_found:
        manifest_candidates = [
            Path(DATA_DIR) / "drive_notes_manifest.json",
            Path(__file__).resolve().parent / "data" / "drive_notes_manifest.json",
            Path(DATA_DIR).parent / "data" / "drive_notes_manifest.json"
        ]
        for mp in manifest_candidates:
            if mp.exists():
                try:
                    with open(mp, "r", encoding="utf-8") as mf:
                        m_list = json.load(mf)
                    for item in m_list:
                        fname = item.get("filename") or item.get("orig_filename") or ""
                        if not fname:
                            continue
                        f_stem = item.get("stem") or Path(fname).stem
                        subject = item.get("subject", "其他")
                        size_mb = float(item.get("size_mb", 0.0) or 0.0)
                        size_bytes = int(size_mb * 1024 * 1024)
                        ext = Path(fname).suffix.lower()
                        is_cached = bool(item.get("is_cached", False))
                        is_raw = is_raw_uninformative_name(fname)
                        local_p = samsung_dir / fname
                        
                        files_found.append({
                            "id": f"{f_stem}_{size_bytes}",
                            "filename": fname,
                            "orig_filename": item.get("orig_filename", fname),
                            "stem": f_stem,
                            "ext": ext,
                            "path": local_p,
                            "path_str": str(local_p),
                            "size_bytes": size_bytes,
                            "size_mb": round(size_mb, 2),
                            "size_str": f"{size_mb:.2f} MB" if size_mb >= 1.0 else f"{size_bytes / 1024:.1f} KB",
                            "mtime": 0,
                            "mtime_str": "雲端清單",
                            "subject": subject,
                            "is_cached": is_cached,
                            "cached_len": 500 if is_cached else 0,
                            "cached_preview": f"【{subject}】{fname} (雲端同步法學講義/手寫筆記)",
                            "is_raw": is_raw,
                            "is_community": False
                        })
                    if files_found:
                        break
                except Exception:
                    pass

    return files_found


def _build_file_metadata(p: Path, cache_dir: Path, existing_caches: set, is_community: bool = False) -> Dict[str, Any]:
    """建立單一檔案之詳細元數據物件"""
    filename = p.name
    stem = p.stem
    ext = p.suffix.lower()

    try:
        st = p.stat()
        size_bytes = st.st_size
        size_mb = size_bytes / (1024 * 1024)
        mtime = st.st_mtime
        mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
    except Exception:
        size_bytes = 0
        size_mb = 0.0
        mtime = 0
        mtime_str = "未知"

    # 科目判定
    subject = "其他"
    if "_" in stem:
        part0 = stem.split("_")[0].strip()
        if any(part0 == k for k in SUBJECT_KEYWORDS_MAP.keys()):
            subject = part0
        elif any(k in part0 for k in SUBJECT_KEYWORDS_MAP.keys()):
            for k in SUBJECT_KEYWORDS_MAP.keys():
                if k in part0:
                    subject = k
                    break

    # 檢查文字快取
    cache_cand1 = f"{filename}.txt"
    cache_cand2 = f"{stem}.txt"
    is_cached = (cache_cand1 in existing_caches) or (cache_cand2 in existing_caches)

    cached_preview = ""
    cached_len = 0
    c_target = cache_dir / cache_cand1 if cache_cand1 in existing_caches else cache_dir / cache_cand2
    if is_cached and c_target.exists():
        try:
            c_text = c_target.read_text(encoding="utf-8", errors="replace")
            cached_len = len(c_text)
            clean_first = re.sub(r'[\r\n\t]+', ' ', c_text).strip()
            cached_preview = clean_first[:160]
        except Exception:
            pass

    is_raw = is_raw_uninformative_name(filename)

    return {
        "id": f"{stem}_{size_bytes}",
        "filename": filename,
        "stem": stem,
        "ext": ext,
        "path": p,
        "path_str": str(p),
        "size_bytes": size_bytes,
        "size_mb": round(size_mb, 2),
        "size_str": f"{size_mb:.2f} MB" if size_mb >= 1.0 else f"{size_bytes / 1024:.1f} KB",
        "mtime": mtime,
        "mtime_str": mtime_str,
        "subject": subject,
        "is_cached": is_cached,
        "cached_len": cached_len,
        "cached_preview": cached_preview,
        "is_raw": is_raw,
        "is_community": is_community
    }


def read_file_text_cached(file_path: Path, max_pages: int = 5, auto_extract: bool = True) -> str:
    """
    高速讀取筆記文字：優先自 _cache/ 讀取；若無快取則自動調用文字解析或 OCR 並寫入快取。
    """
    samsung_dir = Path(DATA_DIR) / "SamsungNotes"
    cache_dir = samsung_dir / "_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_file = cache_dir / f"{file_path.name}.txt"
    if cache_file.exists() and cache_file.stat().st_size > 0:
        try:
            return cache_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # 若未要求自動提取則返回空字串
    if not auto_extract:
        return ""

    text = ""
    ext = file_path.suffix.lower()

    if ext in [".txt", ".md"]:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            text = f"[純文字讀取異常: {e}]"
    elif ext in [".pdf", ".docx", ".jpg", ".jpeg", ".png", ".webp"]:
        # 嘗試引用主專案的 read_note_text
        try:
            from ingest_user_notes_to_sft import read_note_text
            text = read_note_text(file_path, max_pages=max_pages, auto_ocr=True)
        except Exception as ee:
            text = f"[文字解析提示: {ee}]"

    # 若成功提取實質內容，立即寫入快取供日後秒速讀取
    if text and len(text.strip()) > 30 and not text.startswith("["):
        try:
            cache_file.write_text(text, encoding="utf-8")
        except Exception:
            pass

    return text


def extract_key_legal_entities(text: str, subject_hint: str = "") -> Dict[str, List[str]]:
    """自內文中精確識別法規條文（含 § 記號與完整條文）與司法院裁判字號"""
    if not text:
        return {"laws": [], "cases": []}

    law_pattern = re.compile(
        r'([\u4e00-\u9fa5]{2,12}?(?:法|條例|通則|規則|辦法))第\s*(\d+(?:之\d+)?)\s*條'
    )
    # 支援法學手寫常用的條文符號 § 與 § 184 I 等
    sec_pattern = re.compile(
        r'(?:§|§\s*|條次[:：]?\s*)(\d{1,4}(?:之\d+)?)'
    )
    case_pattern = re.compile(
        r'((?:最高法院|最高行政法院|臺灣高等法院|憲法法庭)?\s*(?:\d{2,3}\s*年(?:度)?\s*[\u4e00-\u9fa5A-Za-z\(\)（）]+字第\s*\d+\s*號|\d{2,3}\s*(?:台上|台上大|台抗|台聲|上易|重訴|訴|簡上|大|憲判)\s*(?:大)?\d+(?:裁|決|例)?|\d{2,3}憲判\d+|SC\s*\d+\s*[\u4e00-\u9fa5]+\d+例?))'
    )

    laws = []
    seen_laws = set()
    for m in law_pattern.finditer(text):
        l_str = f"{m.group(1)}第{m.group(2)}條"
        if l_str not in seen_laws:
            seen_laws.add(l_str)
            laws.append(l_str)

    # 若未找到完整條文名稱，則依科目補綴對應主要法典（如身分法/債各/民總/物權 -> 民法；保險法 -> 保險法）
    if len(laws) < 5:
        default_statute = "民法"
        if subject_hint in ["刑總", "刑分", "刑法"]:
            default_statute = "刑法"
        elif subject_hint in ["保險法"]:
            default_statute = "保險法"
        elif subject_hint in ["公司法"]:
            default_statute = "公司法"
        elif subject_hint in ["證券交易法", "證交法"]:
            default_statute = "證券交易法"
        elif subject_hint in ["行政法"]:
            default_statute = "行政程序法"
        elif subject_hint in ["憲法"]:
            default_statute = "憲法"
        elif subject_hint in ["民訴"]:
            default_statute = "民事訴訟法"
        elif subject_hint in ["刑訴"]:
            default_statute = "刑事訴訟法"
        elif subject_hint in ["專利法"]:
            default_statute = "專利法"

        for m in sec_pattern.finditer(text):
            sec_no = m.group(1).strip()
            l_str = f"{default_statute}第{sec_no}條"
            if l_str not in seen_laws:
                seen_laws.add(l_str)
                laws.append(l_str)
            if len(laws) >= 8:
                break

    cases = []
    seen_cases = set()
    for m in case_pattern.finditer(text):
        c_str = m.group(1).strip()
        if len(c_str) >= 4 and c_str not in seen_cases:
            seen_cases.add(c_str)
            cases.append(c_str)

    return {"laws": laws[:8], "cases": cases[:5]}


def suggest_name_by_content(
    file_path: Path,
    known_subject: str = "",
    use_ai: bool = True
) -> Dict[str, Any]:
    """
    核心引擎：依據檔案實際內容（內文、條文、爭點、講義標題），
    智慧推導出最精準標準的繁體中文法學檔名。
    回傳字典包含：
      - suggested_filename: 建議之完整新檔名（含副檔名）
      - clean_topic: 核心爭點或章節名稱
      - subject: 所屬考科
      - core_laws: 識別出的主要法條
      - reasoning: 命名依據與分析理由
      - confidence: 信心指標 ("high", "medium", "rule-based")
    """
    filename = file_path.name
    ext = file_path.suffix.lower()
    stem = file_path.stem

    # 1. 取得內文（優先自快取調用）
    text = read_file_text_cached(file_path, max_pages=4, auto_extract=True)
    text_sample = text[:3500] if text else ""

    # 2. 考科判定
    subject = known_subject
    if not subject or subject == "其他":
        # 依內文關鍵字頻率投票判定考科
        scores = {}
        for sub_name, kw_list in SUBJECT_KEYWORDS_MAP.items():
            cnt = sum(text_sample.count(kw) for kw in kw_list)
            if cnt > 0:
                scores[sub_name] = cnt
        if scores:
            subject = max(scores.items(), key=lambda x: x[1])[0]
        else:
            subject = "法學筆記"

    # 3. 實體提取
    entities = extract_key_legal_entities(text_sample, subject_hint=subject)
    core_laws = entities["laws"]
    core_cases = entities["cases"]

    # 4. 規則基礎爭點萃取 (Heuristic Rule-Based Fallback)
    rule_topic = ""

    # (A) 搜尋 Markdown / 筆記標題語法 (如 "# 身分法：一、親屬總論" 或 "第X章")
    title_matches = re.findall(r'(?:^|\n)#+\s*([^\n\r]+)', text_sample)
    for tm in title_matches:
        t_clean = tm.strip().replace("以下為", "").replace("手寫筆記", "").strip()
        if len(t_clean) >= 4 and not any(k in t_clean for k in ["精確辨識", "法學結構", "繁體中文"]):
            rule_topic = t_clean
            break

    # (B) 若無明確大標題，嘗試尋找特定章節標題
    if not rule_topic:
        chap_match = re.search(r'([一二三四五六七八九十]+、[^\n\r，。；]{4,25})', text_sample)
        if chap_match:
            rule_topic = chap_match.group(1).strip()

    # (C) 依核心法條與關鍵爭點拼裝
    if not rule_topic and core_laws:
        top_law = core_laws[0]
        # 比對爭點關鍵字
        matched_kws = []
        for kw in SUBJECT_KEYWORDS_MAP.get(subject, []):
            if kw in text_sample and kw not in matched_kws:
                matched_kws.append(kw)
                if len(matched_kws) >= 2:
                    break
        kw_str = "・".join(matched_kws) if matched_kws else "核心爭點"
        rule_topic = f"{top_law}_{kw_str}"

    if not rule_topic:
        # 若仍無法萃取，提取檔名中非時間戳的有用字符
        clean_stem = re.sub(r'(Notes_|\d{6}_\d{6}|\d{8}_\d{6}|\d{6})', '', stem)
        clean_stem = re.sub(r'^[_\-\s]+|[_\-\s]+$', '', clean_stem)
        rule_topic = clean_stem if len(clean_stem) >= 3 else "研讀筆記與實務爭點"

    # 去除前後可能重複的科目
    rule_topic = re.sub(rf'^{subject}[:：_・\s]*', '', rule_topic).strip()

    # 5. Gemini AI 深度法學精準題名（若配置 API KEY 且要求 AI）
    ai_suggested_name = ""
    ai_reason = ""
    confidence = "rule-based"

    api_key = get_gemini_api_key()
    if use_ai and api_key and len(text_sample) >= 40:
        try:
            # 支援 google-genai 新舊 SDK
            prompt = f"""
你是一位台灣國家司法官與律師二試權威閱卷委員與法學圖書館總策劃。
請閱讀以下法學教材/手寫筆記的前言與內文摘錄：
---
檔名：{filename}
科目：{subject}
核心法條：{', '.join(core_laws)}
內文摘錄：
{text_sample[:2000]}
---

請依據台灣國家考試之正式法理體系與學說爭點（例如「買賣物之瑕疵擔保責任與危險負擔」、「夫妻剩餘財產分配請求權」、「原因自由行為處罰基礎與主客觀要件」等），
給予這份檔案一個精鍊、專業、標準化的繁體中文題名。

請嚴格輸出符合以下 JSON 格式之回傳（勿包含額外 markdown 說明符號）：
{{
  "subject": "{subject}",
  "topic_title": "精確章節或爭點名稱（約 10 至 25 字）",
  "reasoning": "簡短命名依據（例如：內文集中探討民法第354條物之瑕疵與危險負擔移轉時點）"
}}
"""
            raw_resp = ""
            models_to_try = get_gemini_models_to_try(DEFAULT_GEMINI_MODEL)
            for m in models_to_try:
                try:
                    try:
                        from google import genai
                        from google.genai import types
                        client = genai.Client(api_key=api_key)
                        resp = client.models.generate_content(
                            model=m,
                            contents=prompt,
                            config=types.GenerateContentConfig(temperature=0.2)
                        )
                        raw_resp = resp.text
                        if raw_resp:
                            break
                    except Exception:
                        import google.generativeai as ggenai
                        ggenai.configure(api_key=api_key)
                        model = ggenai.GenerativeModel(m)
                        resp = model.generate_content(prompt)
                        raw_resp = resp.text
                        if raw_resp:
                            break
                except Exception:
                    continue

            if raw_resp:
                clean_json_str = re.search(r'\{.*\}', raw_resp, re.DOTALL)
                if clean_json_str:
                    parsed = json.loads(clean_json_str.group(0))
                    t_title = parsed.get("topic_title", "").strip()
                    if t_title:
                        ai_suggested_name = t_title
                        ai_reason = parsed.get("reasoning", "")
                        confidence = "high"
        except Exception:
            pass

    final_topic = ai_suggested_name if ai_suggested_name else rule_topic
    final_topic = sanitize_filename(final_topic)

    # 保留原檔末尾簡短識別戳記（避免同科目同章節多份筆記覆寫衝突）
    short_id_match = re.search(r'(\d{6}_\d{6}|\d{6}|\d{3})', stem)
    suffix_tag = f"_{short_id_match.group(1)}" if short_id_match else ""

    # 組合標準法學命名：【考科】核心章節爭點題名_識別碼.副檔名
    final_filename = f"【{subject}】{final_topic}{suffix_tag}{ext}"
    final_filename = sanitize_filename(final_filename)

    reason = ai_reason if ai_reason else (
        f"依內文法律實體與關鍵字比對（核心條文：{', '.join(core_laws[:3]) if core_laws else '無'}；章節要旨：{final_topic}）"
    )

    return {
        "suggested_filename": final_filename,
        "clean_topic": final_topic,
        "subject": subject,
        "core_laws": core_laws,
        "core_cases": core_cases,
        "reasoning": reason,
        "confidence": confidence
    }


def execute_rename_file(old_path: Path, new_filename: str) -> Dict[str, Any]:
    """
    嚴格安全的實體檔案重命名引擎：
    1. 驗證合法檔名與原副檔名保證
    2. 自動檢查磁碟衝突與重名防護（若衝突自動追加流水序號）
    3. 同步重命名或複製 _cache/ 內的文字快取檔案
    4. 同步更新 drive_notes_manifest.json 紀錄
    5. 回傳執行成果物件，供 Streamlit 即時渲染與一鍵復原
    """
    if not old_path.exists():
        return {"success": False, "error": f"原始檔案不存在：{old_path}"}

    clean_new_name = sanitize_filename(new_filename.strip())
    # 確保副檔名與原始一致
    if not clean_new_name.lower().endswith(old_path.suffix.lower()):
        clean_new_name += old_path.suffix

    parent_dir = old_path.parent
    target_path = parent_dir / clean_new_name

    # 若新舊名稱完全一致，直接成功
    if old_path.resolve() == target_path.resolve():
        return {
            "success": True,
            "old_filename": old_path.name,
            "new_filename": clean_new_name,
            "old_path": old_path,
            "new_path": target_path,
            "message": "檔名無異動"
        }

    # 衝突處理：若已有同名檔案，追加計數序號
    counter = 1
    stem_part = target_path.stem
    ext_part = target_path.suffix
    while target_path.exists() and target_path.resolve() != old_path.resolve():
        target_path = parent_dir / f"{stem_part}({counter}){ext_part}"
        counter += 1

    try:
        # 1. 執行實體檔案重命名
        shutil.move(str(old_path), str(target_path))

        # 2. 同步快取檔案 (_cache/)
        samsung_dir = Path(DATA_DIR) / "SamsungNotes"
        cache_dir = samsung_dir / "_cache"
        old_cache = cache_dir / f"{old_path.name}.txt"
        new_cache = cache_dir / f"{target_path.name}.txt"
        if old_cache.exists():
            try:
                shutil.move(str(old_cache), str(new_cache))
            except Exception:
                pass

        # 3. 同步 drive_notes_manifest.json（若存在）
        manifest_path = Path(DATA_DIR) / "drive_notes_manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f_mf:
                    m_data = json.load(f_mf)
                updated = False
                for item in m_data:
                    if item.get("filename") == old_path.name:
                        item["filename"] = target_path.name
                        item["path"] = str(target_path)
                        updated = True
                if updated:
                    with open(manifest_path, "w", encoding="utf-8") as f_mf_out:
                        json.dump(m_data, f_mf_out, ensure_ascii=False, indent=2)
            except Exception:
                pass

        # 4. 清除記憶體快取
        try:
            import ingest_user_notes_to_sft
            ingest_user_notes_to_sft._DRIVE_NOTES_CACHE = None
        except Exception:
            pass

        return {
            "success": True,
            "old_filename": old_path.name,
            "new_filename": target_path.name,
            "old_path": old_path,
            "new_path": target_path,
            "message": f"成功重命名為《{target_path.name}》"
        }

    except Exception as e:
        return {"success": False, "error": f"重命名過程發生異常: {e}"}


def execute_undo_rename(history_item: Dict[str, Any]) -> Dict[str, Any]:
    """一鍵復原前次重命名操作"""
    current_path = Path(history_item["new_path"])
    original_filename = history_item["old_filename"]
    if not current_path.exists():
        return {"success": False, "error": f"當前檔案已不存在，無法復原：{current_path}"}
    return execute_rename_file(current_path, original_filename)


# ------------------------------------------------------------------------------
# Streamlit 交互式操作面板組件
# ------------------------------------------------------------------------------
def render_developer_file_manager():
    """
    完整渲染 Streamlit 開發者檔案總管面板：
    包含檔案調閱檢視器、分類組織矩陣、依內容智慧重命名大典與復原中心。
    """
    import streamlit as st

    # 嚴格多層防護機制：若當前獨立 Session 未經金鑰授權，立即阻絕存取
    is_auth = st.session_state.get("is_developer_authenticated", False)
    dev_pwd = str(st.session_state.get("inp_developer_pwd", "")).strip().lower()
    if not (is_auth and dev_pwd == "brrfdccee"):
        st.error("🔒 【權限不足・存取遭拒】此檔案庫總管收錄作者個人未公開之法學手寫筆記與教材檔案，未獲授權嚴禁調閱。請於左側邊欄輸入開發者金鑰解鎖。")
        return

    st.markdown("""
        <div style="padding: 16px 20px; border-radius: 10px; background: linear-gradient(135deg, #1f4068 0%, #162447 100%); color: white; margin-bottom: 20px;">
            <h2 style="color: white; margin-bottom: 4px; font-size: 1.6rem;">🛠️ 開發者檔案庫總管 (Developer File Hub)</h2>
            <p style="color: #e4e4e4; font-size: 0.95rem; margin-bottom: 0;">
                支援全量個人法學講義與三星手寫筆記：<b>在線無損閱讀檢視</b>、<b>考科體系分類組織</b> 與 <b>依據法理內文 AI 智慧重命名</b>。
            </p>
        </div>
    """, unsafe_allow_html=True)

    # 確保 session state 重命名歷史清單
    if "dev_rename_history" not in st.session_state:
        st.session_state["dev_rename_history"] = []

    # 載入全部檔案清單
    all_files = get_all_managed_files()

    if not all_files:
        st.warning("⚠️ 目前未偵測到任何 SamsungNotes 或社群筆記檔案，請確認 `SamsungNotes/` 資料夾位置或於下方直接上傳。")
        with st.container(border=True):
            st.subheader("📤 立即上傳法學講義或手寫筆記")
            up_files = st.file_uploader("選取欲上傳之檔案：", type=["pdf", "docx", "png", "jpg", "jpeg", "txt", "md"], accept_multiple_files=True, key="dev_empty_uploader")
            if up_files:
                target_s_dir = Path(DATA_DIR) / "SamsungNotes"
                target_s_dir.mkdir(parents=True, exist_ok=True)
                for uf in up_files:
                    with open(target_s_dir / uf.name, "wb") as fo:
                        fo.write(uf.getbuffer())
                st.success(f"✅ 成功上傳 {len(up_files)} 份筆記！")
                st.rerun()
        return

    # 計算統計指標
    total_count = len(all_files)
    total_mb = sum(f["size_mb"] for f in all_files)
    raw_count = sum(1 for f in all_files if f["is_raw"])
    cached_count = sum(1 for f in all_files if f["is_cached"])

    # 頂部儀表板
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("📁 全庫收錄總檔案", f"{total_count} 份")
    col_m2.metric("💾 磁碟總佔用容量", f"{total_mb:.1f} MB")
    col_m3.metric("⚠️ 待依內容命名 (原始檔)", f"{raw_count} 份", delta=f"{raw_count / total_count * 100:.0f}% 待整理", delta_color="inverse")
    col_m4.metric("⚡ 已快取文字 / OCR", f"{cached_count} 份", delta=f"{cached_count / total_count * 100:.0f}% 已就緒")

    st.markdown("---")

    # 四大核心功能分頁（含開發者專屬全考科合併為單一完整 PDF 大典）
    tab_view, tab_organize, tab_merge_pdf, tab_rename, tab_history = st.tabs([
        "📂 1. 全庫檔案在線檢視與調閱 (View Files)",
        "🏷️ 2. 考科體系分類與組織清單 (Organize)",
        "📑 3. 全考科合併為單一完整 PDF (Merge PDFs)",
        "🪄 4. 依內文智慧重命名大典 (Smart Rename)",
        "📜 5. 操作歷史審計與一鍵復原 (Undo / Audit)"
    ])

    # --------------------------------------------------------------------------
    # 分頁 1: 全庫檔案在線檢視與調閱
    # --------------------------------------------------------------------------
    with tab_view:
        st.subheader("📂 檔案調閱與多模態即時在線檢視器")
        st.caption("點選即可於網頁內直接翻閱高解析度 PDF 講義、手寫圖檔或瀏覽 OCR 結構化筆記文字，無需下載至本機即可秒速檢視！")

        # 篩選列
        c_f1, c_f2, c_f3, c_f4 = st.columns([1.5, 1.2, 1.3, 1.5])
        with c_f1:
            all_subjects = ["全部考科"] + sorted(list(set(f["subject"] for f in all_files)))
            sel_sub_filter = st.selectbox("依科目篩選：", all_subjects, key="view_filter_sub")
        with c_f2:
            sel_status_filter = st.selectbox(
                "命名狀態：",
                ["全部狀態", "⚠️ 待依內容重命名 (Raw)", "✅ 已語義化命名"],
                key="view_filter_status"
            )
        with c_f3:
            sel_cache_filter = st.selectbox(
                "文字快取：",
                ["全部", "⚡ 僅顯示已快取", "📄 尚未快取文字"],
                key="view_filter_cache"
            )
        with c_f4:
            search_query = st.text_input("🔍 檔名 / 爭點關鍵字速查：", placeholder="輸入關鍵字如：買賣、親屬、保險...", key="view_search_kw")

        # 執行過濾
        filtered_files = all_files
        if sel_sub_filter != "全部考科":
            filtered_files = [f for f in filtered_files if f["subject"] == sel_sub_filter]
        if "待依內容" in sel_status_filter:
            filtered_files = [f for f in filtered_files if f["is_raw"]]
        elif "已語義化" in sel_status_filter:
            filtered_files = [f for f in filtered_files if not f["is_raw"]]
        if "僅顯示已快取" in sel_cache_filter:
            filtered_files = [f for f in filtered_files if f["is_cached"]]
        elif "尚未快取" in sel_cache_filter:
            filtered_files = [f for f in filtered_files if not f["is_cached"]]
        if search_query.strip():
            sq = search_query.strip().lower()
            filtered_files = [
                f for f in filtered_files
                if sq in f["filename"].lower() or sq in f["cached_preview"].lower() or sq in f["subject"].lower()
            ]

        st.caption(f"🎯 符合篩選條件：共 **{len(filtered_files)} 份** 檔案")

        # 檔案清單渲染
        for idx, item in enumerate(filtered_files):
            badge_raw = "⚠️ 原始檔名待重命名" if item["is_raw"] else "✅ 已語義題名"
            badge_cache = f"⚡ 已快取 ({item['cached_len']} 字)" if item["is_cached"] else "📄 待提取文字"
            badge_ext = item["ext"].upper()

            with st.expander(
                f"【{item['subject']}】《{item['filename']}》 ｜ 💾 {item['size_str']} ｜ 📅 {item['mtime_str']} ｜ {badge_raw} ｜ {badge_cache}",
                expanded=False
            ):
                col_info, col_act = st.columns([3, 1])
                with col_info:
                    st.markdown(f"**實體路徑**：`{item['path_str']}`")
                    if item["cached_preview"]:
                        st.info(f"📝 **文字摘錄預覽**：{item['cached_preview']}...")
                    else:
                        st.caption("💡 尚未快取文字內容。點擊右側或下方「⚡ 立即提取文字」即可由 AI 高速辨識並快取。")

                with col_act:
                    # 檔案下載按鈕
                    try:
                        with open(item["path"], "rb") as fp:
                            st.download_button(
                                label=f"💾 下載原檔 ({item['size_str']})",
                                data=fp.read(),
                                file_name=item["filename"],
                                key=f"dl_file_{idx}"
                            )
                    except Exception:
                        pass

                # 在線預覽區塊
                st.markdown("#### 👁️ 在線多模態檔案檢視器：")
                ext_l = item["ext"]
                if ext_l == ".pdf":
                    try:
                        with open(item["path"], "rb") as f_pdf:
                            pdf_bytes = f_pdf.read()
                        b64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
                        pdf_display = f'<iframe src="data:application/pdf;base64,{b64_pdf}" width="100%" height="520" type="application/pdf" style="border: 1px solid #ddd; border-radius: 8px;"></iframe>'
                        st.markdown(pdf_display, unsafe_allow_html=True)
                    except Exception as pe:
                        st.warning(f"在線 PDF 渲染提示: {pe}")
                elif ext_l in [".jpg", ".jpeg", ".png", ".webp"]:
                    try:
                        st.image(str(item["path"]), caption=item["filename"], use_container_width=True)
                    except Exception as ie:
                        st.warning(f"圖片渲染提示: {ie}")
                elif ext_l in [".txt", ".md"]:
                    try:
                        t_content = item["path"].read_text(encoding="utf-8", errors="replace")
                        st.text_area("純文字內容全文：", t_content, height=350, key=f"txt_area_{idx}")
                    except Exception as te:
                        st.warning(f"文字讀取提示: {te}")

                # 底部即時文字檢視 / 提取按鈕
                c_btn1, c_btn2 = st.columns(2)
                with c_btn1:
                    if st.button("📝 展開檢視 / 重新提取 OCR 完整文字", key=f"btn_ocr_view_{idx}"):
                        with st.spinner("正在調閱文字快取或啟動多模態辨識..."):
                            full_txt = read_file_text_cached(item["path"], max_pages=8, auto_extract=True)
                            st.session_state[f"full_txt_view_{idx}"] = full_txt
                            st.rerun()

                if f"full_txt_view_{idx}" in st.session_state:
                    st.text_area(f"《{item['filename']}》完整辨識文字：", st.session_state[f"full_txt_view_{idx}"], height=300, key=f"full_area_{idx}")

    # --------------------------------------------------------------------------
    # 分頁 2: 考科體系分類與組織清單
    # --------------------------------------------------------------------------
    with tab_organize:
        st.subheader("🏷️ 考科體系化組織與分類總覽")
        st.caption("將全庫零散筆記依據法學考科、章節架構與檔案類型進行結構化歸納，直觀掌握各科教材完備度。")

        # 考科統計直條卡片
        sub_dist = {}
        for f in all_files:
            sub_dist[f["subject"]] = sub_dist.get(f["subject"], 0) + 1

        st.markdown("#### 📊 各考科筆記收錄數量分佈：")
        cols_sub = st.columns(4)
        for s_idx, (s_name, s_count) in enumerate(sorted(sub_dist.items(), key=lambda x: -x[1])):
            with cols_sub[s_idx % 4]:
                st.metric(f"【{s_name}】", f"{s_count} 份", delta=f"{s_count / total_count * 100:.1f}%")

        st.markdown("---")
        st.markdown("#### 📂 依考科分類瀏覽檔案目錄：")
        for s_name, s_count in sorted(sub_dist.items(), key=lambda x: -x[1]):
            s_files = [f for f in all_files if f["subject"] == s_name]
            with st.expander(f"📁 【{s_name}】共收錄 {s_count} 份筆記講義", expanded=False):
                for sf_idx, sf in enumerate(s_files, 1):
                    c_tag = "⚡ 已快取" if sf["is_cached"] else "待提取"
                    is_r_icon = "⚠️" if sf["is_raw"] else "✅"
                    st.write(f"{sf_idx}. {is_r_icon} **《{sf['filename']}》** ｜ `{sf['size_str']}` ｜ {c_tag}")

    # --------------------------------------------------------------------------
    # 分頁 3: 開發者專屬全考科合併為單一完整 PDF 大典
    # --------------------------------------------------------------------------
    with tab_merge_pdf:
        st.subheader("📑 考科全卷總成：依章節法理順序拼接合併為單一完整 PDF")
        st.caption("🔒 **【開發者特權工具】** 自動依據中文章節與法學體系順序（如親屬總論 ➔ 婚約 ➔ 婚姻...至扣減權，或刑總構成要件 ➔ 違法性 ➔ 罪責 ➔ 未遂共犯），秒速拼接該考科全部 PDF，生成一個完整可離線劃記閱讀的超大 PDF。")

        try:
            from ingest_user_notes_to_sft import (
                get_google_drive_notes_list,
                merge_subject_pdfs,
                get_chapter_sort_key
            )
            all_drive_notes = get_google_drive_notes_list()
        except Exception as _e_load:
            all_drive_notes = []

        sub_pdf_map = {}
        for n in all_drive_notes:
            if n.get("path") and Path(n["path"]).suffix.lower() == ".pdf":
                fn = n.get("filename", "")
                if "全科整合" not in fn and "全科體系" not in fn and not fn.endswith("_全科筆記文字總彙編.md"):
                    sub_pdf_map.setdefault(n["subject"], []).append(n)

        if not sub_pdf_map:
            st.info("💡 目前未偵測到任何考科的 PDF 講義筆記。請確認雲端硬碟「資源」或 SamsungNotes 目錄。")
        else:
            CIVIL_GROUP = ["民總", "債總", "債各", "物權", "身分法", "民法"]
            CRIM_GROUP = ["刑總", "刑分", "刑法"]
            PUB_GROUP = ["憲法", "行政法"]
            COMM_GROUP = ["商事法", "保險法"]
            IP_GROUP = ["專利法", "商標法", "著作權法", "智慧財產權法"]

            crim_pdfs = [n for n in all_drive_notes if n["subject"] in CRIM_GROUP and Path(n["path"]).suffix.lower() == ".pdf" and "全科整合" not in n["filename"]]
            civil_pdfs = [n for n in all_drive_notes if n["subject"] in CIVIL_GROUP and Path(n["path"]).suffix.lower() == ".pdf" and "全科整合" not in n["filename"]]
            pub_pdfs = [n for n in all_drive_notes if n["subject"] in PUB_GROUP and Path(n["path"]).suffix.lower() == ".pdf" and "全科整合" not in n["filename"]]
            comm_pdfs = [n for n in all_drive_notes if n["subject"] in COMM_GROUP and Path(n["path"]).suffix.lower() == ".pdf" and "全科整合" not in n["filename"]]
            ip_pdfs = [n for n in all_drive_notes if n["subject"] in IP_GROUP and Path(n["path"]).suffix.lower() == ".pdf" and "全科整合" not in n["filename"]]

            # 選單選項：優先將《刑總》與《刑法全輯》等重點考科列出
            merge_sub_options = []
            if "刑總" in sub_pdf_map:
                merge_sub_options.append(f"⚖️ 【刑總】(收錄全科 {len(sub_pdf_map['刑總'])} 份講義與筆記)")
            if crim_pdfs:
                merge_sub_options.append(f"🌟 【刑法全輯】(刑總/刑分 共 {len(crim_pdfs)} 份)")
            if "身分法" in sub_pdf_map:
                merge_sub_options.append(f"⚖️ 【身分法】(收錄全科 {len(sub_pdf_map['身分法'])} 份講義與筆記)")
            if civil_pdfs:
                merge_sub_options.append(f"🌟 【民法全輯】(總則/債總/債各/物權/身分 共 {len(civil_pdfs)} 份)")
            if pub_pdfs:
                merge_sub_options.append(f"🌟 【公法全輯】(憲法/行政法 共 {len(pub_pdfs)} 份)")
            if comm_pdfs:
                merge_sub_options.append(f"🌟 【商事法全輯】(公司/證交/保險 共 {len(comm_pdfs)} 份)")
            if ip_pdfs:
                merge_sub_options.append(f"🌟 【智財全輯】(專利/商標/著作權 共 {len(ip_pdfs)} 份)")

            # 加入其餘個別考科
            for s, plist in sorted(sub_pdf_map.items(), key=lambda x: -len(x[1])):
                label_candidate = f"⚖️ 【{s}】(收錄全科 {len(plist)} 份講義與筆記)"
                if label_candidate not in merge_sub_options:
                    merge_sub_options.append(label_candidate)

            col_m1, col_m2 = st.columns([1.5, 1])
            with col_m1:
                sel_merge_opt = st.selectbox("🎯 選擇欲合併拼接為單一完整 PDF 之考科：", merge_sub_options, key="dev_sel_merge_sub")

            # 解析目標科目
            if "【" in sel_merge_opt and "】" in sel_merge_opt:
                target_sub = sel_merge_opt.split("【")[1].split("】")[0]
            else:
                target_sub = "刑總"

            # 取得對應 PDF 清單
            if target_sub == "刑法全輯":
                curr_target_files = crim_pdfs
            elif target_sub == "民法全輯":
                curr_target_files = civil_pdfs
            elif target_sub == "公法全輯":
                curr_target_files = pub_pdfs
            elif target_sub == "商事法全輯":
                curr_target_files = comm_pdfs
            elif target_sub == "智財全輯":
                curr_target_files = ip_pdfs
            else:
                curr_target_files = sub_pdf_map.get(target_sub, [])

            # 依體系章節法理順序排序
            sorted_target_files = sorted(curr_target_files, key=lambda x: (x.get("subject", ""), get_chapter_sort_key(Path(x["path"]))))

            st.info(f"📂 目前【**{target_sub}**】已定位 **{len(sorted_target_files)} 份** 原始 PDF 講義/筆記，系統將依據中文章節法理順序進行高精度拼接。")

            with st.expander(f"📋 點擊展開檢視【{target_sub}】拼接順序清單（共 {len(sorted_target_files)} 份）", expanded=False):
                for p_idx, pf in enumerate(sorted_target_files, 1):
                    st.write(f"{p_idx}. 📄 **《{pf.get('filename')}》** (`{pf.get('size_mb', 0):.2f} MB`) ｜ 考科：`{pf.get('subject')}`")

            st.markdown("---")
            st.markdown(f"### 📑 方案一：合併為《{target_sub}》單一完整 PDF")
            st.caption(f"自動依據章節法理順序高速拼接本考科所有 **{len(sorted_target_files)} 份** PDF，生成一個完整可離線劃記閱讀的超大 PDF。")

            if st.button(f"🚀 開始合併【{target_sub}】全科為單一完整 PDF", type="primary", key="dev_btn_run_merge_pdf"):
                with st.spinner(f"正在使用高精度 C++ 引擎依法理章節順序高速拼接【{target_sub}】所有 PDF..."):
                    try:
                        merge_res = merge_subject_pdfs(target_sub)
                        st.session_state[f"dev_merged_pdf_{target_sub}"] = merge_res
                        st.balloons()
                        st.success(f"🎉 合併成功！已生成單一完整 PDF：《{merge_res['output_path'].name}》")
                    except Exception as me:
                        st.error(f"合併失敗: {me}")

            if f"dev_merged_pdf_{target_sub}" in st.session_state:
                m_info = st.session_state[f"dev_merged_pdf_{target_sub}"]
                st.success(f"✅ 【{target_sub}】單一完整 PDF 總成已就緒！")
                st.info(f"📄 總頁數：**{m_info['total_pages']} 頁** ｜ 檔案大小：**{m_info['file_size_mb']:.2f} MB** ｜ 涵蓋講義筆記：**{m_info['file_count']} 份**")
                
                if m_info["output_path"].exists():
                    with open(m_info["output_path"], "rb") as f_pdf:
                        st.download_button(
                            label=f"⬇️ 立即下載《{m_info['output_path'].name}》({m_info['file_size_mb']:.2f} MB)",
                            data=f_pdf.read(),
                            file_name=m_info["output_path"].name,
                            mime="application/pdf",
                            key="dev_btn_dl_merged_pdf"
                        )

    # --------------------------------------------------------------------------
    # 分頁 4: 依內文智慧重命名大典
    # --------------------------------------------------------------------------
    with tab_rename:
        st.subheader("🪄 依據筆記內容智慧重命名大典 (Content-Based Renaming)")
        st.markdown("""
        許多由三星筆記 (Samsung Notes) 匯出的檔案皆為預設時間戳命名（例如 `債各_Notes_250220_100011.pdf`、`保險法_20251215_152009.jpg`），無法一眼辨識章節考點。  
        本引擎透過 **閱讀內文、識別法條（如民法第184條、保險法第53條）與 Gemini Flash 法學大模型**，自動建議標準法學檔名，並提供單檔精修與批次一鍵安全命名！
        """)

        r_mode = st.radio(
            "請選擇重命名模式：",
            ["⚡ 模式 A：單一檔案深度分析與精準重命名", "🚀 模式 B：全自動批次掃描與一鍵重命名向導"],
            horizontal=True,
            key="rename_work_mode"
        )

        # ----------------------------------------------------------------------
        # 模式 A: 單檔深度分析
        # ----------------------------------------------------------------------
        if "模式 A" in r_mode:
            st.markdown("### 🔍 單一檔案深度分析與重新命名")

            # 優先挑選待整理的原始檔案
            file_choices = [
                f"【{f['subject']}】{f['filename']}" + (" (⚠️ 原始時間戳)" if f["is_raw"] else "")
                for f in all_files
            ]
            sel_choice = st.selectbox("請選擇欲分析重命名之筆記檔案：", file_choices, key="rename_single_select")

            if sel_choice:
                c_idx = file_choices.index(sel_choice)
                target_f = all_files[c_idx]

                st.info(f"📄 當前選定檔案：**《{target_f['filename']}》** ｜ 考科：`{target_f['subject']}` ｜ 容量：`{target_f['size_str']}`")

                # AI 分析按鈕
                c_a1, c_a2 = st.columns([1.5, 2.5])
                with c_a1:
                    run_ai_analyze = st.button("🤖 啟動 AI 依內文分析並建議檔名", type="primary", key="btn_run_analyze_single")

                if run_ai_analyze or f"sug_res_{target_f['id']}" in st.session_state:
                    if run_ai_analyze:
                        with st.spinner("正在閱讀筆記內文、萃取法律條文並由 Gemini 評估最佳檔名..."):
                            sug = suggest_name_by_content(
                                target_f["path"],
                                known_subject=target_f["subject"],
                                use_ai=True
                            )
                            st.session_state[f"sug_res_{target_f['id']}"] = sug

                    sug = st.session_state[f"sug_res_{target_f['id']}"]

                    st.success(f"✨ 內文法理分析完成！（信心指標：`{sug['confidence']}`）")
                    st.markdown(f"**核心考科**：`{sug['subject']}`")
                    st.markdown(f"**核心條文**：{', '.join(f'`{l}`' for l in sug['core_laws']) if sug['core_laws'] else '無特定條文'}")
                    st.info(f"💡 **命名理由與考點摘要**：{sug['reasoning']}")

                    # 編輯與確認重命名輸入框
                    edited_new_name = st.text_input(
                        "建議新檔名（您可直接微調修改）：",
                        value=sug["suggested_filename"],
                        key=f"inp_edit_name_{target_f['id']}"
                    )

                    c_act1, c_act2 = st.columns([1.5, 2.5])
                    with c_act1:
                        if st.button("✅ 確認套用並執行磁碟重命名", type="primary", key=f"btn_confirm_rename_{target_f['id']}"):
                            with st.spinner("正在執行安全重命名、遷移快取與更新索引..."):
                                res = execute_rename_file(target_f["path"], edited_new_name)
                                if res["success"]:
                                    st.balloons()
                                    st.success(f"🎉 重命名成功！新檔名：`{res['new_filename']}`")
                                    # 記錄至 session 歷史以供 Undo
                                    st.session_state["dev_rename_history"].insert(0, res)
                                    time.sleep(1.2)
                                    st.rerun()
                                else:
                                    st.error(f"重命名失敗：{res.get('error')}")

        # ----------------------------------------------------------------------
        # 模式 B: 批次掃描向導
        # ----------------------------------------------------------------------
        else:
            st.markdown("### 🚀 全自動批次掃描與一鍵重命名向導")
            raw_files = [f for f in all_files if f["is_raw"]]
            st.write(f"目前全庫共偵測到 **{len(raw_files)} 份** 原始時間戳或未經語義整理的筆記檔案（如 `Notes_`、純數字檔名）。")

            if not raw_files:
                st.success("🎉 太棒了！全庫檔案皆已完成語義化命名，目前暫無待依內容整理的原始時間戳檔案。")
            else:
                col_b1, col_b2 = st.columns([2, 1])
                with col_b1:
                    batch_btn = st.button(
                        f"🔍 一鍵依內容批次掃描前 15 份原始筆記並生成智慧建議",
                        type="primary",
                        key="btn_run_batch_suggest"
                    )

                if batch_btn or "batch_rename_proposals" in st.session_state:
                    if batch_btn:
                        prog_b = st.progress(0.0)
                        status_b = st.empty()
                        proposals = []
                        target_batch = raw_files[:15]

                        for b_idx, bf in enumerate(target_batch, 1):
                            status_b.text(f"正在分析內文 [{b_idx}/{len(target_batch)}]: 《{bf['filename'][:25]}...》")
                            prog_b.progress(b_idx / len(target_batch))
                            sug = suggest_name_by_content(
                                bf["path"],
                                known_subject=bf["subject"],
                                use_ai=True
                            )
                            proposals.append({
                                "file_obj": bf,
                                "old_name": bf["filename"],
                                "suggested_name": sug["suggested_filename"],
                                "reasoning": sug["reasoning"],
                                "laws": sug["core_laws"]
                            })

                        prog_b.progress(1.0)
                        status_b.text("✅ 批次內文分析與建議生成完畢！")
                        st.session_state["batch_rename_proposals"] = proposals

                    proposals = st.session_state["batch_rename_proposals"]

                    st.markdown("#### 📋 批次重命名建議核准清單：")
                    st.caption("請檢視以下由 AI 依據筆記內文法條與爭點所推導之標準檔名，確認無誤後即可一鍵批次執行：")

                    approve_map = {}
                    for p_idx, prop in enumerate(proposals):
                        with st.container():
                            col_chk, col_pinfo = st.columns([1, 8])
                            with col_chk:
                                approved = st.checkbox("核准", value=True, key=f"chk_prop_{p_idx}")
                                approve_map[p_idx] = approved
                            with col_pinfo:
                                st.markdown(f"**原檔名**：`{prop['old_name']}`")
                                st.markdown(f"👉 **建議新檔名**：`{prop['suggested_name']}`")
                                st.caption(f"理由：{prop['reasoning']}")
                                st.divider()

                    if st.button("🚀 確認一鍵批次套用所有已核准之重命名", type="primary", key="btn_apply_batch_rename"):
                        success_c = 0
                        fail_c = 0
                        with st.spinner("正在批次執行磁碟重命名與快取遷移..."):
                            for p_idx, prop in enumerate(proposals):
                                if approve_map.get(p_idx, False):
                                    res = execute_rename_file(prop["file_obj"]["path"], prop["suggested_name"])
                                    if res["success"]:
                                        success_c += 1
                                        st.session_state["dev_rename_history"].insert(0, res)
                                    else:
                                        fail_c += 1

                        st.balloons()
                        st.success(f"🎉 批次重命名執行完成！成功：{success_c} 份，失敗：{fail_c} 份。")
                        del st.session_state["batch_rename_proposals"]
                        time.sleep(1.5)
                        st.rerun()

    # --------------------------------------------------------------------------
    # 分頁 4: 操作歷史審計與一鍵復原 (Undo)
    # --------------------------------------------------------------------------
    with tab_history:
        st.subheader("📜 重命名操作審計日誌與一鍵復原中心 (Undo)")
        st.caption("本系統完整記錄當前連線 Session 的所有重命名操作。若不慎更名或欲還原原始檔名，點擊復原按鈕即可無損復歸！")

        history = st.session_state["dev_rename_history"]

        if not history:
            st.info("💡 目前在此 Session 中尚未執行任何重命名操作。")
        else:
            for h_idx, h_item in enumerate(history):
                with st.container():
                    col_h1, col_h2 = st.columns([3, 1])
                    with col_h1:
                        st.markdown(f"**舊檔名**：`{h_item['old_filename']}`")
                        st.markdown(f"👉 **現檔名**：`{h_item['new_filename']}`")
                    with col_h2:
                        if st.button("↩️ 復原 (Undo)", key=f"btn_undo_{h_idx}"):
                            with st.spinner("正在復原原始檔名..."):
                                undo_res = execute_undo_rename(h_item)
                                if undo_res["success"]:
                                    st.success(f"✅ 已成功復原為《{undo_res['new_filename']}》！")
                                    history.pop(h_idx)
                                    time.sleep(1.0)
                                    st.rerun()
                                else:
                                    st.error(f"復原失敗：{undo_res.get('error')}")
                    st.divider()
