# Step 1 — CV Ingestion Layer

**Project:** CV Matcher — an ATS pipeline for parsing, scoring, and matching candidate CVs
**Author:** Yasser Boudriga — ENSIASD (1st year engineering)
**Context:** AI internship project, Linkrs Morocco
**Phase:** 1 of 6 (Ingestion → Extraction → Scraping → Matching → Backend/DB → UI)

---

## 1. Objective

The ingestion layer is the entry point of the entire system. Its single responsibility
is to take **any** CV file a candidate might submit and return **clean, machine-readable
text**, regardless of the file's format or quality. Everything downstream (extraction,
scoring, matching) depends on the reliability of this layer — *garbage in, garbage out*.

## 2. Problem statement

A CV is not a simple text file. In a real recruitment scenario, candidates submit CVs in
many forms, each with its own technical challenge:

| Input type | Technical challenge |
|---|---|
| **Native PDF** | A PDF stores *positioned glyphs*, not linear text. Multi-column layouts get read out of order. |
| **Scanned PDF** | The page is just an *image* with no text layer at all — nothing to extract directly. |
| **DOCX** | A zipped XML format. Designed templates hide content in **tables** and **text boxes** that naive parsers miss. |
| **Photo (JPG/PNG)** | Candidates frequently photograph a paper CV with their phone — a pure image. |

Additionally, in the Moroccan context CVs are typically **multilingual** (French, Arabic,
English), which affects both text extraction and later processing.

## 3. Design and architecture

The layer follows a **router pattern**: a single public function, `extract_text(path)`,
inspects the file extension, validates the file, and dispatches it to the appropriate
specialized reader. This keeps each format's logic isolated and testable.

```
                       ┌──────────────────────┐
   CV file  ─────────► │   extract_text()     │   (validation + routing)
   (any type)          └──────────┬───────────┘
                                  │
        ┌──────────────┬──────────┼───────────┬────────────────┐
        ▼              ▼          ▼            ▼                ▼
   pdf_reader     docx_reader   image_reader  (OCR fallback shared by PDF + image)
   (text layer)   (paragraphs   (Tesseract)
        │           + tables
        │           + textboxes)
        ▼
   if < 50 chars → OCR (scanned PDF)
```

**Modules created:**
- `ingest/extractor.py` — the router: validation, dispatch, logging, error handling.
- `ingest/pdf_reader.py` — PDF text extraction, with automatic OCR fallback for scans.
- `ingest/docx_reader.py` — DOCX extraction covering paragraphs, tables, and text boxes.
- `ingest/image_reader.py` — OCR for photographed CVs (JPG/PNG).

## 4. Tools and libraries

| Tool | Role | Why it was chosen |
|---|---|---|
| **PyMuPDF** (`pymupdf`) | PDF text + page rendering | Fast, accurate, handles messy real-world PDFs; can render pages to images for OCR without extra dependencies. |
| **python-docx** | DOCX parsing | Standard library for Word documents; gives structured access to paragraphs and tables. |
| **Tesseract OCR** + **pytesseract** | Optical Character Recognition | Open-source, industry-standard OCR engine; supports French, Arabic, and English simultaneously. |
| **Pillow** | Image handling | Required by the OCR toolchain. |

Tesseract is installed with the **French (`fra`)**, **Arabic (`ara`)**, and **English
(`eng`)** language packs to match Moroccan CVs.

## 5. Implementation highlights

### 5.1 PDF — with OCR fallback
The PDF reader first attempts to read the native text layer. If the result is nearly empty
(`< 50` characters), the document is assumed to be a **scanned image**, and each page is
rendered at 300 DPI and passed to Tesseract OCR.

### 5.2 DOCX — reaching hidden content
Designed CV templates store text inside **tables** and **text boxes**, which a simple
paragraph loop cannot see. The reader therefore:
1. reads normal paragraphs,
2. reads all table cells,
3. as a last resort, extracts every text node from the raw XML (to reach text boxes).

A subtle real-world issue was discovered: Word stores text-box content **twice** (a modern
copy and a legacy "fallback" copy for old Word versions), causing every line to appear
duplicated. The reader detects and skips the legacy copy, eliminating the duplication.

### 5.3 Images — direct OCR
Photographed CVs are passed directly to Tesseract by **file path** (rather than as an
in-memory image object). This design choice also resolved a dependency incompatibility
(see §7).

## 6. Production-grade robustness

This layer was built to production standards, not as a throwaway script:

- **Input validation** — rejects missing files, empty files, files over 10 MB, and
  unsupported extensions, each with a clear message.
- **Custom exception** — a single `ExtractionError` type gives callers predictable,
  catchable failures instead of low-level library crashes.
- **Logging** — uses Python's `logging` module (not `print`) so a running system can be
  traced.
- **CLI input** — the file path is passed as a command-line argument (`argparse`); nothing
  is hardcoded.

### Data protection note
A CV is **personal data** (name, phone, email, address of a real person). The project
therefore treats CVs as sensitive from the start: raw CV files are excluded from version
control (`.gitignore`) and are never committed to the repository. This aligns with data
protection obligations (GDPR for the EU/Dutch market, Morocco's *Loi 09-08*), which is a
core requirement for any real recruitment product.

## 7. A real debugging case: Pillow 12 incompatibility

During OCR development, passing an in-memory image object to pytesseract raised
`TypeError: Unsupported image format/type`. By **isolating the failing layer** (calling
Tesseract directly on the file path, which worked), the cause was identified as a version
incompatibility between the very recent **Pillow 12.3.0** and the installed pytesseract's
image-handling code. The fix — passing **file paths** instead of image objects — bypasses
the incompatible code path entirely. This is documented as an example of methodical
debugging rather than trial-and-error.

## 8. Testing and results

The layer was tested against three real CVs representing the main scenarios:

| Test file | Type | Result |
|---|---|---|
| Data-scientist CV | Native PDF | ✅ Full text extracted (2971 chars) |
| Accountant CV | DOCX (text boxes) | ✅ Text extracted after text-box + de-duplication handling (1530 chars) |
| Same CV, photographed | JPG image / scanned PDF | ✅ OCR extracted core content (993 / 808 chars) |

**Error handling** was verified by feeding a missing file and an unsupported `.txt` file —
both were rejected cleanly with an `ExtractionError` instead of crashing.

### Match verification (scanned CV)
The OCR output was compared field-by-field against the source photo:

- **Captured correctly:** name, job title, phone, full education history (institutions +
  dates), all technical skills, and languages.
- **Degraded:** the email digit `1` misread as `l`/`i`; multi-column reading order
  scrambled; the *Projets* section largely lost.

**Conclusion of the test:** the core, decision-relevant information is reliably captured
across all formats. The degradation observed on scanned inputs is an inherent property of
OCR, not a defect of the implementation.

## 9. Limitations

- OCR text is noisier than native text (character confusions, lost sections, scrambled
  order) and depends on photo quality and lighting.
- Multi-column layouts are read in an imperfect order (acceptable, because the next stage
  reads meaning rather than position).
- Arabic (right-to-left) text introduces direction-marker artifacts that will be cleaned in
  the extraction stage.

## 10. Conclusion and transition

The ingestion layer reliably converts four input types — native PDF, scanned PDF, DOCX
(including text boxes), and photographed images — into text, with production-grade
validation, error handling, and logging. The observed OCR noise directly motivates the next
phase: an **AI-based extraction layer** that reads *meaning* rather than exact patterns, and
is therefore robust to the imperfect text this layer sometimes produces.

**Next step → Step 2: Information Extraction (regex + LLM hybrid).**
