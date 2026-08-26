import io
import pymupdf
import pytesseract
from PIL import Image

# Windows: point pytesseract at the installed Tesseract engine.
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# OCR languages: French + Arabic + English
OCR_LANGS = "fra+ara+eng"


def extract_text_from_pdf(path: str) -> str:
    # First try the normal text layer.
    doc = pymupdf.open(path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()

    # Almost no text -> it's a scanned/image PDF -> fall back to OCR.
    if len(text.strip()) < 50:
        text = _ocr_pdf(path)

    return text


def _ocr_pdf(path: str) -> str:
    doc = pymupdf.open(path)
    text = ""
    for page in doc:
        pix = page.get_pixmap(dpi=300)              # render the page to an image
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        text += pytesseract.image_to_string(img, lang=OCR_LANGS)
    doc.close()
    return text