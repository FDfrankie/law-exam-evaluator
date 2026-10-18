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
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

# 現代化 Gemini 3.x 模型後備階梯（依序降級，全面防禦單一模型額度耗盡或服務變更）
GEMINI_FALLBACK_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-pro-latest",
    "gemini-3.1-pro-preview"
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
    if custom_dir:
        return Path(custom_dir)
    
    # Priority 1: Check if Google Drive directory exists on Windows
    for g_path in [Path("G:/我的雲端硬碟/LawExamData"), Path("G:/My Drive/LawExamData")]:
        if g_path.exists():
            return g_path
            
    # Priority 2: Repository local data directory (for Streamlit Cloud / Linux / cloned repo)
    local_data = Path(__file__).resolve().parent / "data"
    if local_data.exists():
        return local_data
        
    # Priority 3: Fallback to G: drive parent if user is setting up Google Drive
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
