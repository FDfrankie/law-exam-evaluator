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

# Output directory structure
RAW_DATA_DIR = DATA_DIR / "raw_exams"
STANDARDS_DIR = DATA_DIR / "scoring_standards"
STUDENT_PAPERS_DIR = DATA_DIR / "student_submissions"
REPORTS_DIR = DATA_DIR / "evaluation_reports"

def init_directories():
    """Ensure data directories exist"""
    for folder in [RAW_DATA_DIR, STANDARDS_DIR, STUDENT_PAPERS_DIR, REPORTS_DIR]:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[DIR ERROR] Failed creating {folder}: {e}")

if __name__ == "__main__":
    init_directories()
    print("API Key Status:", "Configured" if GEMINI_API_KEY else "Not configured")
    print("Data Directory:", DATA_DIR)
