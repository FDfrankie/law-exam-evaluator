"""
文件解析模組：支援 PDF、Word (.docx) 以及圖片解析
"""
from pathlib import Path
from typing import List, Union, Tuple
import io
from PIL import Image
import pdfplumber
import docx

def parse_document(file_bytes: bytes, filename: str) -> Tuple[str, List[Image.Image]]:
    """
    解析上傳的檔案。
    :return: (純文字內容, 圖片清單)
    - 若為 docx：解析出文字內容
    - 若為 pdf：嘗試擷取文字，並同時將頁面轉為高解析圖片（供手寫/掃描卷辨識）
    - 若為圖片 (png/jpg/jpeg/webp)：放入圖片清單
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
                if text:
                    pdf_text_parts.append(text)
                
                # 轉換頁面為影像（供手寫 PDF 辨識）
                try:
                    page_img = page.to_image(resolution=200).original
                    images.append(page_img)
                except Exception as e:
                    print(f"PDF 轉影像警示: {e}")
            extracted_text = "\n\n".join(pdf_text_parts)

    return extracted_text, images
