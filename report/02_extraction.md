# Step 2 — Information Extraction (Hybrid: Regex + LLM)

**Project:** CV Matcher — an ATS pipeline for parsing, scoring, and matching candidate CVs
**Author:** Yasser Boudriga — ENSIASD (1st year engineering)
**Context:** AI internship project, Linkrs Morocco
**Phase:** 2 of 6 (Ingestion → **Extraction** → Scraping → Matching → Backend/DB → UI)

---

## 1. Objective

The extraction layer turns the **raw, unstructured text** produced by Step 1 into a
**structured, validated candidate profile** (JSON). This profile is the object that every
later stage — scoring, matching, storage, display — operates on. The goal is not just to
pull out fields, but to do so **reliably**, while being honest about the confidence of each
field.

## 2. Why extraction is hard

Raw CV text has three properties that defeat naive rule-based parsing:

1. **Unstructured & inconsistent** — every CV has a different layout, order, and vocabulary.
2. **Multilingual** — Moroccan CVs mix French, Arabic, and English, often in the same
   document.
3. **Noisy** — text from scanned/photographed CVs contains OCR errors (character confusions
   such as `1`↔`l`, scrambled reading order, dropped sections).

A pure regular-expression approach can reliably capture only rigidly-formatted fields
(email, phone). Everything semantic (skills, experience, a summary) requires understanding
*meaning*, which motivates a hybrid design.

## 3. Architecture: a hybrid extractor

The design splits fields by **how reliably they can be identified**:

| Field type | Method | Rationale |
|---|---|---|
| Exact patterns (email, phone) | **Regex** (deterministic) | 100% predictable; on native text, exact and free. |
| Semantic fields (name, skills, education, experience, projects, languages, summary) | **LLM** | Requires understanding meaning; robust to noise and multiple languages. |

```
  raw text ──► clean_text() ──► LLM extraction ──► Candidate (pydantic)
                                                        │
                                   regex + validation + provenance
                                                        │
                                                        ▼
                                          validated Candidate (JSON)
```

**Files created:**
- `extract/schema.py` — the `Candidate` data model (pydantic).
- `extract/llm_client.py` — the LLM client (OpenRouter, OpenAI-compatible).
- `extract/regex_fields.py` — deterministic email/phone extraction.
- `extract/cv_parser.py` — orchestration: clean → LLM → validate → provenance.

## 4. The data model (pydantic)

A typed `Candidate` schema defines the exact shape of the output and **validates** the LLM's
response. Fields: `name, title, email, phone, location, skills[], languages[], education[],
experience[], projects[], years_experience, summary, warnings[]`. Nested `Education` and
`Experience` sub-models give structure to those lists. Using pydantic means malformed output
fails loudly and early, instead of propagating silently.

## 5. The LLM component

- **Provider:** OpenRouter, using a **free** model via an OpenAI-compatible API. The model
  name is a single configurable constant (*configuration over hardcoding*), so a deprecated
  model is swapped in one line.
- **Prompt design:** the model is instructed to return **only** a JSON object with an exact
  set of keys, to use `null`/`[]` for missing data, to correct obvious OCR errors *only when
  confident*, and — critically — to **never invent information**.
- **Determinism:** `temperature=0` for stable, repeatable extraction.
- **Defensive JSON parsing:** the response is stripped of any markdown fences and the JSON
  object is isolated with a regex before parsing, so minor formatting deviations don't crash
  the pipeline.

### Security
The API key is a secret. It is stored **only** in a `.env` file (git-ignored) and loaded at
runtime; it is never hardcoded or committed. During development a key was accidentally
exposed and was immediately **rotated** — the correct response to any leaked credential.

### Resilience
Free models occasionally return empty responses. The extractor therefore **retries** on an
empty result and raises a clear, inspectable error if all attempts fail. This reflects a
real principle: a system that depends on an external service must tolerate that service's
unreliability.

## 6. Deterministic validation and data provenance (key contribution)

This is the most important design decision of the stage, and it directly addresses a real
failure observed in testing.

**The problem.** On a scanned CV, OCR misread the email `...yasser1@gmail.com` as
`...yesseri@amall.com`. This is a *plausible-but-wrong* value: it is a syntactically valid
email, so **format validation alone cannot detect that it is wrong** — the correct
characters were destroyed by OCR and cannot be recovered from the document.

**The principle.** *You cannot correct information that OCR destroyed, and you must never
fabricate contact data.* The correct engineering response is to judge each field's
reliability by its **source (provenance)**, not only its format:

1. **Hybrid preference** — for email/phone, a valid regex hit on the (intact) native text is
   preferred over the LLM's value.
2. **Format validation** — a syntactically invalid field (e.g. an email with no `.tld`) is
   rejected: set to `null` and a warning is recorded.
3. **Provenance flagging** — the ingestion layer reports whether the text came from a real
   text layer (`native`) or from OCR (`ocr`). Contact fields extracted from an OCR source
   are **flagged for human verification**, however valid they look, because OCR can produce
   plausible-but-wrong values that no automated check can catch.

Every field's uncertainty is surfaced in a `warnings` list. The system therefore
**knows what it does not know** — it never presents low-confidence data as fact.

## 7. Testing and evaluation

The extractor was evaluated on **four inputs** representing every ingestion path, covering
two different candidates (a data-scientist profile and an accountant profile).

| Input (candidate) | Source method | Email result | Warnings | Overall |
|---|---|---|---|---|
| Native PDF (Yasser) | native | `boudrigayasser1@gmail.com` — **correct** | none | Richest profile: 27 skills, 3 diplomas w/ institutions, 6 projects, summary |
| DOCX (Zakaria) | native | `Boudad.zakaria92@gmail.com` — **correct** | none | 5 experiences w/ dates, 3 diplomas, contact exact |
| Scanned PDF (Yasser) | ocr | corrupted → **nulled** | email "needs review", phone "verify" | Core skills/education recovered; contact correctly rejected |
| Photo JPG (Yasser) | ocr | `...yasserl@gmail.com` (`l`≠`1`) | email + phone "verify" | Good recovery; wrong-but-flagged contact |

### Key findings
- **Native sources** produced **fully correct** contact data with **no warnings** — trusted.
- **OCR sources** produced degraded contact data that was **correctly nulled or flagged** —
  never presented as fact.
- The **same architecture** behaves **differently by source reliability**, which is exactly
  the intended provenance behaviour.
- Semantic extraction (skills, education, projects, languages) was strong across all inputs,
  including multilingual French content.

## 8. Limitations

- Contact accuracy on scanned/photo CVs cannot be guaranteed (an inherent OCR property); the
  system mitigates this by flagging rather than fabricating.
- `years_experience` is an LLM **estimate**, not a stated fact, and should be treated as
  approximate.
- Language proficiency levels (e.g. "Bon niveau") are simplified to the language name.
- A few niche items (e.g. driving licences) were occasionally missed.

## 9. Conclusion and transition

The extraction layer reliably converts noisy, multilingual CV text into a structured,
**validated** candidate profile, using a hybrid regex + LLM approach and a **provenance-aware
confidence mechanism** that flags untrustworthy fields instead of guessing. Combined with
Step 1, the pipeline now takes *any* CV file and outputs a clean candidate object.

The next phase collects the **job offers** this candidate will be matched against — starting
with roles that require **Dutch** — via web scraping.

**Next step → Step 3: Job scraping (Dutch-requirement roles).**
