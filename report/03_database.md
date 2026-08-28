# Step 3A — Persistence Layer (Supabase / PostgreSQL + pgvector)

**Project:** CV Matcher — an ATS pipeline for parsing, scoring, and matching candidate CVs
**Author:** Yasser Boudriga — ENSIASD (1st year engineering)
**Context:** AI internship project, Linkrs Morocco
**Phase:** 3A of 6 (Ingestion → Extraction → **Database** → Scraping → Matching → UI)

---

## 1. Objective

Until this phase, the pipeline extracted a candidate profile and then **printed it and forgot
it**. A real system needs **memory**: a place to persistently store candidates (and later,
jobs and matches) that the rest of the application can query. This phase adds that
persistence layer.

## 2. Why a database, and which one

A cloud **PostgreSQL** database (via **Supabase**) with the **pgvector** extension was chosen
over simpler options (e.g. a local SQLite file or CSV). The reasoning:

| Requirement | Why Supabase / Postgres + pgvector |
|---|---|
| Production-grade storage | PostgreSQL is a real relational database, not a toy file. |
| **Semantic matching (Step 4)** | `pgvector` stores embeddings and performs vector-similarity search **inside the database** — the foundation of the matching engine. |
| Cloud / deployment story | Hosted and reachable from anywhere; supports the later FastAPI + UI. |
| Free tier | No cost for a student project. |

The single-most important reason is **pgvector**: it lets the matching step run vector search
natively in the database rather than in application code.

## 3. Schema design

A single `candidates` table was created (see `db/schema.sql`). Key design decisions:

- **`jsonb`** columns for list/nested fields (`skills`, `languages`, `education`,
  `experience`, `projects`, `warnings`) — a natural, queryable fit for the nested pydantic
  `Candidate` model.
- **`embedding vector(384)`** — the pgvector column, dimensioned for the
  `all-MiniLM-L6-v2` embedding model used in Step 4. Adding it now means matching plugs in
  without a schema change.
- **`source_method`** (`native` / `ocr`) — carries data **provenance** (from Step 2) into the
  database, so confidence information is preserved and queryable.
- **`warnings` (jsonb)** — the per-field confidence flags travel with the record.
- **`created_at timestamptz`** — a standard audit timestamp.

The schema is stored as a versioned `schema.sql` file and applied by a small Python script
(`db/init_db.py`), so the database structure is **reproducible** and lives in version control
— a production practice, as opposed to clicking tables together by hand.

## 4. Connectivity: a real debugging case

Connecting from Morocco surfaced two real infrastructure issues, each solved methodically:

1. **IPv6-only direct host.** Supabase's *direct* connection host
   (`db.<ref>.supabase.co`) resolves only over IPv6; on an IPv4-only network it failed with
   `getaddrinfo failed`. **Fix:** switch to the **Session pooler** endpoint, which is
   IPv4-friendly.
2. **Region/tenant routing.** The pooler returned `tenant/user not found` because the host
   region must exactly match the project's region. **Fix:** copy the exact pooler host from
   the dashboard (`aws-1-eu-west-1.pooler.supabase.com`) rather than assuming a region.

This is documented as an example of diagnosing networking issues layer by layer (DNS →
routing → authentication).

## 5. Security

- **Secrets:** the database URL (with password) and the API key live only in `.env`, which is
  git-ignored — never committed. A credential accidentally exposed during development was
  **rotated** immediately.
- **SQL injection prevention:** all inserts use **parameterized queries** (`%s` placeholders
  with a values tuple), never string concatenation — the standard defense against SQL
  injection.
- **PII:** candidate records contain personal data; they live in the project's own database,
  and raw CV files remain excluded from version control.

## 6. The save pipeline

Two components complete the flow:

- `db/candidates_repo.py` — `save_candidate()` serializes the validated `Candidate` (with
  `jsonb` for lists) and inserts it, returning the new row id.
- `pipeline.py` — the end-to-end orchestrator: **file → text (+ method) → parsed profile →
  database**. A single command now processes any CV and stores the result.

A defensive fix was required here: the LLM occasionally returns `null` for a list field
instead of `[]`, and occasionally returns non-JSON text (e.g. a stray moderation string).
The schema now coerces `null → []` for list fields, and the extractor **retries** on empty or
unparseable responses with a strict JSON system prompt. *Building reliably on an unreliable
free model requires defensive validation and retries.*

## 7. Results

All four ingestion paths were run through the full pipeline and stored:

| id | Source | Method | Email stored | Warnings |
|---|---|---|---|---|
| 1 | Native PDF (Yasser) | native | `boudrigayasser1@gmail.com` (correct) | none |
| 2 | DOCX (Zakaria) | native | `Boudad.zakaria92@gmail.com` (correct) | none |
| 3 | Scanned PDF (Yasser) | ocr | `null` (rejected) | email + phone flagged |
| 4 | Photo JPG (Yasser) | ocr | `...yasserl@…` (wrong `l`) | email + phone flagged |

Rows 1, 3 and 4 are the **same candidate in three formats**, stored side by side. The
database now makes the provenance behaviour **visible and queryable**: native sources store
correct, unflagged contact data; OCR sources store flagged or nulled data. `embedding` is
`null` on every row, awaiting Step 4.

## 8. Limitations / future work

- **Deduplication:** the same person can be stored multiple times (one per uploaded file). A
  production system would deduplicate on email/name. (Left as future work; here it usefully
  demonstrates the pipeline across input types.)
- **Normalization:** list fields are stored as `jsonb` rather than fully normalized tables
  (e.g. a separate `skills` table). Acceptable for this scale; normalization is a possible
  extension.

## 9. Conclusion and transition

The pipeline now takes any CV file and **persists** a structured, validated, provenance-aware
candidate profile into a cloud PostgreSQL database that is ready for vector search. The
candidate side of the ATS is complete and durable.

The next phase collects the **jobs** to match candidates against — starting with roles that
require **Dutch** — via web scraping, storing them in a companion `jobs` table.

**Next step → Step 3B / 4: Job scraping (Dutch-requirement roles).**
