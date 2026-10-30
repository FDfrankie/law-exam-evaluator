import sys
import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        try:
            load_dotenv(env_path)
        except Exception:
            pass
except ImportError:
    pass

def get_gemini_api_key() -> str:
    """Get Gemini API Key from Streamlit Secrets or Environment Variables"""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        try:
            import streamlit as st
            if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
                key = str(st.secrets["GEMINI_API_KEY"]).strip()
        except Exception:
            pass
    return key

GEMINI_API_KEY = get_gemini_api_key()
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

# 現行有效之 Google Gemini 官方生產環境模型清單（首選最快最穩定的最新端點，依序故障轉移）
GEMINI_FALLBACK_MODELS = [
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.8-flash"
]

def get_gemini_models_to_try(primary_model: str = None) -> list:
    """Return prioritized list of Gemini model candidates for resilient fallback."""
    models = []
    if primary_model and primary_model not in models:
        models.append(primary_model)
    if DEFAULT_GEMINI_MODEL not in models:
        models.append(DEFAULT_GEMINI_MODEL)
    for m in GEMINI_FALLBACK_MODELS:
        if m not in models:
            models.append(m)
    return models

def get_base_data_dir() -> Path:
    custom_dir = os.getenv("GOOGLE_DRIVE_DATA_DIR")
    if custom_dir and Path(custom_dir).exists():
        p = Path(custom_dir)
        return p if p.name == "data" else p / "data"

    # Priority 0: Streamlit Cloud persistent data mount
    streamlit_mount = Path("/mount/src/law-exam-evaluator/data")
    if streamlit_mount.exists():
        return streamlit_mount

    # Priority 1: Standard Project Root & Data Dir Resolution
    curr = Path(__file__).resolve().parent
    if (curr.parent / "data").exists() and (curr.parent / "data" / "judicial_authority.db").exists():
        return curr.parent / "data"

    project_root = curr if (curr / "data").exists() else curr.parent
    return project_root / "data"


PROJECT_ROOT = Path(__file__).resolve().parent if (Path(__file__).resolve().parent / "data").exists() else Path(__file__).resolve().parent.parent
DATA_DIR = get_base_data_dir()
if not DATA_DIR.exists() and (PROJECT_ROOT / "data").exists():
    DATA_DIR = PROJECT_ROOT / "data"
PROJECT_ROOT = DATA_DIR.parent
GOOGLE_DRIVE_DATA_DIR = str(DATA_DIR)


def resolve_data_subdir(name: str) -> Path:
    p_data = DATA_DIR / name
    if p_data.exists():
        return p_data
    p_root = PROJECT_ROOT / name
    if p_root.exists():
        return p_root
    return p_data


RAW_DATA_DIR = resolve_data_subdir("raw_exams")
STANDARDS_DIR = resolve_data_subdir("scoring_standards")
STUDENT_PAPERS_DIR = resolve_data_subdir("student_submissions")
REPORTS_DIR = resolve_data_subdir("evaluation_reports")
CONSTITUTIONAL_DIR = resolve_data_subdir("constitutional_cases")
NATIONAL_LAWS_DIR = resolve_data_subdir("national_laws")
TRAINING_DATA_DIR = resolve_data_subdir("training_data")
SAMSUNG_NOTES_DIR = resolve_data_subdir("SamsungNotes")
MODEL_WEIGHTS_DIR = resolve_data_subdir("model_weights")
JUDICIAL_1M_DIR = resolve_data_subdir("judicial_1m_db")
OPENDATA_INBOX_DIR = resolve_data_subdir("opendata_inbox")
DEFAULT_WINDOWS_JUDGEMENTS_DIR = DATA_DIR / "judgements"


def get_judgements_dir() -> Path:
    """獲取裁判壓縮包 (.rar, .7z, .zip) 監控目錄，自動適配本機 Windows、macOS 與 Linux/Streamlit Cloud"""
    # 0. 環境變數或 Streamlit secrets 顯式設定
    custom_j = os.getenv("JUDGEMENTS_DIR")
    if not custom_j:
        try:
            import streamlit as st
            if hasattr(st, "secrets") and "JUDGEMENTS_DIR" in st.secrets:
                custom_j = str(st.secrets["JUDGEMENTS_DIR"]).strip()
        except Exception:
            pass
    if custom_j and Path(custom_j).exists():
        return Path(custom_j)

    # 1. 主資料目錄下的 judgements
    j_data = DATA_DIR / "judgements"
    if j_data.exists():
        return j_data

    # 2. 專案根目錄備選 judgements
    j_root = PROJECT_ROOT / "judgements"
    if j_root.exists():
        return j_root

    # 3. 本地 repo data/judgements
    repo_j = Path(__file__).resolve().parent / "data" / "judgements"
    if repo_j.exists():
        return repo_j

    try:
        if not j_data.exists():
            j_data.mkdir(parents=True, exist_ok=True)
    except (FileExistsError, OSError):
        pass
    return j_data

JUDGEMENTS_DIR = get_judgements_dir()

def init_directories():
    """Ensure data directories exist"""
    for folder in [
        RAW_DATA_DIR, STANDARDS_DIR, STUDENT_PAPERS_DIR, REPORTS_DIR,
        CONSTITUTIONAL_DIR, NATIONAL_LAWS_DIR, TRAINING_DATA_DIR,
        SAMSUNG_NOTES_DIR, JUDICIAL_1M_DIR, OPENDATA_INBOX_DIR, JUDGEMENTS_DIR
    ]:
        try:
            # 避免在 Linux/macOS 環境下對 Windows 磁碟槽路徑（如 G:\...）進行無效 mkdir
            folder_str = str(folder)
            if sys.platform != "win32" and (folder_str.startswith(("G:", "g:", "C:", "c:", "D:", "d:")) or ":" in folder_str[:3]):
                continue
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[DIR ERROR] Failed creating {folder}: {e}")

def safe_requests_get(url: str, session=None, **kwargs):
    """
    發送 HTTP GET：嚴格遵循標準 TLS/SSL 憑證安全驗證 (verify=True)。
    為防範中間人攻擊 (MITM) 與靜默降級風險，預設絕不自動停用 SSL 驗證。
    僅在使用者顯式配置環境變數 LEGAL_ALLOW_INSECURE_SSL=1 的受信任測試情境下，
    才允許對缺少台灣政府 (GRCA) 根憑證的機關伺服器以相容模式連線。
    """
    import requests
    req = session.get if session else requests.get

    allow_insecure = os.getenv("LEGAL_ALLOW_INSECURE_SSL", "0").lower() in ("1", "true", "yes")

    try:
        return req(url, verify=True, **kwargs)
    except requests.exceptions.SSLError as e:
        if allow_insecure:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            print(f"  [SECURITY WARNING] 已啟用 LEGAL_ALLOW_INSECURE_SSL，降級以 verify=False 重試: {url}")
            return req(url, verify=False, **kwargs)
        raise requests.exceptions.SSLError(
            f"TLS/SSL 憑證驗證失敗：無法安全連線至 {url} (原因: {e})。\n"
            "系統嚴格遵循安全標準，預設禁止不安全之非驗證連線。\n"
            "若確認目標為政府機關且本機缺少 GRCA 根憑證，並確知連線環境安全，"
            "請顯式設定環境變數 LEGAL_ALLOW_INSECURE_SSL=1。"
        ) from e

if __name__ == "__main__":
    init_directories()
    print("API Key Status:", "Configured" if GEMINI_API_KEY else "Not configured")
    print("Data Directory:", DATA_DIR)
