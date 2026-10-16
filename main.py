"""
司律手寫題目自動評分系統 - CLI 與 主控制入口
"""
import sys
import argparse
from pathlib import Path
from PIL import Image
from config import init_directories, GOOGLE_DRIVE_DATA_DIR, RAW_DATA_DIR
from evaluator import LawExamEvaluator
from crawler import MoexCrawler

def print_banner():
    print("=" * 65)
    print("      司律二試手寫申論題 - AI 自動評分與診斷系統")
    print(f"      雲端儲存路徑: {GOOGLE_DRIVE_DATA_DIR}")
    print("=" * 65)

def run_evaluation(images, question, rubric=None):
    print("\n[步驟 1/2] 正在讀取試卷影像與載入 Gemini 2.0 Flash 評分引擎...")
    evaluator = LawExamEvaluator()
    
    # 將檔案路徑轉換為 PIL Image 物件
    pil_images = []
    for img_path in images:
        try:
            pil_images.append(Image.open(img_path))
        except Exception as e:
            print(f"[警告] 無法載入圖片 {img_path}: {e}")
    
    if not pil_images:
        print("[錯誤] 沒有成功載入任何圖片，請確認檔案路徑是否正確。")
        return None
    
    print("\n[步驟 2/2] 正在進行手寫辨識、爭點比對與四維度評分 (請稍候)...")
    res = evaluator.evaluate_submission(
        images=pil_images,
        question_text=question,
        standard_rubric=rubric
    )
    
    print("\n" + "=" * 65)
    print(f"【評閱總分】：{res.get('total_score')} 分 / 100 分  【等第】：{res.get('grade_level')}")
    print("=" * 65)
    print(f"  * 爭點意識與開標: {res.get('issue_spotting_score')}/25")
    print(f"  * 三段論法與架構: {res.get('legal_reasoning_score')}/25")
    print(f"  * 實務與學說深度: {res.get('precedent_scholarship_score')}/25")
    print(f"  * 具體事實之涵攝: {res.get('subsumption_score')}/25")
    print("-" * 65)
    print("【手寫謄錄內容 (OCR 辨識結果)】:")
    print(res.get("transcription", "").strip())
    print("-" * 65)
    print("【命中核心爭點】:")
    for item in res.get("identified_issues", []):
        print(f"  + {item}")
    print("【漏答核心爭點】:")
    for item in res.get("missed_issues", []):
        print(f"  - {item}")
    print("【試卷亮點】:")
    for item in res.get("strengths", []):
        print(f"  ✔ {item}")
    print("【缺失與待改進處】:")
    for item in res.get("weaknesses", []):
        print(f"  ✘ {item}")
    print("-" * 65)
    print("【閱卷委員優化建議】:")
    print(res.get("suggested_revision", "").strip())
    print("=" * 65)
    return res

def main():
    init_directories()
    print_banner()

    parser = argparse.ArgumentParser(description="司律手寫題目自動評分器")
    parser.add_argument("--image", "-i", nargs="+", help="手寫試卷照片路徑 (可多張)")
    parser.add_argument("--question", "-q", help="題目文字或題目文字檔路徑")
    parser.add_argument("--rubric", "-r", help="參考擬答/評分標準文字或檔案路徑 (選填)")
    parser.add_argument("--demo", action="store_true", help="執行示範測試")
    
    args = parser.parse_args()

    if args.demo:
        print("[執行示範模式] 建立 112年 司律民法示範題目與測試評分...")
        sample_q = (
            "甲向乙借款新臺幣（下同）1000萬元，並將其所有之A屋設定普通抵押權予乙以供擔保。"
            "嗣後甲未依約清償借款，乙乃依法聲請法院拍賣A屋。於強制執行程序中，"
            "丙主張其就A屋在抵押權設定前即已有不定期限之租賃契約存在，依民法第425條（買賣不破租賃），"
            "其得繼續占有使用A屋。試問：執行法院得否除去丙之租賃權後拍賣A屋？"
        )
        sample_points = [
            "民法第425條買賣不破租賃於抵押權設定前之適用要件",
            "民法第866條抵押人設定抵押權後所為之用益物權或租賃對抵押權之影響",
            "抵押權設定後成立之租賃，若有妨害抵押權實行者，執行法院得除去後拍賣（辦理強制執行事件應行注意事項第42點、司法院釋字第304號解釋意旨）",
            "本題租賃契約若成立在抵押權設定前，能否類推適用或逕予除去之爭點分析"
        ]
        crawler = MoexCrawler()
        crawler.save_exam_record(112, "民法與民事訴訟法(一)", sample_q, sample_points)
        print("示範試題已成功保存至 Google Drive！")
        return

    if not args.image or not args.question:
        print("\n[提示] 請提供手寫圖片與題目，例如：")
        print("  python main.py -i C:/path/to/page1.jpg C:/path/to/page2.jpg -q '題目內容...'")
        print("若要測試儲存與環境，可執行示範模式：")
        print("  python main.py --demo\n")
        return

    # 讀取題目內容（支援字串或檔案路徑）
    q_path = Path(args.question)
    q_content = q_path.read_text(encoding="utf-8") if q_path.exists() else args.question

    r_content = None
    if args.rubric:
        r_path = Path(args.rubric)
        r_content = r_path.read_text(encoding="utf-8") if r_path.exists() else args.rubric

    run_evaluation(images=args.image, question=q_content, rubric=r_content)

if __name__ == "__main__":
    main()
