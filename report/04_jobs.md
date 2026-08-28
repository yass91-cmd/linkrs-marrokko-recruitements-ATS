# Step 4 — Job Collection: API Integration, Structuring and Data Modelling

**Project:** CV Matcher — an ATS pipeline for parsing, scoring, and matching candidate CVs
**Author:** Yasser Boudriga — ENSIASD (1st year engineering)
**Context:** AI internship project, Linkrs Morocco
**Phase:** 4 of 6 (Ingestion → Extraction → Database → **Job Collection** → Matching → UI)

---

## 1. Objective

The previous phases built the **candidate side** of the system: any CV file is converted into a
structured, validated, stored profile. But a matching system needs *two* sides. This phase
builds the **job side**: acquiring real job openings, structuring them to the same standard as
the candidate profiles, and storing them in a way that supports both automated matching and
the human recruitment workflow that follows.

The concrete target was defined by the business context: **Linkrs places Moroccan candidates
into Dutch-speaking roles**. In Morocco, a substantial outsourcing/BPO sector serves Belgian
and Dutch clients, creating a steady demand for *néerlandophone* customer-service, sales and
team-lead positions in Casablanca, Marrakech, Rabat and Kénitra. These are the openings the
system must collect.

---

## 2. Acquisition strategy: why an API instead of web scraping

The original plan was to scrape a Moroccan job board. Before writing a single line of scraping
code, the source's crawling policy was checked — a step that is both a legal obligation and a
professional norm.

### 2.1 The robots.txt check

`moncallcenter.ma` is the dominant source of Moroccan call-centre job postings and appeared as
the publisher of most relevant openings. Its `robots.txt` was examined and found to:

- **explicitly disallow** the job-offer paths (`/…/offres-emploi`), which are precisely the
  pages that would need to be crawled;
- **block roughly 500 automated user-agents** by name — including common scraping frameworks
  such as Scrapy — with a blanket `Disallow: /`.

**Decision: the site was not scraped.** The `robots.txt` protocol is the standard mechanism by
which a site declares which automated access it permits; ignoring an explicit prohibition
would be both unethical and, depending on jurisdiction and terms of service, potentially
unlawful. Additionally, scraping a site that actively blocks bots would have produced a
fragile system requiring evasion techniques — the opposite of good engineering.

### 2.2 Choosing an official API

The alternative chosen was **JSearch**, a job-search API distributed via the RapidAPI
marketplace. It aggregates listings surfaced through Google for Jobs, which indexes the
Moroccan boards (including ReKrute, Moncallcenter.ma and jobiglo) with the publishers'
consent. This has four decisive advantages over scraping:

| Aspect | HTML scraping | Official API |
|---|---|---|
| **Legality** | Depends on robots.txt / ToS; disallowed here | Explicitly permitted, contractual access |
| **Stability** | Breaks whenever the site's HTML changes | Versioned, documented response schema |
| **Data quality** | Requires parsing markup, error-prone | Clean, normalized JSON |
| **Maintenance** | High — selectors rot constantly | Low |

**This is a substantive engineering result, not a compromise.** Choosing a compliant,
structured source produced a *more robust* system than scraping would have, in addition to
being legally sound. It is documented here as a deliberate architectural decision.

### 2.3 Operating within the API's constraints

The free tier permits approximately **200 requests per month**. This constraint actively shaped
the design rather than being a mere inconvenience:

- The scheduled collection interval (24–48 hours) was chosen to fit comfortably within the
  quota: at one run every 48 hours, ~15 runs/month; at 24 hours, ~30 runs/month — both far
  below the limit even with several requests per run.
- The full API response was initially preserved in the database so that additional fields
  could be extracted later **without spending further quota** (this decision was subsequently
  revised — see §6.3).

Respecting a third party's published rate limits is part of using external data responsibly,
and is the API equivalent of respecting `robots.txt`.

---

## 3. Targeting Dutch-requirement roles

Two strategies were considered:

- **Strategy A — collect broadly, filter later.** Fetch all Moroccan jobs and tag those that
  mention Dutch. Maximises data, but spends most of the quota on irrelevant listings.
- **Strategy B — query narrowly.** Search specifically for Dutch-language roles.

**Strategy B was selected**, on the condition that it be *empirically validated* before being
committed to — following the project's standing principle of measuring before building.

### 3.1 Query design

The search term `néerlandais` (French for "Dutch") was used rather than the English "Dutch",
because Moroccan job postings are written predominantly in French. Combined with
`country=ma`, this targets the intended market directly.

### 3.2 Validation and defence-in-depth

A test query returned **10 results, of which 10 genuinely required Dutch** — a 100% precision
rate. Strategy B was therefore confirmed as viable.

Nevertheless, a **local verification step** was implemented rather than trusting the search
engine's relevance ranking. Every returned listing is checked against a keyword set covering
the term's variants across the three relevant languages:

```
dutch, nederlands, nederlandstalig, néerlandais, neerlandais,
néerlandophone, neerlandophone, flamand, flemish
```

Only listings whose title or description contains one of these terms are stored. This is a
**defence-in-depth** measure: if the API's ranking ever degrades or returns loosely-related
results, irrelevant jobs are still excluded. A system should not assume an external service
will always behave as it did during testing.

---

## 4. Structuring job descriptions with an LLM

The API returns a job's requirements as a **single block of unstructured free text**. The
structured `job_highlights` field, which would in principle contain parsed qualifications, was
found to be **empty for every Moroccan listing examined** — a concrete example of an API's
optional fields being unpopulated for a niche market.

Since matching requires structured, comparable data, the same architectural pattern developed
for CVs in Step 2 was **reused** for jobs: an LLM converts free text into validated JSON.

### 4.1 The `JobDetails` schema

A pydantic model defines the target structure:

| Field | Purpose |
|---|---|
| `missions` | What the role involves day-to-day |
| `requirements` | What the candidate must have |
| `languages` | **Languages required** — critical for matching |
| `contract_type` | CDI, CDD, freelance… |
| `salary` | Stated compensation, when mentioned |
| `schedule` | Working hours |
| `benefits` | CNSS, mutuelle, bonuses… |
| `experience_required` | Minimum experience |

### 4.2 Results

Applied to a real Team Leader posting, the extractor produced **8 missions, 12 requirements,
5 benefits**, the contract type (`CDI`), the experience requirement, and — most importantly for
matching — `languages: ["Néerlandais", "Anglais", "Français"]`. Free text became queryable
structure.

`salary` and `schedule` returned `null`, correctly reflecting that the API's description
excerpt did not contain them. **The model did not invent values** — consistent with the
"never fabricate" rule established in Step 2.

### 4.3 Failure isolation

The structuring call is wrapped so that **an LLM failure cannot cause data loss**: if the model
is unavailable or returns unparseable output, the job is still stored with `details = NULL`,
and a warning is logged. This reflects a general principle:

> A failure in an **enrichment** step must never destroy the **core** data.

The free model used has demonstrated intermittent failures (empty responses, stray
non-JSON output), which makes this isolation a practical necessity rather than a theoretical
precaution.

---

## 5. Data modelling: designing the `jobs` table

The schema was developed iteratively, beginning at 19 columns and reduced to a final **15**.
The reduction was driven by a single question applied to every column:

> *"What decision does this column enable? If none, it is removed."*

### 5.1 Grouping columns by purpose

Organising the schema by **role** rather than by data type made the redundancies visible:

| Group | Columns | Rationale |
|---|---|---|
| **Identity** | `job_uid` | Stable key enabling deduplication |
| **Job facts** | `title`, `employer`, `city`, `is_remote`, `apply_link`, `description`, `details` | Everything acquired from the source |
| **HR enrichment** | `hr_verified`, `hr_salary`, `hr_notes` | Information obtained from human contact (workflow step 2) |
| **Internal** | `note` | The recruiter's own annotations |
| **Lifecycle** | `status` | Is this posting still open? |
| **AI** | `embedding` | 384-dimension vector for semantic matching |
| **Audit** | `last_seen_at`, `created_at` | Timestamps supporting the expiry rule |

### 5.2 Columns removed, and why

- **`posted_at`** — `null` in 100% of observed records. A permanently empty column is worse
  than no column: it clutters the model and invites logic that can never execute.
- **`publisher`** — redundant; the source domain is already contained in `apply_link`.
- **`employment_type`** — redundant with `details->contract_type`, which additionally
  carries the more informative local value (`CDI`) rather than a generic enum (`FULLTIME`).
- **`country`** — constant (`Morocco`) for every row; a column with one distinct value stores
  no information.
- **`requires_dutch`** — constant (`true`), since non-Dutch roles are filtered out before
  insertion. The filter is applied at ingestion, so the flag is meaningless.
- **`raw`** — the complete API response. Retained initially as insurance against the request
  quota, then removed because everything of value was already extracted into `description`
  and `details`, and its size rendered the table unreadable during demonstration.
- **`job_id`** — see §6.1; superseded by `job_uid`.

### 5.3 Separating human-provided from machine-acquired data

`hr_salary` and `hr_notes` exist as distinct columns rather than overwriting the scraped
fields. This preserves **data provenance** — the same principle applied to candidates in
Step 2, where `source_method` distinguishes native text from OCR text. The system consistently
records *where each fact came from*, because facts from different sources warrant different
levels of trust.

`hr_salary` is kept as its **own column** rather than being folded into `hr_notes`, following
a general modelling rule:

> Anything that will be **filtered, sorted or compared** deserves its own column; everything
> else belongs in free text.

Salary is a primary filter criterion in recruitment ("Dutch roles paying above X"). Buried in
free text it would be unqueryable. Conversely, the contact person's name and the urgency of a
vacancy are read but never sorted, so they belong in `hr_notes`.

### 5.4 Constraining the lifecycle field

`status` is declared with an explicit constraint:

```sql
status text NOT NULL DEFAULT 'active'
       CHECK (status IN ('active', 'filled', 'expired', 'closed'))
```

An unconstrained text column silently accepts `'activ'`, `'Active'` or `'ACTIVE'`, each of
which would be excluded from a query filtering on `'active'` — a failure mode that produces
**wrong results without any error message**. The `CHECK` constraint makes the database itself
reject invalid values at write time.

### 5.5 Job state versus match state

A deliberate boundary was drawn between two different state machines:

- **`jobs.status`** describes the *posting*: is it still open? (`active`, `filled`, `expired`,
  `closed`)
- **`matches.status`** (Step 5) will describe a *candidate–job pair*: where is this particular
  candidate in the process? (`presented`, `approved`, `applied`, `result`)

Placing the second on the `jobs` table would break as soon as two candidates are submitted to
the same opening: a single job-level field cannot simultaneously be "presented" for one
candidate and "approved" for another. Recognising that these are **states of different
entities** is a fundamental relational-modelling decision.

---

## 6. Debugging case studies

Three genuine defects were discovered and resolved. Each is documented because the *method* of
diagnosis matters as much as the fix.

### 6.1 An unstable primary key (critical)

**Symptom.** The deduplication mechanism (`ON CONFLICT (job_id) DO NOTHING`) appeared to do
nothing: after two collection runs the table contained 17 rows representing only ~11 distinct
jobs. Six postings were stored twice, with identical titles and employers.

**Investigation.** The data was exported to CSV and inspected manually — a step that made the
duplication visible in a way that browsing the table had not. Comparing the `job_id` values of
a duplicated pair revealed the structure:

```
bXdrTm5sNE1TZEpSVUdMdUFBQUFBQT09 : OkVzc0JDb3dCUVVwcFZEUjBTazUz…   ← run 1
bXdrTm5sNE1TZEpSVUdMdUFBQUFBQT09 : OkVzd0JDb3dCUVVwcFZEUjBURUpP…   ← run 2
└────────── identical ──────────┘   └────── differs per request ───┘
```

The identifier is a **composite**: a stable prefix, a colon, then a volatile token. Decoding
the stable prefix from base64 produced `mwkNnl4MSdJRUGLuAAAAAA==` — exactly the value of a
separate field in the response, **`job_uid`**. The volatile suffix is a per-search tracking
token that changes on every request.

**Root cause.** `job_id`, despite its name, is **not a stable identifier**. The `ON CONFLICT`
clause therefore never matched, because the key was different every time.

**Fix.** `job_uid` was adopted as the primary key. After the change, two consecutive runs
produced **10 rows, all distinct** — deduplication verified.

**Lesson.** An external API's most obviously-named identifier is not necessarily its stable
one. Identifier stability must be *verified empirically across requests*, never assumed from
the field name.

### 6.2 Unexpected response language

**Symptom.** Stored values appeared in Arabic: `employment_type` contained `دوام كامل`, and
location strings read `الدار البيضاء`.

**Root cause.** The API echoes its resolved parameters in the response, which revealed
`"language": "ar"`. For `country=ma`, the service had defaulted to Arabic.

**Fix.** An explicit `language=fr` parameter was added, matching the language of the source
postings.

**Lesson.** Inspect the parameters an API *actually applied*, not only the ones you sent.
Defaults are chosen by the provider and may not suit your use case.

### 6.3 Placeholder values and missing structured fields

Two data-quality issues were addressed in normalisation:

- **`employer` = `"Unspecified"`.** The API uses this literal string where the employer is
  unknown. Stored verbatim it is a **magic string** — it reads as a real company name, and a
  query for records with an unknown employer (`WHERE employer IS NULL`) would miss them
  entirely. A normalisation function converts it (and similar placeholders) to `NULL`, which
  is what SQL provides for representing absent values.
- **`city` = `null` despite the city being known.** The dedicated city field was unpopulated,
  yet the city appeared in the location string and frequently in the title itself
  (e.g. *"…h/f casablanca"*). A detection function checks the city field, then the location
  string, then the title, matching against a dictionary of Moroccan cities in both Latin and
  Arabic script. This recovered the city for **7 of 10** records; the remaining three are
  legitimately absent (one is a fully remote *télétravail* role).

**Lesson.** An API field being `null` does not mean the information is unavailable — it may
simply be located elsewhere in the payload. Reading the *whole* response before modelling it
recovers data that a field-by-field mapping would discard.

---

## 7. Deduplication and the freshness mechanism

Because collection is **scheduled and repeated**, the insert uses an upsert:

```sql
ON CONFLICT (job_uid) DO UPDATE SET last_seen_at = now()
RETURNING (xmax = 0) AS inserted;
```

- A **new** job is inserted.
- An **already-known** job is not duplicated; instead its `last_seen_at` is refreshed,
  recording that the posting is still being advertised.
- `RETURNING (xmax = 0)` uses a PostgreSQL system column to distinguish a genuine insert from
  an update, so the run can still report how many jobs were *newly* discovered.

This converts the scraper from an append-only script into a **stateful synchroniser**: each run
tells the system which postings are still live.

---

## 8. Determining whether a posting has expired

A job board does not announce closures, and the API provides no "closed" signal. Expiry
therefore **cannot be observed — only inferred**. Three signals of differing strength were
evaluated:

| Signal | Mechanism | Strength | Adopted? |
|---|---|---|---|
| Absence from results | `last_seen_at` older than ~7 days | **Weak** | ✅ as a re-check flag |
| Dead apply link | HTTP request to `apply_link` returning 404 | Moderate | ❌ (see below) |
| HR confirmation | The recruiter telephones the company | **Authoritative** | ✅ |

**Why the absence signal is weak.** The search returns a limited number of results per page. If
more Dutch-language openings exist than are fetched, listings drop out of results because of
**ranking and pagination**, not because they closed. Treating a single absence as expiry would
mark live jobs as dead. The signal is therefore only meaningful when several pages are
retrieved *and* a job has been absent across many consecutive runs.

**Why the link-check signal was rejected.** Verifying `apply_link` would require requesting a
page on `moncallcenter.ma`, whose `robots.txt` explicitly disallows those paths (§2.1). Having
declined to scrape the site, it would be inconsistent to probe it programmatically. The
conservative choice was made.

**The governing rule.** Automatic expiry must **never override a human-set status**. If a
recruiter has confirmed with the company that a position is open, a missed collection run must
not silently mark it expired.

> Machine inference yields to human knowledge.

This is the same principle that governs the CV pipeline, where OCR-derived contact data is
*flagged for verification* rather than trusted or discarded. In both cases the system
distinguishes what it **knows** from what it **guesses**, and defers to a human on the latter.

---

## 9. Results

Two consecutive collection runs produced:

| Metric | Result |
|---|---|
| Jobs returned by the API | 10 per run |
| Precision of the Dutch filter | **10 / 10** |
| Distinct jobs stored | **10** (0 duplicates after the `job_uid` fix) |
| Employers identified | 5 named (MLBOS, OCEANCALL GROUP, Konecta, jobiglo maroc, Marketing Call Center); 5 correctly `NULL` |
| Cities recovered | 7 / 10 (Casablanca, Marrakech, Kénitra); 3 legitimately absent |
| Descriptions structured by the LLM | All records, with missions, requirements and required languages |

The stored roles — team leader, *téléconseiller*, quality controller, insurance operator,
bilingual client advisor, including one remote position — accurately represent the Moroccan
Dutch-speaking employment market that Linkrs serves.

---

## 10. Limitations

- **Coverage** is bounded by the API's aggregation and by the free tier's request quota; the
  system observes a sample of the market rather than its entirety.
- **Salary data is largely absent** from postings, which is why the workflow relies on direct
  HR contact to establish compensation.
- **Expiry detection is inferential**, as analysed in §8, and is deliberately treated as a
  prompt for verification rather than a fact.
- **A single source** is used. Additional sources would improve coverage but would each
  require their own legality assessment and normalisation logic.

---

## 11. Conclusion and transition

This phase established the job side of the system. It selected a **legally compliant, stable
data source** after finding the intended scraping target prohibited by its `robots.txt`;
validated a **targeting strategy empirically** before committing to it; **reused the LLM
structuring pattern** from the CV pipeline to convert free-text descriptions into comparable
structured data; and produced a **deliberately-modelled schema** in which every column enables
a decision, provenance is preserved, and job state is correctly separated from match state.

Three real defects — an unstable API identifier, an unexpected response language, and
placeholder values masquerading as data — were diagnosed by **inspecting exported data rather
than assuming correctness**, which is itself a transferable engineering practice.

The database now holds **structured candidates** and **structured jobs**, with an empty
`embedding` column awaiting both. The next phase fills those columns and connects the two
sides: converting text to vectors, computing semantic similarity, and ranking each candidate
against the available Dutch-speaking positions.

**Next step → Step 5: The Matching Engine (embeddings, vector search, scoring).**
