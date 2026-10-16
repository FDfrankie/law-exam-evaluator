"""
司律 AI 評分系統 - 全球外網一鍵穿透啟動器
自動啟動 Streamlit 本地伺服器與 Cloudflare Tunnel，並同步更新手機捷徑頁面。
"""
import os
import re
import sys
import time
import subprocess
from pathlib import Path

# 終端機編碼設定
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CURRENT_DIR

# 優先尋找 local tools，再尋找雲端硬碟 tools
TOOLS_EXE = Path("C:/Users/mis/tools/cloudflared.exe")
if not TOOLS_EXE.exists():
    TOOLS_EXE = PROJECT_DIR.parent / "tools" / "cloudflared.exe"

LOG_FILE = Path("C:/Users/mis/tools/cf_tunnel.log")
SHORTCUT_HTML_PROJECT = PROJECT_DIR.parent / "手機點我開啟評分系統.html"
SHORTCUT_HTML_ROOT = Path("G:/我的雲端硬碟/手機點我開啟評分系統.html")

def update_shortcut_html(public_url: str):
    """更新手機捷徑 HTML 檔案中的網址，讓手機點開直接連到最新的外網網址"""
    html_content = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>司律考試 AI 評分系統 - 全球外網捷徑</title>
    <meta http-equiv="refresh" content="2;url={public_url}">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            color: #f8fafc;
        }}
        .card {{
            background: rgba(255, 255, 255, 0.08);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 24px;
            padding: 32px 24px;
            max-width: 440px;
            width: 100%;
            text-align: center;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
        }}
        .icon {{ font-size: 56px; margin-bottom: 12px; }}
        h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 8px; color: #ffffff; }}
        p.subtitle {{ font-size: 14px; color: #94a3b8; margin-bottom: 24px; }}
        .btn-launch {{
            display: block;
            width: 100%;
            padding: 16px;
            background: linear-gradient(90deg, #2563eb, #3b82f6);
            color: #ffffff;
            font-size: 18px;
            font-weight: 600;
            text-decoration: none;
            border-radius: 14px;
            box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4);
            margin-bottom: 24px;
        }}
        .qr-section {{
            background: #ffffff;
            padding: 16px;
            border-radius: 16px;
            display: inline-block;
            margin-bottom: 20px;
        }}
        .qr-section img {{ display: block; width: 180px; height: 180px; }}
        .url-box {{
            background: rgba(0, 0, 0, 0.3);
            padding: 10px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 13px;
            word-break: break-all;
            margin-bottom: 16px;
            color: #38bdf8;
        }}
        .tip-box {{
            background: rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            padding: 14px;
            text-align: left;
            font-size: 13px;
            line-height: 1.6;
            color: #cbd5e1;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">⚖️</div>
        <h1>司律 AI 評分與命題大師</h1>
        <p class="subtitle">全球安全外網連線就緒，正在自動跳轉...</p>
        <div class="url-box">{public_url}</div>
        <a class="btn-launch" href="{public_url}">
            點擊立即進入評分系統
        </a>
        <div class="qr-section">
            <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={public_url}" alt="QR Code">
        </div>
        <div class="tip-box">
            <p><strong>手機連線說明：</strong></p>
            <p>1. 本網址為全球安全加密穿透，手機不論使用 <strong>4G/5G 或外部 Wi-Fi</strong> 皆可直接開啟。</p>
            <p>2. 可直接用手機相機掃描上方 QR 碼，或點擊藍色按鈕登入。</p>
        </div>
    </div>
</body>
</html>"""
    for p in [SHORTCUT_HTML_PROJECT, SHORTCUT_HTML_ROOT]:
        try:
            p.write_text(html_content, encoding="utf-8")
        except Exception as e:
            print(f"[警告] 更新捷徑檔失敗 {p}: {e}")

def main():
    print("=" * 70)
    print("        司律 AI 評分系統 - 全球外網穿透服務 (Cloudflare Tunnel)")
    print("=" * 70)

    python_exe = sys.executable
    app_script = str(PROJECT_DIR / "app.py")

    print("[1/3] 正在啟動 Streamlit 本地伺服器 (Port 8501)...")
    st_proc = subprocess.Popen(
        [python_exe, "-m", "streamlit", "run", app_script, "--server.port", "8501", "--server.headless", "true"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    time.sleep(2)

    if LOG_FILE.exists():
        try:
            LOG_FILE.unlink()
        except Exception:
            pass

    print("[2/3] 正在建立 Cloudflare 全球穿透連線 (全球免設定路由器)...")
    cf_cmd = [
        str(TOOLS_EXE),
        "tunnel",
        "--logfile", str(LOG_FILE),
        "--url", "http://127.0.0.1:8501"
    ]
    cf_proc = subprocess.Popen(cf_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    tunnel_url = None
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

    for _ in range(40):
        time.sleep(1)
        if LOG_FILE.exists():
            try:
                log_content = LOG_FILE.read_text(encoding="utf-8", errors="ignore")
                match = url_pattern.search(log_content)
                if match:
                    tunnel_url = match.group(0)
                    break
            except Exception:
                pass
        if cf_proc.poll() is not None:
            break

    if not tunnel_url:
        print("[錯誤] 無法取得外網網址，請檢查網路連線。")
        st_proc.terminate()
        return

    print("[3/3] 全球外網通道建立成功！")
    update_shortcut_html(tunnel_url)

    print("\n" + "=" * 70)
    print("  [成功] 您的專屬全球公開網址（任何手機、任何網路皆可使用）：")
    print(f"     >>  {tunnel_url}")
    print("=" * 70)
    print("  * 已自動同步更新手機捷徑頁面：")
    print("    G:\\我的雲端硬碟\\手機點我開啟評分系統.html")
    print("  * 手機打開 Google Drive 點擊該 HTML，或直接瀏覽上方網址即可！")
    print("  * 保持本視窗開啟即可維持連線，按 Ctrl+C 可關閉服務。")
    print("=" * 70 + "\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在關閉服務...")
    finally:
        cf_proc.terminate()
        st_proc.terminate()
        print("服務已停止。")

if __name__ == "__main__":
    main()
