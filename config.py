import os
from pathlib import Path
from dotenv import load_dotenv

# 載入本機 .env
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

def get_gemini_api_key() -> str:
    """取得 Gemini API Key，支援 Streamlit Cloud Secrets 與本機環境變數"""
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

# 資料目錄判斷：本機 G 槽存在則存於 Google Drive，雲端環境 (Streamlit Cloud Linux) 則自動存於專案內 data 目錄
def get_base_data_dir() -> Path:
    custom_dir = os.getenv("GOOGLE_DRIVE_DATA_DIR")
    if custom_dir:
        return Path(custom_dir)
    
    g_drive_dir = Path("G:/我的雲端硬碟/LawExamData")
    if Path("G:/").exists():
        return g_drive_dir
    
    # Streamlit Cloud / Linux 跨平台預設儲存位置
    return Path(__file__).resolve().parent / "data"

DATA_DIR = get_base_data_dir()
GOOGLE_DRIVE_DATA_DIR = str(DATA_DIR)

# 確保輸出目錄結構存在
RAW_DATA_DIR = DATA_DIR / "raw_exams"                  # 考題原始檔 (PDF/TXT)
STANDARDS_DIR = DATA_DIR / "scoring_standards"         # 評分要點/參考擬答
STUDENT_PAPERS_DIR = DATA_DIR / "student_submissions" # 考生手寫上傳試卷
REPORTS_DIR = DATA_DIR / "evaluation_reports"          # 評分結果輸出報告

def init_directories():
    """初始化存放目錄"""
    for folder in [RAW_DATA_DIR, STANDARDS_DIR, STUDENT_PAPERS_DIR, REPORTS_DIR]:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[目錄建立失敗] {folder}: {e}")

if __name__ == "__main__":
    init_directories()
    print("API Key 狀態:", "已設定" if GEMINI_API_KEY else "尚未設定")
    print("資料存放位置:", DATA_DIR)
