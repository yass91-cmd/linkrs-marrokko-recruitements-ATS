# syntax=docker/dockerfile:1
FROM python:3.12-slim

# System dependencies:
#  - tesseract-ocr + language packs: OCR for scanned/photographed CVs
#  - the fra/ara/nld packs matter because the corpus is French/Arabic/Dutch
#  - libgl1 + libglib2.0-0: required by the imaging stack
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-fra \
        tesseract-ocr-ara \
        tesseract-ocr-nld \
        libgl1 \
        libglib2.0-0 \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TESSERACT_CMD=/usr/bin/tesseract \
    HF_HOME=/models

WORKDIR /app

# Install CPU-only PyTorch first: the default wheels bundle CUDA and add
# roughly 2 GB to the image for GPU support this server does not have.
RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the embedding model into the image so the first request
# is not delayed by a 470 MB download.
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:8000/ || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
