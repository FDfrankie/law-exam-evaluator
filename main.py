"""
Taiwan Law Exam AI Grader - CLI Entry Point
"""
import sys
import argparse
from pathlib import Path
from PIL import Image

# Ensure stdout handles UTF-8 safely on Windows CMD
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from config import init_directories, GOOGLE_DRIVE_DATA_DIR, RAW_DATA_DIR
from evaluator import LawExamEvaluator
from exam_bank_crawler import MoexCrawler

def print_banner():
    print("=" * 65)
    print("      Taiwan Law Exam AI Grader & Reasoning Diagnostics")
    print(f"      Data Storage: {GOOGLE_DRIVE_DATA_DIR}")
    print("=" * 65)

def run_evaluation(images, question, rubric=None):
    print("\n[Step 1/2] Loading images and Gemini 2.0 Flash engine...")
    evaluator = LawExamEvaluator()
    
    pil_images = []
    for img_path in images:
        try:
            pil_images.append(Image.open(img_path))
        except Exception as e:
            print(f"[WARNING] Failed to load image {img_path}: {e}")
    
    if not pil_images:
        print("[ERROR] No valid images loaded. Please check the image paths.")
        return None
    
    print("\n[Step 2/2] Evaluating submission (OCR, issues, IRAC reasoning)...")
    res = evaluator.evaluate_submission(
        images=pil_images,
        question_text=question,
        standard_rubric=rubric
    )
    
    print("\n" + "=" * 65)
    print(f" TOTAL SCORE: {res.get('total_score')} / 100   GRADE: {res.get('grade_level')}")
    print("=" * 65)
    print(f"  * Issue Spotting:          {res.get('issue_spotting_score')}/25")
    print(f"  * Legal Reasoning (IRAC):  {res.get('legal_reasoning_score')}/25")
    print(f"  * Precedent & Scholarship: {res.get('precedent_scholarship_score')}/25")
    print(f"  * Fact Subsumption:        {res.get('subsumption_score')}/25")
    print("-" * 65)
    print("[OCR Transcription]:")
    print(res.get("transcription", "").strip())
    print("-" * 65)
    print("[Identified Issues]:")
    for item in res.get("identified_issues", []):
        print(f"  + {item}")
    print("[Missed Issues]:")
    for item in res.get("missed_issues", []):
        print(f"  - {item}")
    print("[Strengths]:")
    for item in res.get("strengths", []):
        print(f"  + {item}")
    print("[Weaknesses]:")
    for item in res.get("weaknesses", []):
        print(f"  - {item}")
    print("-" * 65)
    print("[Revision Advice]:")
    print(res.get("suggested_revision", "").strip())
    print("=" * 65)
    return res

def main():
    init_directories()
    print_banner()

    parser = argparse.ArgumentParser(description="Taiwan Law Exam AI Grader")
    parser.add_argument("--image", "-i", nargs="+", help="Paths to handwritten exam images")
    parser.add_argument("--question", "-q", help="Question text or path to question file")
    parser.add_argument("--rubric", "-r", help="Standard rubric text or file path (optional)")
    parser.add_argument("--demo", action="store_true", help="Run demonstration test")
    
    args = parser.parse_args()

    if args.demo:
        print("[DEMO MODE] Creating sample civil law exam problem...")
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
        crawler.save_exam_record(112, "Civil Law", sample_q, sample_points)
        print("[DEMO SUCCESS] Sample record saved to storage.")
        return

    if not args.image or not args.question:
        print("\n[Usage Guide] Please provide image paths and question text, e.g.:")
        print("  python main.py -i page1.jpg page2.jpg -q 'Question content...'")
        print("To run environment test, use demo mode:")
        print("  python main.py --demo\n")
        return

    q_path = Path(args.question)
    q_content = q_path.read_text(encoding="utf-8") if q_path.exists() else args.question

    r_content = None
    if args.rubric:
        r_path = Path(args.rubric)
        r_content = r_path.read_text(encoding="utf-8") if r_path.exists() else args.rubric

    run_evaluation(images=args.image, question=q_content, rubric=r_content)

if __name__ == "__main__":
    main()
