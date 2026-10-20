import os
import sys
from pathlib import Path

# 將專案根目錄與 core 目錄加入模組搜尋路徑
ROOT_DIR = Path(__file__).resolve().parent
CORE_DIR = ROOT_DIR / "core"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

try:
    from dotenv import load_dotenv
    env_path = ROOT_DIR / ".env"
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
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

# 現代化 Gemini 核心模型後備階梯（依序降級，保證模型 ID 有效，避免 404 重試延遲）
GEMINI_FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.8-pro",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-2.0-flash-lite",
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

# ==============================================================================
# 系統導航模式常數（相容舊版模式與跨視圖跳轉）
# ==============================================================================
MODE_HOME = "🏠 首頁與系統導覽 (功能總覽・隱私權政策・法律聲明)"
MODE_EVAL = "📝 試卷評分與手寫辨識 (手寫/PDF/Word)"
MODE_GEN = "🎯 司律模擬出題 (一試/二試 & 手寫筆記客製命題)"
MODE_BANK = "📚 歷年真題庫檢索與模擬演練 (法研所 / 轉學考 / 司法官律師 / 司法特考)"
MODE_ANS = "📖 高分權威擬答生成"
MODE_SEARCH = "🔍 統一法學檢索樞紐與 AI 判決研析 (布林檢索・多庫矩陣・爭點大典)"
MODE_QA = "💬 專屬法學全能問答樞紐 (萬能檢索・條文定位・爭點論辯・金額精算)"
MODE_SUMMARIZER = "📑 一鍵 AI 裁判與長篇函釋要旨自動精鍊 (AI 判解精鍊旗艦)"
MODE_SIX_CODES = "⚖️ 智慧六法與條文判解綜合標註 (法條・沿革・爭點・筆記)"
MODE_SFT = "📥 手寫筆記蒸餾與 SFT 模型微調大庫"

def get_base_data_dir() -> Path:
    custom_dir = os.getenv("GOOGLE_DRIVE_DATA_DIR")
    if custom_dir:
        p = Path(custom_dir)
        if p.exists():
            return p
    
    # Priority 1: Check if Google Drive directory exists on Windows
    for g_path in [Path("G:/我的雲端硬碟/LawExamData"), Path("G:/My Drive/LawExamData")]:
        if g_path.exists():
            return g_path
            
    # Priority 2: Check active workspace Google Drive CloudStorage parent on macOS dynamically
    try:
        home_cloud = Path.home() / "Library" / "CloudStorage"
        if home_cloud.exists():
            for p in home_cloud.glob("GoogleDrive-*/**/LawExamData"):
                if p.is_dir():
                    return p
    except Exception:
        pass

    # Priority 3: Repository local data directory (for Streamlit Cloud / Linux / cloned repo)
    local_data = ROOT_DIR / "data"
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
NATIONAL_LAWS_DIR = DATA_DIR / "national_laws"
TRAINING_DATA_DIR = DATA_DIR / "training_data"
SAMSUNG_NOTES_DIR = DATA_DIR / "SamsungNotes"
MODEL_WEIGHTS_DIR = DATA_DIR / "model_weights"

def normalize_to_posix_path(raw_path: str) -> str:
    """將 Windows 絕對路徑或舊版硬編碼路徑正規化為相容各 OS 之路徑字串"""
    if not raw_path:
        return ""
    p_str = str(raw_path).replace("\\", "/")
    for prefix in ["G:/我的雲端硬碟/LawExamData/", "G:/My Drive/LawExamData/", "G:/LawExamData/"]:
        if prefix in p_str:
            p_str = p_str.split(prefix, 1)[-1]
            return str(DATA_DIR / p_str)
    return p_str

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
    僅在顯式配置環境變數 LEGAL_ALLOW_INSECURE_SSL=1 時才允許降級連線。
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
            f"TLS/SSL 憑證驗證失敗：無法安全連線至 {url} (原因: {e})。"
        ) from e

if __name__ == "__main__":
    init_directories()
    print("API Key Status:", "Configured" if GEMINI_API_KEY else "Not configured")
    print("Data Directory:", DATA_DIR)
