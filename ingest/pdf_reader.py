import os
import tempfile
import pymupdf
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
OCR_LANGS = "fra+ara+eng"


def extract_text_from_pdf(path: str) -> str:
    doc = pymupdf.open(path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()

    # Almost no text -> scanned/image PDF -> OCR
    if len(text.strip()) < 50:
        text = _ocr_pdf(path)
    return text


def _ocr_pdf(path: str) -> str:
    doc = pymupdf.open(path)
    text = ""
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=300)
        tmp_path = os.path.join(tempfile.gettempdir(), f"ocr_page_{i}.png")
        pix.save(tmp_path)                 # save page image to a temp file
        try:
            text += pytesseract.image_to_string(tmp_path, lang=OCR_LANGS)
        finally:
            os.remove(tmp_path)            # clean up
    doc.close()
    return text