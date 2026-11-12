import sys
import os
import hmac
import hashlib
from pathlib import Path
from typing import List, Optional, Tuple

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


def _get_streamlit_secret(name: str) -> str:
    """Safely read a secret string from st.secrets outside or inside Streamlit."""
    try:
        import streamlit as st
        secrets = getattr(st, "secrets", None)
        if secrets is not None:
            val = secrets.get(name) if hasattr(secrets, "get") else (
                secrets[name] if name in secrets else None
            )
            if val is not None and str(val).strip():
                return str(val).strip()
    except Exception:
        pass
    return ""


def _resolve_gemini_api_key(explicit_key: Optional[str] = None) -> Tuple[str, str]:
    """Resolve Gemini API key and its source ('byok'|'secrets'|'env'|'none')."""
    if explicit_key is not None and str(explicit_key).strip():
        return str(explicit_key).strip(), "byok"

    try:
        import streamlit as st
        ss = getattr(st, "session_state", None)
        if ss is not None:
            val = ss.get("user_gemini_api_key") if hasattr(ss, "get") else (
                ss["user_gemini_api_key"] if "user_gemini_api_key" in ss else None
            )
            if val is not None and str(val).strip():
                return str(val).strip(), "byok"
    except Exception:
        pass

    secret_key = _get_streamlit_secret("GEMINI_API_KEY")
    if secret_key:
        return secret_key, "secrets"

    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key, "env"

    return "", "none"


def get_gemini_api_key(explicit_key: Optional[str] = None) -> str:
    """Get Gemini API Key from explicit key, session BYOK, Streamlit Secrets, or env."""
    key, _ = _resolve_gemini_api_key(explicit_key=explicit_key)
    return key


def get_gemini_api_key_source(explicit_key: Optional[str] = None) -> str:
    """Return the active Gemini API key source: 'byok', 'secrets', 'env', or 'none'."""
    _, source = _resolve_gemini_api_key(explicit_key=explicit_key)
    return source


GEMINI_API_KEY = get_gemini_api_key()
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip() or "gemini-flash-latest"

# 現行有效之 Google Gemini 官方 GA 生產環境模型清單（依序故障轉移）
GEMINI_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-pro",
]


def get_gemini_models_to_try(primary_model: Optional[str] = None) -> List[str]:
    """Return prioritized list of Gemini model candidates for resilient fallback."""
    models: List[str] = []
    for candidate in (primary_model, DEFAULT_GEMINI_MODEL, *GEMINI_FALLBACK_MODELS):
        if candidate:
            clean = str(candidate).strip()
            if clean and clean not in models:
                models.append(clean)
    return models


# SHA-256 hex digest of the legacy owner credential (plaintext never stored in source)
_LEGACY_DEVELOPER_PASSWORD_SHA256 = (
    "0182d0d4463d3d5781f5e9addacbebe24a7875ad14f118559bcdc183e11f8f49"
)


def verify_developer_password(pwd: str) -> bool:
    """Verify developer password against secrets/env DEVELOPER_PASSWORD or legacy SHA-256 digest."""
    if not pwd or not isinstance(pwd, str):
        return False
    candidate = pwd.strip()
    if not candidate:
        return False

    configured = _get_streamlit_secret("DEVELOPER_PASSWORD") or os.getenv("DEVELOPER_PASSWORD", "").strip()
    if configured:
        return hmac.compare_digest(candidate.encode("utf-8"), configured.encode("utf-8"))

    candidate_digest = hashlib.sha256(candidate.lower().encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate_digest, _LEGACY_DEVELOPER_PASSWORD_SHA256)

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
    if name == "judicial_1m_db":
        custom_1m = os.getenv("JUDICIAL_1M_DIR")
        if custom_1m and Path(custom_1m).exists():
            return Path(custom_1m)
        # 本機高速 SSD (D:\ 或 C:\) 優先，杜絕 Google Drive 雲端同步衝突與鎖定異常
        for local_cand in [Path(r"D:\LawExamData\judicial_1m_db"), Path(r"C:\LawExamData\judicial_1m_db")]:
            if local_cand.exists() and (local_cand / "judicial_1m_index.db").exists():
                return local_cand

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

_DIRS_INITIALIZED: bool = False


def init_directories(force: bool = False):
    """Ensure data directories exist (guarded against redundant Streamlit reruns)."""
    global _DIRS_INITIALIZED
    if _DIRS_INITIALIZED and not force:
        return
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
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                except (FileExistsError, OSError):
                    pass
        except Exception as e:
            print(f"[DIR ERROR] Failed creating {folder}: {e}")
    _DIRS_INITIALIZED = True

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

# 系統核心導航模式常數
MODE_HOME = "🏠 系統首頁"
MODE_TEXTBOOK = "📖 體系教科書"
MODE_EVAL = "📝 試卷批改"
MODE_GEN = "🎯 模擬命題"
MODE_BANK = "📚 歷年真題"
MODE_ANS = "✍️ 擬答生成"
MODE_SEARCH = "🔍 法學檢索"
MODE_QA = "💬 法律問答"
MODE_SUMMARIZER = "📑 裁判精鍊"
MODE_SIX_CODES = "⚖️ 智慧六法"
MODE_SFT = "📥 法學筆記"
MODE_LEGAL_NOTICE = "📮 存證信函"
MODE_INGEST = "📦 裁判入庫"
MODE_DEV_MANAGER = "🛠️ 檔案總管"

if __name__ == "__main__":
    init_directories()
    print("API Key Status:", "Configured" if GEMINI_API_KEY else "Not configured")
    print("Data Directory:", DATA_DIR)
