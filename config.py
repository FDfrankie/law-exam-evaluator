import os
from pathlib import Path
from dotenv import load_dotenv

# Load local .env
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

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
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

def get_base_data_dir() -> Path:
    custom_dir = os.getenv("GOOGLE_DRIVE_DATA_DIR")
    if custom_dir:
        return Path(custom_dir)
    
    # Check if Google Drive exists on Windows
    for g_path in [Path("G:/我的雲端硬碟/LawExamData"), Path("G:/My Drive/LawExamData")]:
        if g_path.parent.exists():
            return g_path
            
    # Fallback to local data directory (e.g. for Streamlit Cloud / Linux)
    return Path(__file__).resolve().parent / "data"

DATA_DIR = get_base_data_dir()
GOOGLE_DRIVE_DATA_DIR = str(DATA_DIR)

RAW_DATA_DIR = DATA_DIR / "raw_exams"
STANDARDS_DIR = DATA_DIR / "scoring_standards"
STUDENT_PAPERS_DIR = DATA_DIR / "student_submissions"
REPORTS_DIR = DATA_DIR / "evaluation_reports"
CONSTITUTIONAL_DIR = DATA_DIR / "constitutional_cases"
NATIONAL_LAWS_DIR = DATA_DIR / "national_laws"
TRAINING_DATA_DIR = DATA_DIR / "training_data"
SAMSUNG_NOTES_DIR = DATA_DIR / "SamsungNotes"
MODEL_WEIGHTS_DIR = DATA_DIR / "model_weights"

def init_directories():
    """Ensure data directories exist"""
    for folder in [
        RAW_DATA_DIR, STANDARDS_DIR, STUDENT_PAPERS_DIR, REPORTS_DIR,
        CONSTITUTIONAL_DIR, NATIONAL_LAWS_DIR, TRAINING_DATA_DIR,
        SAMSUNG_NOTES_DIR, MODEL_WEIGHTS_DIR
    ]:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[DIR ERROR] Failed creating {folder}: {e}")

def safe_requests_get(url: str, session=None, **kwargs):
    """
    發送 HTTP GET：優先嚴格遵循標準 TLS/SSL 憑證驗證；
    若因本機作業系統未預載台灣政府 (GRCA) 根憑證而導致 SSLError，
    發出明確日誌警示後以相容模式降級重試，避免無條件靜默關閉安全性驗證。
    """
    import requests
    req = session.get if session else requests.get
    
    # 讀取環境變數強制設定 (預設優先驗證)
    enforce_ssl = os.getenv("LEGAL_SSL_VERIFY", "true").lower() in ("true", "1", "yes")
    if not enforce_ssl:
        return req(url, verify=False, **kwargs)

    try:
        return req(url, verify=True, **kwargs)
    except requests.exceptions.SSLError as e:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        print(f"  [SSL 憑證警告] 本機缺少台灣政府 (GRCA) 憑證鏈，切換相容模式重試: {url}")
        return req(url, verify=False, **kwargs)

if __name__ == "__main__":
    init_directories()
    print("API Key Status:", "Configured" if GEMINI_API_KEY else "Not configured")
    print("Data Directory:", DATA_DIR)
