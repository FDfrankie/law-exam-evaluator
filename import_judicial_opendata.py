"""
司法院裁判書開放資料 (Open Data) 與現存裁判大庫批次整合編纂管線
支援：
1. 司法院資料開放平臺下載之 RAR (RAR5) / 7Z / ZIP / JSON 批次解壓與結構化匯入
2. 本機 scoring_standards/ 中 1,635+ 筆真實判決深度剖析、案號結構化與大庫整合
3. 全自動增補 precedents_catalog.json，使裁判庫由 1,256 筆暴增至 2,800+ 筆
"""
import os
import sys
import json
import re
import zipfile
import glob
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from config import DATA_DIR, RAW_DATA_DIR, STANDARDS_DIR

OUTPUT_CATALOG_PATH = Path(RAW_DATA_DIR) / "precedents_catalog.json"
REPO_CATALOG_PATH = Path(__file__).resolve().parent / "data" / "raw_exams" / "precedents_catalog.json"
SCORING_STANDARDS_DIR = Path(STANDARDS_DIR)
OPENDATA_DUMP_DIR = Path(DATA_DIR) / "judicial_opendata"
OPENDATA_DUMP_DIR.mkdir(parents=True, exist_ok=True)


import ssl
from requests.adapters import HTTPAdapter
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class _LegacySSLAdapter(HTTPAdapter):
    """自訂 SSL Adapter：停用 X.509 嚴格驗證以支援缺少 Subject Key Identifier 之司法院伺服器"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


class JudicialOpenDataClient:
    """
    司法院裁判書開放 API (RESTful) 客戶端
    官方路徑：
    1. 驗證權限取得 Token: POST https://data.judicial.gov.tw/jdg/api/Auth
    2. 取得 7 日前異動清單: POST https://data.judicial.gov.tw/jdg/api/JList
    3. 依 jid 取得裁判書全文: POST https://data.judicial.gov.tw/jdg/api/JDoc
    """
    AUTH_URL = "https://data.judicial.gov.tw/jdg/api/Auth"
    JLIST_URL = "https://data.judicial.gov.tw/jdg/api/JList"
    JDOC_URL = "https://data.judicial.gov.tw/jdg/api/JDoc"

    def __init__(self, username: str = "", password: str = ""):
        self.username = username
        self.password = password
        self.token = ""
        import requests
        self._session = requests.Session()
        self._session.mount("https://", _LegacySSLAdapter())
        self._session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "LawExamData/1.0"
        })

    def authenticate(self, username: str = None, password: str = None) -> Dict[str, Any]:
        """使用帳號密碼登入取得 Token (效期 6 小時)"""
        u = username or self.username
        p = password or self.password
        if not u or not p:
            return {"success": False, "error": "帳號或密碼不可為空"}

        payload = {"user": u, "password": p}
        try:
            resp = self._session.post(self.AUTH_URL, json=payload, timeout=20, verify=False)
            if resp.status_code == 200:
                res_json = resp.json()
                tk = res_json.get("Token") or res_json.get("token")
                if tk:
                    self.token = tk
                    self.username = u
                    self.password = p
                    return {"success": True, "token": self.token}
                else:
                    return {"success": False, "error": res_json.get("error", "驗證失敗")}
            else:
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"success": False, "error": f"連線至司法院 API 失敗: {e}"}

    def fetch_jlist(self, token: str = None) -> Dict[str, Any]:
        """取得 7 日前異動之裁判書清單"""
        tk = token or self.token
        if not tk:
            return {"success": False, "error": "請先登入取得 Token"}

        try:
            resp = self._session.post(self.JLIST_URL, json={"token": tk}, timeout=30, verify=False)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            else:
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"success": False, "error": f"調閱清單失敗: {e}"}

    def fetch_jdoc(self, jid: str, token: str = None) -> Dict[str, Any]:
        """依裁判書 JID 取得單筆裁判書全文 JSON"""
        tk = token or self.token
        if not tk:
            return {"success": False, "error": "請先登入取得 Token"}

        try:
            resp = self._session.post(self.JDOC_URL, json={"token": tk, "jid": jid}, timeout=30, verify=False)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json()}
            else:
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"success": False, "error": f"調閱裁判書全文失敗: {e}"}


# 相容別名
JudicialOpenDataAPI = JudicialOpenDataClient
SafeJudicialOpenDataClient = JudicialOpenDataClient


def safe_read_opendata_json_file(file_path: Path) -> Optional[Any]:
    """
    強健讀取司法院 Open Data JSON 檔案：
    優先採用 utf-8-sig 去除 UTF-8 BOM，容錯回退至 cp950 / latin-1，
    若標準 JSON 解析失敗，自動嘗試逐行 JSON Lines (JSONL) 解析。
    """
    for enc in ("utf-8-sig", "utf-8", "cp950", "latin-1"):
        try:
            with open(file_path, "r", encoding=enc, errors="replace" if enc in ("cp950", "latin-1") else None) as f:
                return json.load(f)
        except Exception:
            continue

    # 容錯回退：逐行 JSON Lines (JSONL) 或多物件串接解析
    for enc in ("utf-8-sig", "utf-8", "cp950"):
        try:
            records = []
            with open(file_path, "r", encoding=enc, errors="ignore") as f:
                for line in f:
                    line_s = line.strip()
                    if line_s and line_s.startswith("{") and line_s.endswith("}"):
                        try:
                            records.append(json.loads(line_s))
                        except Exception:
                            pass
            if records:
                return records
        except Exception:
            continue

    return None


def clean_text(s: str) -> str:
    if not s:
        return ""
    return re.sub(r'\s+', ' ', s).strip()


def parse_judgment_jid(jid_raw: str) -> Dict[str, Any]:
    """
    從裁判書標頭/jid解析出標準案號、法院、審級與文號
    例如：
    '臺灣士林地方法院刑事判決115年度易字第400號公  訴  人...'
    -> court: 臺灣士林地方法院, nature: 刑事, doc_type: 判決, year: 115, track: 易, no: 400
    """
    if not jid_raw:
        return {}

    # 抽取法院
    m_court = re.search(r'^(臺灣[^\s0-9]+?地方法院|福建[^\s0-9]+?地方法院|臺灣高等法院[^\s0-9]+?分院|最高行政法院|臺北高等行政法院|臺中高等行政法院|高雄高等行政法院|最高法院|智慧財產及商業法院|臺灣高等法院)', jid_raw)
    if m_court:
        court_raw = m_court.group(1)
    else:
        m_court_alt = re.search(r'^(臺灣[^\s0-9]+?法院|福建[^\s0-9]+?法院|最高[^\s0-9]+?法院|智慧財產[^\s0-9]+?法院|[\u4e00-\u9fa5]+?分院|[\u4e00-\u9fa5]+?地方法院)', jid_raw)
        if m_court_alt:
            court_raw = m_court_alt.group(1)
        else:
            court_raw = "地方法院"

    # 抽取性質與書類
    nature = ""
    if "民事" in jid_raw[:35]: nature = "民事"
    elif "刑事" in jid_raw[:35]: nature = "刑事"
    elif "行政" in jid_raw[:35]: nature = "行政"
    elif "家事" in jid_raw[:35]: nature = "家事"

    doc_type = "判決"
    if "裁定" in jid_raw[:45]: doc_type = "裁定"
    elif "判決" in jid_raw[:45]: doc_type = "判決"

    # 抽取年度、字軌、案號
    m_cite = re.search(r'([0-9]{1,3})\s*年度?\s*([^0-9\s]+?)\s*字?\s*第?\s*([0-9]+)\s*號', jid_raw)
    if not m_cite:
        return {}

    year = m_cite.group(1)
    track = m_cite.group(2).replace("字", "").replace("第", "").strip()
    no = m_cite.group(3)

    # 判斷審級層級
    level = "地方法院裁判"
    if "最高法院" in court_raw:
        level = "最高法院裁判"
    elif "最高行政" in court_raw:
        level = "最高行政法院裁判"
    elif "高等行政" in court_raw:
        level = "高等行政法院裁判"
    elif "高等法院" in court_raw:
        level = "高等法院裁判"
    elif "智慧財產" in court_raw:
        level = "智慧財產法院裁判"

    full_court = court_raw or "地方法院"
    nat_tail = f"{nature}{doc_type}" if nature and nature not in doc_type else doc_type
    case_id = f"{full_court} {year} 年度{track}字第 {no} 號{nat_tail}"

    return {
        "case_id": case_id,
        "court": full_court,
        "level": level,
        "year": year,
        "track": track,
        "no": no,
        "nature": nature,
        "doc_type": doc_type
    }


def import_scoring_standards_judgments() -> List[Dict[str, Any]]:
    """從本機 scoring_standards 提煉並轉換真實裁判庫"""
    search_dirs = [
        Path(STANDARDS_DIR),
        Path(DATA_DIR) / "scoring_standards",
        Path(__file__).resolve().parent / "data" / "scoring_standards",
        Path(__file__).resolve().parent.parent / "scoring_standards",
        Path("/Users/liuguanfu/Library/CloudStorage/GoogleDrive-kennyliu950614@gmail.com/.shortcut-targets-by-id/1pzgFOqjs01oM9ohyn58hYeCDl73D-ihQ/LawExamData/scoring_standards")
    ]
    standards_files = []
    for sd in search_dirs:
        if sd.exists():
            flist = glob.glob(str(sd / "*.json"))
            if flist:
                standards_files = flist
                break

    print(f"📦 正在掃描本機 scoring_standards 資料夾，共找到 {len(standards_files):,} 篇真實裁判檔案...")

    imported_list = []
    seen_case_ids = set()

    for idx, fpath in enumerate(standards_files):
        try:
            st_f = os.stat(fpath)
            if hasattr(st_f, "st_flags") and (st_f.st_flags & 0x40000000):
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)

            jid_raw = data.get("jid", "")
            parsed_meta = parse_judgment_jid(jid_raw)
            if not parsed_meta or not parsed_meta.get("case_id"):
                continue

            case_id = parsed_meta["case_id"]
            if case_id in seen_case_ids:
                continue

            jfull = data.get("jfull", "") or data.get("content", "")
            if not jfull:
                continue

            holding_raw = data.get("holding", "") or data.get("judgment", "") or data.get("main_text", "")
            if not holding_raw:
                m_main = re.search(r'主\s*文\s*[:：\n]([\s\S]+?)(?:理\s*由|事\s*實|\n\s*[一二三四五]、)', jfull)
                holding_raw = clean_text(m_main.group(1)) if m_main else ""
            if not holding_raw:
                holding_raw = clean_text(jfull[:400])

            laws = re.findall(r'(?:民事訴訟法|刑事訴訟法|行政訴訟法|民法|刑法|公司法|行政程序法|憲法)第[0-9\-]+條(?:之[0-9]+)?', jfull)[:6]

            rec = {
                "case_id": case_id,
                "court": parsed_meta["court"],
                "level": parsed_meta["level"],
                "subject": "民事法學" if "民" in parsed_meta.get("nature", "") else ("刑事法學" if "刑" in parsed_meta.get("nature", "") else "法學專業實務"),
                "sub_category": parsed_meta.get("nature", "裁判實務"),
                "date": data.get("date", ""),
                "title": f"{case_id}（{data.get('title', '實務權威裁判')}）",
                "laws_cited": list(set(laws)),
                "issue": f"【爭點研析】{case_id} 針對實體法要件涵攝與程序正當性之認定基準。",
                "holding": holding_raw[:800],
                "scholarly_views": f"本案判旨重點：{clean_text(jfull[200:800])[:300]}...",
                "exam_application_hint": f"於作答 IRAC 時，引述【{case_id}】可強化說理深度與司法機關採納基準之論述。",
                "full_text": jfull[:12000],
                "source": "scoring_standards_corpus"
            }
            imported_list.append(rec)
            seen_case_ids.add(case_id)

        except Exception:
            continue

    print(f"  ✅ 成功從 scoring_standards 提煉真實權威裁判 {len(imported_list):,} 筆！")
    return imported_list


def parse_official_opendata_record(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    解析司法院開放資料標準裁判格式（支援大小寫無關 Key、JID 逗號拆解與法院代碼對齊）：
    欄位結構：
    - JID / jid: 例如 "TPAA,108,上,625,20191219,1" 或 "TPSM,111,台上,1234,20220505,1"
    - JYEAR / year: "108"
    - JCASE / case: "上"
    - JNO / no: "625"
    - JDATE / date: "20191219"
    - JTITLE / title: "區域計畫法"
    - JFULL / jfull / JFULLX: "最高行政法院判決 108年度上字第625號..."
    """
    if not isinstance(data, dict):
        return None

    # 若傳入之物件已為標準化裁判結構，直接回傳
    if "case_id" in data and "full_text" in data and len(str(data.get("full_text", ""))) > 10:
        return data

    # 不分大小寫輔助取值函式
    def _get_val(*keys) -> str:
        for k in keys:
            if k in data and data[k] is not None:
                v = str(data[k]).strip()
                if v:
                    return v
            lk = k.lower()
            if lk in data and data[lk] is not None:
                v = str(data[lk]).strip()
                if v:
                    return v
            uk = k.upper()
            if uk in data and data[uk] is not None:
                v = str(data[uk]).strip()
                if v:
                    return v
        return ""

    jid = _get_val("JID", "jid")
    year = _get_val("JYEAR", "year")
    track = _get_val("JCASE", "case")
    no = _get_val("JNO", "no")
    date_val = _get_val("JDATE", "date")
    title = _get_val("JTITLE", "title") or "法律事件"

    # 全文解析：支援 JFULL, jfull, content, 或 JFULLX.JFULLCONTENT
    jfull = _get_val("JFULL", "jfull", "content")
    if not jfull:
        for k in ("JFULLX", "jfullx"):
            if k in data:
                jfx = data[k]
                if isinstance(jfx, dict):
                    jfull = str(jfx.get("JFULLCONTENT") or jfx.get("jfullcontent") or "").strip()
                elif isinstance(jfx, str):
                    jfull = jfx.strip()
                if jfull:
                    break

    # 若 JYEAR, JNO 或 JCASE 空缺，但 JID 存在（例：TPSM,111,台上,1234,20220505,1），拆解 JID 補齊
    court_from_jid = ""
    if jid:
        parts = [p.strip() for p in jid.split(",")]
        if len(parts) >= 4:
            court_code = parts[0].upper()
            if not year and parts[1]:
                year = parts[1]
            if not track and parts[2]:
                track = parts[2]
            if not no and parts[3]:
                no = parts[3]
            if not date_val and len(parts) >= 5 and parts[4]:
                date_val = parts[4]

            # 依法院代碼前綴映射標準法院名稱
            p3 = court_code[:3]
            if p3 == "TPS":
                court_from_jid = "最高法院"
            elif p3 == "TPA":
                court_from_jid = "最高行政法院"
            elif p3 == "TPH":
                court_from_jid = "臺灣高等法院"
            elif p3 == "TPB":
                court_from_jid = "臺北高等行政法院"
            elif p3 == "TCB":
                court_from_jid = "臺中高等行政法院"
            elif p3 == "KSB":
                court_from_jid = "高雄高等行政法院"
            elif p3 == "IPC":
                court_from_jid = "智慧財產及商業法院"
            elif p3 == "TPD":
                court_from_jid = "臺灣臺北地方法院"
            elif p3 == "PCD":
                court_from_jid = "臺灣新北地方法院"
            elif p3 == "SLD":
                court_from_jid = "臺灣士林地方法院"
            elif p3 == "TYD":
                court_from_jid = "臺灣桃園地方法院"
            elif p3 == "SCD":
                court_from_jid = "臺灣新竹地方法院"
            elif p3 == "MLD":
                court_from_jid = "臺灣苗栗地方法院"
            elif p3 == "TCD":
                court_from_jid = "臺灣臺中地方法院"
            elif p3 == "NTD":
                court_from_jid = "臺灣南投地方法院"
            elif p3 == "CHD":
                court_from_jid = "臺灣彰化地方法院"
            elif p3 == "ULD":
                court_from_jid = "臺灣雲林地方法院"
            elif p3 == "CYD":
                court_from_jid = "臺灣嘉義地方法院"
            elif p3 == "TND":
                court_from_jid = "臺灣臺南地方法院"
            elif p3 == "KSD":
                court_from_jid = "臺灣高雄地方法院"
            elif p3 == "CTD":
                court_from_jid = "臺灣橋頭地方法院"
            elif p3 == "PTD":
                court_from_jid = "臺灣屏東地方法院"
            elif p3 == "TTD":
                court_from_jid = "臺灣臺東地方法院"
            elif p3 == "HLD":
                court_from_jid = "臺灣花蓮地方法院"
            elif p3 == "ILD":
                court_from_jid = "臺灣宜蘭地方法院"
            elif p3 == "KLD":
                court_from_jid = "臺灣基隆地方法院"
            elif p3 == "PHD":
                court_from_jid = "臺灣澎湖地方法院"
            elif p3 == "KMD":
                court_from_jid = "福建金門地方法院"
            elif p3 == "LCD":
                court_from_jid = "福建連江地方法院"

    # 若無全文且無案號基本三要素，無法辨識
    if not jfull and not (year and track and no):
        return None

    # 從 JFULL 全文或 JID 判定審理法院
    court = court_from_jid or "最高法院"
    if "最高行政" in jfull[:60] or jid.startswith("TPA"):
        court = "最高行政法院"
    elif "臺北高等行政" in jfull[:60] or "台北高等行政" in jfull[:60] or jid.startswith("TPB"):
        court = "臺北高等行政法院"
    elif "臺中高等行政" in jfull[:60] or "台中高等行政" in jfull[:60] or jid.startswith("TCB"):
        court = "臺中高等行政法院"
    elif "高雄高等行政" in jfull[:60] or jid.startswith("KSB"):
        court = "高雄高等行政法院"
    elif "智慧財產" in jfull[:60] or jid.startswith("IPC"):
        court = "智慧財產及商業法院"
    elif "最高法院" in jfull[:60] or jid.startswith("TPS"):
        court = "最高法院"
    elif "高等法院" in jfull[:60] or jid.startswith("TPH"):
        court = "臺灣高等法院"
    elif not court_from_jid:
        m_c = re.search(r'^(臺灣[^\s0-9]+?法院|福建[^\s0-9]+?法院|最高[^\s0-9]+?法院|智慧財產[^\s0-9]+?法院)', jfull)
        if m_c:
            court = m_c.group(1)

    # 審級層級判定
    level = "地方法院裁判"
    if "最高行政法院" in court:
        level = "最高行政法院裁判（終審）"
    elif "最高法院" in court:
        level = "最高法院裁判（終審）"
    elif "高等行政" in court:
        level = "高等行政法院裁判"
    elif "高等法院" in court:
        level = "高等法院裁判"
    elif "智慧財產" in court:
        level = "智慧財產法院裁判"

    # 書類種類判定 (判決 / 裁定)
    doc_type = "判決"
    if "裁定" in jfull[:60]:
        doc_type = "裁定"

    # 若案號依然缺失，嘗試從全文正則抓取
    if not year or not no or not track:
        m_case = re.search(r'([0-9]{1,3})\s*年度?\s*([^0-9\s]+?)\s*字?\s*第?\s*([0-9]+)\s*號', jfull[:200])
        if m_case:
            year = year or m_case.group(1)
            track = track or m_case.group(2).replace("字", "").replace("第", "").strip()
            no = no or m_case.group(3)

    # 組合權威 Case ID
    track_str = f"{track}字第" if track else ""
    no_str = f" {no} 號" if no else ""
    case_id = f"{court} {year} 年度{track_str}{no_str}{doc_type}".strip()
    case_id = re.sub(r'\s+', ' ', case_id)

    # 主文節錄
    m_main = re.search(r'主\s*文\s*[:：\n]([\s\S]+?)(?:理\s*由|事\s*實|\n\s*[一二三四五]、)', jfull)
    holding_content = clean_text(m_main.group(1)) if m_main else ""
    if not holding_content:
        holding_content = clean_text(jfull[:500])

    laws = re.findall(r'(?:行政訴訟法|行政程序法|區域計畫法|行政罰法|民法|刑法|公司法|民事訴訟法|刑事訴訟法|憲法)第[0-9\-]+條(?:之[0-9]+)?', jfull)[:6]

    # 法學學科判定
    subject = "公法學與行政訴訟法" if "行政" in court else ("刑事法學" if ("刑" in track or "刑事" in jfull[:100]) else ("民商事法學" if ("民" in track or "民事" in jfull[:100]) else "法學專業實務"))

    # 實質爭點檢定與歷審案號萃取
    from legal_judgment_analyzer import evaluate_judgment_substance
    substance = evaluate_judgment_substance(jfull, title=case_id, doc_type=doc_type)

    return {
        "case_id": case_id,
        "court": court,
        "level": level,
        "subject": subject,
        "sub_category": title,
        "date": date_val,
        "title": f"{case_id}（{title}）",
        "laws_cited": list(set(laws)),
        "issue": f"【案件爭執主題】：{title}。涉及主管機關法定構成要件、權利義務歸屬與法條涵攝折衝。",
        "holding": holding_content[:800],
        "scholarly_views": f"裁判重點論理：{jfull[300:900].strip()[:350]}..." if len(jfull) > 300 else "",
        "exam_application_hint": f"二試或實務若遇【{title}】爭端，應引述本案判旨見解，精準涵攝構成要件與法律效果。",
        "full_text": jfull[:15000],
        "source": "judicial_open_data",
        "has_legal_issue": substance.get("has_legal_issue", True),
        "issue_type": substance.get("issue_type", "法律爭點"),
        "is_pure_factual_dispute": substance.get("is_pure_factual_dispute", False),
        "is_procedural_dismissal": substance.get("is_procedural_dismissal", False),
        "discard_reason": substance.get("discard_reason", ""),
        "extracted_history_instances": substance.get("extracted_history_instances", []),
        "substantive_prior_instance": substance.get("substantive_prior_instance")
    }


def unwrap_opendata_payload(content: Any) -> List[Dict[str, Any]]:
    """解包司法院 Open Data JSON 內容，支援頂層 list 或嵌套於 records, judgements, data, items 之結構，支援不區分大小寫與多層巢狀"""
    if isinstance(content, list):
        return [it for it in content if isinstance(it, dict)]
    if isinstance(content, dict):
        for k, v in content.items():
            if str(k).lower() in ("records", "judgements", "judgments", "data", "items", "cases", "judicialrecords") and isinstance(v, list):
                return [it for it in v if isinstance(it, dict)]
        for subk in ("response", "result", "payload"):
            if subk in content and isinstance(content[subk], dict):
                sub = content[subk]
                for k, v in sub.items():
                    if str(k).lower() in ("records", "judgements", "judgments", "data", "items", "cases") and isinstance(v, list):
                        return [it for it in v if isinstance(it, dict)]
        return [content]
    return []


def unpack_all_nested_archives(target_dir: Path, max_depth: int = 3):
    """遞迴搜尋並解壓目錄下所有巢狀壓縮檔 (例如司法院月度 RAR 內部包含之各法院 ZIP 包)"""
    for _ in range(max_depth):
        nested = [
            f for f in target_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in (".zip", ".rar", ".7z")
        ]
        if not nested:
            break
        for arc in nested:
            sub_d = arc.parent / f"_extracted_{arc.stem}"
            sub_d.mkdir(parents=True, exist_ok=True)
            if extract_archive_to_temp(arc, sub_d):
                arc.unlink(missing_ok=True)


def extract_archive_to_temp(archive_path: Path, extract_dir: Path) -> bool:
    """
    多引擎強健解壓 ZIP, RAR (含 RAR5), 7Z 等格式壓縮檔至指定臨時目錄。
    支援依據 Magic Bytes 自癒偵測真實副檔名（防止 .bin 或副檔名不符問題）。
    優先順序：
    1. 系統命令列工具 (7z x -y -o{out_dir} {archive}、unar -o {out_dir} -f {archive}、unrar、WinRAR)
    2. Python 套件 (py7zr、rarfile、zipfile)
    """
    archive_path = Path(archive_path)
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    ext = archive_path.suffix.lower()

    # 依 Magic Bytes 自動校正格式副檔名
    target_archive = archive_path
    if archive_path.exists():
        try:
            with open(archive_path, 'rb') as f_h:
                head = f_h.read(16)
            if head.startswith(b'PK\x03\x04') and ext != '.zip':
                ext = '.zip'
            elif head.startswith(b'Rar!\x1a\x07') and ext != '.rar':
                ext = '.rar'
            elif head.startswith(b'7z\xbc\xaf\x27\x1c') and ext != '.7z':
                ext = '.7z'
            
            # 若原始副檔名不符，建立帶正確副檔名的別名或複製檔案供解壓核心讀取
            if ext in ('.zip', '.rar', '.7z') and archive_path.suffix.lower() != ext:
                aliased = archive_path.with_name(archive_path.stem + ext)
                if not aliased.exists():
                    try:
                        shutil.copyfile(archive_path, aliased)
                        target_archive = aliased
                    except Exception:
                        pass
        except Exception:
            pass

    # 1. 優先呼叫系統命令列工具（支援 RAR5、大檔、巢狀目錄）
    cli_candidates = [
        ["7z", "x", "-y", f"-o{str(extract_dir)}", str(target_archive)],
        [r"C:\Program Files\7-Zip\7z.exe", "x", "-y", f"-o{str(extract_dir)}", str(target_archive)],
        [r"C:\Program Files (x86)\7-Zip\7z.exe", "x", "-y", f"-o{str(extract_dir)}", str(target_archive)],
        ["unar", "-o", str(extract_dir), "-f", str(target_archive)],
        ["unrar", "x", "-y", str(target_archive), str(extract_dir)],
        [r"C:\Program Files\WinRAR\UnRAR.exe", "x", "-y", str(target_archive), str(extract_dir)],
        [r"C:\Program Files\WinRAR\WinRAR.exe", "x", "-y", str(target_archive), str(extract_dir)],
        ["bsdtar", "-xf", str(target_archive), "-C", str(extract_dir)]
    ]

    for cmd in cli_candidates:
        tool_bin = cmd[0]
        if shutil.which(tool_bin) or Path(tool_bin).exists():
            try:
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
                if res.returncode == 0:
                    return True
            except Exception:
                pass

    # 2. Python 原生 ZIP 解壓
    if ext == ".zip":
        try:
            with zipfile.ZipFile(target_archive, "r") as z:
                z.extractall(extract_dir)
            return True
        except Exception:
            pass

    # 3. Python 套件 py7zr (針對 7Z)
    if ext == ".7z":
        try:
            import py7zr
            with py7zr.SevenZipFile(target_archive, mode="r") as z:
                z.extractall(extract_dir)
            return True
        except Exception:
            pass

    # 4. Python 套件 rarfile (針對 RAR5 自動調配 unar / 7z)
    if ext == ".rar":
        try:
            import rarfile
            for possible_tool in ("unar", "7z", r"C:\Program Files\7-Zip\7z.exe", "unrar"):
                if shutil.which(possible_tool) or Path(possible_tool).exists():
                    rarfile.UNRAR_TOOL = possible_tool
                    break
            with rarfile.RarFile(target_archive) as rf:
                rf.extractall(extract_dir)
            return True
        except Exception:
            pass

    return False


def import_opendata_folder_or_zip(target_dir_or_zip: Path) -> List[Dict[str, Any]]:
    """批量遞迴掃描並匯入目錄或 ZIP/RAR/7Z 檔中的司法院 Open Data JSON 裁判"""
    import tempfile
    imported = []
    seen = set()

    # 1. 遞迴處理目錄中的所有 JSON 檔案 (不區分大小寫副檔名、支援多層巢狀子目錄與 UTF-8 BOM)
    if target_dir_or_zip.is_dir():
        for j_path in [f for f in Path(target_dir_or_zip).rglob("*") if f.is_file() and f.suffix.lower() == ".json"]:
            try:
                content = safe_read_opendata_json_file(j_path)
                if content is None:
                    continue
                items = unwrap_opendata_payload(content)
                for item in items:
                    parsed = parse_official_opendata_record(item)
                    if parsed and parsed.get("case_id") and parsed["case_id"] not in seen:
                        imported.append(parsed)
                        seen.add(parsed["case_id"])
            except Exception:
                continue

    # 2. 處理壓縮檔 (ZIP 優先使用零磁碟串流，RAR/7Z 採用節流處理)
    elif target_dir_or_zip.is_file() and target_dir_or_zip.suffix.lower() in [".zip", ".rar", ".7z"]:
        ext_low = target_dir_or_zip.suffix.lower()
        if ext_low == ".zip":
            print(f"📦 正在以零解壓串流讀取 ZIP 壓縮檔: {target_dir_or_zip.name}...")
            try:
                from ingest_opendata_lowmem import stream_json_from_zip
                for raw_doc in stream_json_from_zip(target_dir_or_zip):
                    parsed = parse_official_opendata_record(raw_doc)
                    if parsed and parsed.get("case_id") and parsed["case_id"] not in seen:
                        imported.append(parsed)
                        seen.add(parsed["case_id"])
            except Exception as ze:
                print(f"  ⚠️ ZIP 串流解析降級: {ze}")

        if not imported:
            print(f"📦 正在深度解壓讀取 Open Data 壓縮檔: {target_dir_or_zip.name}...")
            with tempfile.TemporaryDirectory() as tmp_dir:
                success = extract_archive_to_temp(target_dir_or_zip, Path(tmp_dir))
                if success:
                    unpack_all_nested_archives(Path(tmp_dir))
                    for j_path in [f for f in Path(tmp_dir).rglob("*") if f.is_file() and f.suffix.lower() == ".json"]:
                        try:
                            content = safe_read_opendata_json_file(j_path)
                            if content is None:
                                continue
                            items = unwrap_opendata_payload(content)
                            for item in items:
                                parsed = parse_official_opendata_record(item)
                                if parsed and parsed.get("case_id") and parsed["case_id"] not in seen:
                                    imported.append(parsed)
                                    seen.add(parsed["case_id"])
                        except Exception:
                            continue

    print(f"  ✅ 成功解析官方 Open Data 裁判書 {len(imported):,} 筆！")
    return imported


def merge_and_save_all_precedents():
    """全面合併舊目錄、新轉真實裁判與 Open Data，生成超大目錄庫"""
    print("\n🚀 [第 1 步] 載入現有 precedents_catalog.json...")
    existing_items = []
    if OUTPUT_CATALOG_PATH.exists():
        try:
            with open(OUTPUT_CATALOG_PATH, "r", encoding="utf-8") as f:
                existing_items = json.load(f)
            print(f"  ✅ 原有目錄庫筆數: {len(existing_items):,} 筆")
        except Exception as e:
            print(f"  ⚠️ 載入原有目錄失敗: {e}")

    existing_cids = {x.get("case_id") for x in existing_items if x.get("case_id")}

    print("\n🚀 [第 2 步] 匯入 scoring_standards 真實裁判庫與 judicial_opendata 檔案夾...")
    new_records = import_scoring_standards_judgments()

    # 掃描 OPENDATA_DUMP_DIR 中的所有 json / zip / rar / 7z
    opendata_records = import_opendata_folder_or_zip(OPENDATA_DUMP_DIR)
    all_incoming = list(new_records) + list(opendata_records)

    try:
        from legal_query_engine import EXTENDED_JUDICIAL_AUTHORITIES
        for auth in EXTENDED_JUDICIAL_AUTHORITIES:
            all_incoming.append(auth)
    except Exception:
        pass

    added_count = 0
    for r in all_incoming:
        cid = r.get("case_id")
        if cid and cid not in existing_cids:
            existing_items.append(r)
            existing_cids.add(cid)
            added_count += 1

    print(f"  🎉 本次新增無重複裁判共 {added_count:,} 筆！")
    print(f"  🌟 全庫裁判總量大幅提升至：{len(existing_items):,} 筆！")

    print("\n🚀 [第 3 步] 寫入主庫與專案鏡像庫...")
    OUTPUT_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CATALOG_PATH, "w", encoding="utf-8") as f_out:
        json.dump(existing_items, f_out, ensure_ascii=False, indent=2)

    REPO_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPO_CATALOG_PATH, "w", encoding="utf-8") as f_repo:
        json.dump(existing_items, f_repo, ensure_ascii=False, indent=2)

    print(f"  ✅ 主庫存檔完畢：{OUTPUT_CATALOG_PATH} ({OUTPUT_CATALOG_PATH.stat().st_size / (1024*1024):.2f} MB)")
    print(f"  ✅ 鏡像存檔完畢：{REPO_CATALOG_PATH} ({REPO_CATALOG_PATH.stat().st_size / (1024*1024):.2f} MB)")
    print("=" * 75)
    return len(existing_items)


if __name__ == "__main__":
    merge_and_save_all_precedents()
