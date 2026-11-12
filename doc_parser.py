"""
文件解析模組：支援 PDF、Word (.docx)、文字檔以及手寫/掃描影像辨識 (Gemini Multimodal OCR)
精確支援打字與手寫體法學筆記、實務講義及試卷影像辨識
"""
from pathlib import Path
from typing import List, Union, Tuple, Optional
import io
from PIL import Image
import pdfplumber
import docx

import logging

from llm_client import LlmCallError, MissingApiKeyError, generate_content

logger = logging.getLogger(__name__)

def ocr_handwritten_images(images: List[Image.Image], prompt_hint: Optional[str] = None) -> str:
    """
    使用 Gemini 多模態神經網路，精確辨識法律手寫筆記、手寫試卷或掃描圖檔之文字、法條與爭點論述。
    :param images: PIL Image 清單
    :param prompt_hint: 額外的提示語（例如指定考科或重點方向）
    :return: 辨識謄錄之完整繁體中文文字
    """
    if not images:
        return ""
        

    prompt = """
你是一位精通台灣法學與繁體中文手寫辨識的專家與權威法學助理。
請仔細辨識這份手寫/掃描筆記/試卷圖片的文字與法學架構：
1. 【逐字逐段精確謄錄】：精準轉錄手寫字跡，包括筆記中的法條（含條項款）、構成要件、權利義務、爭點、實務裁判字號（如最高法院XX台上字第XX號、最高行政法院判決、憲法法庭判決、司法院釋字、大法庭裁定）、學者見解（如王澤鑑、林山田、黃榮堅、陳敏、姜世明等通說有力說）。
2. 【法學結構重現】：保留筆記的大標題、小標題、開標、爭點提示、肯否兩說、折衷說、結論等論理架構。
3. 【模糊修正】：若遇潦草或沾染之手寫字跡，請依據台灣法律專有名詞與上下文法理邏輯合理推敲辨正，並於括號附註。
4. 【重點萃取】：文末請彙整此筆記之【核心法條】、【關鍵爭點】與【重要實務裁判出處】，以利後續客製化命題與測驗。

請直接輸出完整辨識與結構排版之繁體中文法學筆記內容。
"""
    if prompt_hint:
        prompt += f"\n【考生補充提示】：{prompt_hint}\n"

    # 若頁數過多，分批處理（每批最多 4 頁以確保最高辨識解析度）
    batch_size = 4
    results = []

    for i in range(0, len(images), batch_size):
        end_idx = min(i + batch_size, len(images))
        chunk = images[i:end_idx]
        contents = [prompt] + chunk
        try:
            text = generate_content(contents, temperature=0.2)
            if text and text.strip():
                results.append(text.strip())
            else:
                logger.warning("OCR 第 %d~%d 頁回傳空白內容", i + 1, end_idx)
                results.append(f"[第 {i+1}~{end_idx} 頁辨識異常: 模型回傳空白內容]")
        except MissingApiKeyError:
            logger.warning("未配置 GEMINI_API_KEY，無法執行手寫/影像 OCR 辨識")
            return "[提示] 未配置 GEMINI_API_KEY，無法執行手寫/影像 OCR 辨識。"
        except (LlmCallError, Exception) as e:
            logger.warning("OCR 第 %d~%d 頁辨識異常: %s", i + 1, end_idx, e)
            results.append(f"[第 {i+1}~{end_idx} 頁辨識異常: {e}]")

    return "\n\n---\n\n".join(results)

def parse_document(file_bytes: bytes, filename: str, auto_ocr_handwriting: bool = True) -> Tuple[str, List[Image.Image]]:
    """
    解析上傳的檔案。
    :param file_bytes: 檔案二進位資料
    :param filename: 檔案名稱
    :param auto_ocr_handwriting: 若文字提取為空且有圖片，是否自動調用 Gemini 多模態進行手寫/掃描辨識
    :return: (純文字內容, 圖片清單)
    - 若為 docx：解析出文字內容
    - 若為 pdf：嘗試擷取文字，並同時將頁面轉為高解析圖片（供手寫/掃描卷辨識）
    - 若為圖片 (png/jpg/jpeg/webp/bmp)：放入圖片清單，若開啟 auto_ocr 則直接辨識出文字
    """
    ext = Path(filename).suffix.lower()
    extracted_text = ""
    images = []

    if ext in [".png", ".jpg", ".jpeg", ".webp", ".bmp"]:
        img = Image.open(io.BytesIO(file_bytes))
        images.append(img)
        
    elif ext in [".txt", ".md"]:
        try:
            extracted_text = file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            extracted_text = file_bytes.decode('cp950', errors='ignore')

    elif ext == ".docx":
        doc = docx.Document(io.BytesIO(file_bytes))
        extracted_text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        
    elif ext == ".pdf":
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pdf_text_parts = []
            for page in pdf.pages:
                # 擷取純文字（若原本就是電腦打字的 PDF）
                text = page.extract_text()
                if text and text.strip():
                    pdf_text_parts.append(text.strip())
                
                # 轉換頁面為影像（供手寫/掃描 PDF 辨識）
                try:
                    page_img = page.to_image(resolution=200).original
                    images.append(page_img)
                except Exception as e:
                    print(f"PDF 轉影像警示: {e}")
            extracted_text = "\n\n".join(pdf_text_parts)

    # 智能判定是否需要手寫/掃描視覺 OCR：
    # 條件 1：完全無數位文字或極短 (< 60 字元) 且有影像頁面
    # 條件 2：平均每頁文字量過低 (< 80 字元/頁)，通常為手寫試卷/掃描講義僅含頁首小標
    needs_ocr = False
    if len(images) > 0:
        stripped_len = len(extracted_text.strip())
        if stripped_len < 60:
            needs_ocr = True
        elif len(images) >= 1 and (stripped_len / len(images)) < 80:
            needs_ocr = True

    if auto_ocr_handwriting and needs_ocr:
        try:
            ocr_text = ocr_handwritten_images(images, prompt_hint=f"試卷/筆記檔名：{filename}")
            if ocr_text.strip():
                if len(extracted_text.strip()) > 30:
                    extracted_text = f"【數位檢定文字】：\n{extracted_text}\n\n---\n【視覺手寫OCR解析】：\n{ocr_text}"
                else:
                    extracted_text = ocr_text
        except Exception as e:
            print(f"[OCR 辨識提示] {e}")

    return extracted_text, images
