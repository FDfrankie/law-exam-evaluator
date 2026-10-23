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
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# 現代化 Gemini 核心模型後備階梯（依序降級，保證模型 ID 有效，避免 404 重試延遲與預覽版 429 配額為 0 之錯誤）
GEMINI_FALLBACK_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-flash-latest",
    "gemini-pro-latest"
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
        return Path(custom_dir)

    # Priority 0: Streamlit Cloud persistent data mount
    streamlit_mount = Path("/mount/src/law-exam-evaluator/data")
    if streamlit_mount.exists():
        return streamlit_mount
    
    # Priority 1: Check if Google Drive directory exists on macOS
    macos_candidates = [
        Path.home() / "Library/CloudStorage/GoogleDrive-kennyliu950614@gmail.com/.shortcut-targets-by-id/1pzgFOqjs01oM9ohyn58hYeCDl73D-ihQ/LawExamData",
        Path("/Users/liuguanfu/Library/CloudStorage/GoogleDrive-kennyliu950614@gmail.com/.shortcut-targets-by-id/1pzgFOqjs01oM9ohyn58hYeCDl73D-ihQ/LawExamData")
    ]
    for m_path in macos_candidates:
        if m_path.exists():
            return m_path

    # Priority 2: Check if Google Drive directory exists on Windows
    for g_path in [Path("G:/我的雲端硬碟/LawExamData"), Path("G:/My Drive/LawExamData")]:
        if g_path.exists():
            return g_path
            
    # Priority 3: Repository local data directory (for Streamlit Cloud / Linux / cloned repo)
    local_data = Path(__file__).resolve().parent / "data"
    if local_data.exists():
        return local_data
        
    # Priority 4: Fallback to G: drive parent if user is setting up Google Drive
    for g_path in [Path("G:/我的雲端硬碟/LawExamData"), Path("G:/My Drive/LawExamData")]:
        if g_path.parent.exists():
            return g_path

    return local_data


DATA_DIR = get_base_data_dir()
GOOGLE_DRIVE_DATA_DIR = str(DATA_DIR)

RAW_DATA_DIR = DATA_DIR / "raw_exams"
STANDARDS_DIR = DATA_DIR / "scoring_standards"
STUDENT_PAPERS_DIR = DATA_DIR / "student_submissions"
REPORTS_DIR = DATA_DIR / "evaluation_reports"
CONSTITUTIONAL_DIR = DATA_DIR / "constitutional_cases"
NATIONAL_LAWS_DIR = DATA_DIR / "national_laws" if (DATA_DIR / "national_laws").exists() else (DATA_DIR.parent / "national_laws" if (DATA_DIR.parent / "national_laws").exists() else DATA_DIR / "national_laws")
TRAINING_DATA_DIR = DATA_DIR / "training_data"
SAMSUNG_NOTES_DIR = DATA_DIR / "SamsungNotes"
MODEL_WEIGHTS_DIR = DATA_DIR / "model_weights"
JUDICIAL_1M_DIR = DATA_DIR / "judicial_1m_db" if (DATA_DIR / "judicial_1m_db").exists() else (DATA_DIR / "data" / "judicial_1m_db" if (DATA_DIR / "data" / "judicial_1m_db").exists() else DATA_DIR / "judicial_1m_db")
OPENDATA_INBOX_DIR = DATA_DIR / "opendata_inbox" if (DATA_DIR / "opendata_inbox").exists() else (DATA_DIR / "data" / "opendata_inbox" if (DATA_DIR / "data" / "opendata_inbox").exists() else DATA_DIR / "opendata_inbox")
JUDGEMENTS_DIR = DATA_DIR / "data" / "judgements" if (DATA_DIR / "data" / "judgements").exists() else (DATA_DIR / "judgements" if (DATA_DIR / "judgements").exists() else DATA_DIR / "data" / "judgements")

def init_directories():
    """Ensure data directories exist"""
    for folder in [
        RAW_DATA_DIR, STANDARDS_DIR, STUDENT_PAPERS_DIR, REPORTS_DIR,
        CONSTITUTIONAL_DIR, NATIONAL_LAWS_DIR, TRAINING_DATA_DIR,
        SAMSUNG_NOTES_DIR, JUDICIAL_1M_DIR, OPENDATA_INBOX_DIR, JUDGEMENTS_DIR
    ]:
        try:
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
