import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}
MAX_FILE_SIZE_MB = 10


class ExtractionError(Exception):
    """Raised when a CV file cannot be read."""
    pass


def _validate_file(path: str) -> str:
    if not os.path.exists(path):
        raise ExtractionError(f"File not found: {path}")

    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb == 0:
        raise ExtractionError(f"File is empty: {path}")
    if size_mb > MAX_FILE_SIZE_MB:
        raise ExtractionError(f"File too large ({size_mb:.1f} MB, max {MAX_FILE_SIZE_MB} MB)")

    extension = os.path.splitext(path)[1].lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ExtractionError(f"Unsupported file type: {extension}")

    return extension


def extract_text(path: str) -> str:
    extension = _validate_file(path)
    logger.info("Extracting text from %s", path)

    try:
        if extension == ".pdf":
            from ingest.pdf_reader import extract_text_from_pdf
            text = extract_text_from_pdf(path)
        else:  # .docx
            from ingest.docx_reader import extract_text_from_docx
            text = extract_text_from_docx(path)
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(f"Failed to read {path}: {e}") from e

    if not text.strip():
        raise ExtractionError(f"No text found in {path} (is it a scanned image?)")

    logger.info("Extracted %d characters", len(text))
    return text


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract text from a CV file (PDF or DOCX).")
    parser.add_argument("path", help="Path to the CV file")
    args = parser.parse_args()

    result = extract_text(args.path)
    print(result)