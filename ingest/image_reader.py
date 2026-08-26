import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
OCR_LANGS = "fra+ara+eng"


def extract_text_from_image(path: str) -> str:
    return pytesseract.image_to_string(path, lang=OCR_LANGS)