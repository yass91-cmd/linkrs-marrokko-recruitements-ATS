# Step 5 — The Matching Engine: Semantic Retrieval, Eligibility Gates and LLM Reranking

**Project:** CV Matcher — an ATS pipeline for parsing, scoring, and matching candidate CVs
**Author:** Yasser Boudriga — ENSIASD (1st year engineering)
**Context:** AI internship project, Linkrs Morocco
**Phase:** 5 of 6 (Ingestion → Extraction → Database → Jobs → **Matching** → UI)

---

## 1. Objective

The previous phases produced two independent halves of the system: structured **candidates**
and structured **jobs**, both stored in PostgreSQL. This phase connects them. Given a
candidate, the system must determine **which openings genuinely fit**, rank them, and — because
the decisions concern people's careers — **explain why**.

This is the analytical core of the project and the phase where the "AI" of the title does its
substantive work.

---

## 2. Why keyword matching is insufficient

The obvious approach is to search job descriptions for words from the CV. It fails on real
data, and the failure is easy to demonstrate with two authentic phrasings drawn from the
collected corpus:

- Candidate profile: *"téléconseiller néerlandais centre d'appel"*
- Job posting: *"conseiller client néerlandophone"*

These describe **the same role**, yet they share almost no tokens: *téléconseiller* ≠
*conseiller client*, *néerlandais* ≠ *néerlandophone*, and *centre d'appel* appears in only
one. A lexical method (exact matching, TF-IDF) would score this pair near zero.

The problem is compounded by three properties of the corpus:

1. **French vocabulary is highly variable** — the same job is advertised as *téléconseiller*,
   *conseiller client*, *chargé de clientèle*, or *agent de relation client*.
2. **The corpus is multilingual** — CVs mix French, Arabic and English; postings use French
   with Dutch and English terms embedded.
3. **CVs and job postings are different genres of text** — one describes a person's history,
   the other describes an employer's need. They rarely share phrasing even when they match
   perfectly.

Matching therefore requires comparing **meaning**, not **words**.

---

## 3. Embeddings: the underlying technique

An **embedding model** maps a piece of text to a fixed-length vector of numbers — here, 384
dimensions. The model is trained so that texts with similar meaning are placed close together
in this vector space, regardless of the specific words used. Proximity is then measured with
**cosine similarity**, which compares the *direction* of two vectors:

- **1.0** — identical direction (same meaning)
- **0.0** — orthogonal (unrelated)

Because it compares direction rather than magnitude, cosine similarity is unaffected by
document length — important here, where a CV may be far longer than a job description.

### 3.1 Model selection

The widely-used default, `all-MiniLM-L6-v2`, is **trained predominantly on English**. Since
every document in this corpus is French (with Arabic and Dutch elements), it was rejected in
favour of:

**`paraphrase-multilingual-MiniLM-L12-v2`** — trained on 50+ languages including French,
Dutch, Arabic and English, and producing **384-dimensional** vectors, matching the
`vector(384)` column already provisioned in the schema.

*Selecting a multilingual model is a domain-specific decision driven by the data, not a
default. Using the English model on French text would have degraded every subsequent result.*

### 3.2 Empirical validation of the model

Before integrating the model, its behaviour was verified on the exact linguistic problem
described in §2:

| Text pair | Cosine similarity |
|---|---|
| *"téléconseiller néerlandais centre d'appel"* vs *"conseiller client néerlandophone"* | **0.595** |
| *"téléconseiller néerlandais centre d'appel"* vs *"comptable fiscalité et paie"* | **0.101** |

A **6× separation** between the related and unrelated pair, on French text sharing almost no
vocabulary. This single measurement justifies the choice of semantic over lexical matching, and
was obtained *before* any integration work — consistent with the project's principle of
validating a component in isolation before building on it.

---

## 4. Representing a candidate and a job as text

An embedding model takes one string. A candidate record, however, has a dozen fields. Deciding
**what text represents an entity** is therefore a design decision that directly determines
match quality.

### 4.1 Candidate representation

The composed text includes: professional title, summary, skills, languages, education
(degree + institution), experience (title + company), and projects.

It **deliberately excludes name, email, phone and address**, for two reasons:

- **No signal.** A person's name and telephone number say nothing about their suitability for
  a role. Including them adds noise to the vector.
- **Data minimisation.** Personal identifiers are not sent to the embedding model at all. This
  is the GDPR principle of *data minimisation* applied concretely: process only what the
  purpose requires.

### 4.2 Job representation

Job text is composed from title, missions, requirements and required languages — drawn from
the **LLM-structured `details`** produced in Step 4, with a fallback to the raw description
where structuring failed. Using the structured fields concentrates the vector on
decision-relevant content rather than boilerplate about the company.

---

## 5. Architecture: a three-stage pipeline

No single technique addresses the whole problem, so the engine follows the
**filter → retrieve → rerank** pattern used in production search and recommendation systems.

```
   candidate
       │
       ▼
 ┌───────────────────┐
 │ STAGE 1 — GATES   │  deterministic rules: active jobs; Dutch requirement
 │ (rule-based)      │  → eligibility + explicit blocking reasons
 └─────────┬─────────┘
           ▼
 ┌───────────────────┐
 │ STAGE 2 — RETRIEVE│  pgvector cosine similarity over all jobs
 │ (embeddings)      │  → top N ranked by semantic proximity
 └─────────┬─────────┘
           ▼
 ┌───────────────────┐
 │ STAGE 3 — RERANK  │  LLM assesses only the top N
 │ (LLM)             │  → score 0-100 + strengths + gaps + summary
 └─────────┬─────────┘
           ▼
      persisted to `matches`
```

### 5.1 Stage 1 — Eligibility gates (rules, not scores)

Some requirements are **categorical, not gradual**. A role requiring Dutch cannot be filled by
a candidate who does not speak Dutch, no matter how strong the rest of the profile is. Encoding
this as a *similarity penalty* would be wrong: a sufficiently high score elsewhere could
override it.

Gates are therefore implemented as **deterministic rules**, evaluated separately from any
score, producing two outputs: a boolean `eligible`, and a list of `blocking_reasons`.

Crucially, ineligible jobs are **still ranked and returned, marked as blocked**, rather than
silently removed. An empty result list tells a recruiter nothing; *"85% match — blocked:
candidate does not list Dutch"* tells them exactly what is missing and what would change the
outcome.

### 5.2 Stage 2 — Semantic retrieval with pgvector

Similarity search runs **inside PostgreSQL** using the `pgvector` extension:

```sql
SELECT j.job_uid, j.title,
       1 - (j.embedding <=> c.embedding) AS similarity
FROM jobs j, candidates c
WHERE c.id = %s AND j.embedding IS NOT NULL AND j.status = 'active'
ORDER BY j.embedding <=> c.embedding
LIMIT %s;
```

`<=>` is pgvector's **cosine distance** operator (0 = identical), so similarity is
`1 - distance`. Performing the search in the database rather than in Python means no vectors
are transferred to the application, the ranking and the `status = 'active'` filter are applied
in a single query, and the approach scales without additional infrastructure. This is the
justification for having chosen PostgreSQL + pgvector in Step 3.

### 5.3 Stage 3 — LLM reranking and explanation

The top N results (N = 3) are passed to an LLM, which returns a structured assessment: a
score from 0 to 100, a verdict, a list of **strengths**, a list of **gaps**, and a one- or
two-sentence summary written in French, the agency's working language.

Applying the LLM only to a **shortlist** is what makes this economically viable: assessing
every candidate–job pair would require hundreds of calls, whereas reranking the top 3 requires
three. This is precisely why the architecture retrieves *before* it reranks.

The business rule from Stage 1 is restated in the prompt (*"if the candidate does not speak
Dutch, the score must be below 30"*), so the LLM's judgement remains consistent with the
deterministic gate rather than contradicting it.

---

## 6. Results

### 6.1 Cross-profile discrimination

Three candidates were evaluated against the same ten Dutch-requirement jobs:

| Candidate | Profile | Best semantic score | Eligible |
|---|---|---|---|
| #1 Yasser | Data Scientist / AI Engineer, no Dutch | 0.417 | ⛔ blocked |
| #2 Zakaria | Accounting & logistics, client-facing, no Dutch | 0.445 | ⛔ blocked |
| **#5 Ayoub** | **Dutch-speaking customer-support specialist** | **0.749** | ✅ **eligible** |

The qualified candidate scores approximately **70% higher** than the mismatched profiles — a
decisive separation rather than a marginal one. Simultaneously, the gate correctly blocks the
two candidates who do not meet the language requirement, each with a stated reason.

### 6.2 Discrimination *within* the mismatched profiles

A more subtle result: the two non-Dutch candidates were not merely scored differently — they
were matched to **different kinds of role**.

- **Yasser (data scientist)** ranked highest on *Qualiticien* (quality control) and
  *Team Leader* — the two most **analytical** roles in the set. The Team Leader posting
  requires *"optimisation des tableaux de bord, outils statistiques, reporting qualitatif et
  quantitatif"*; Yasser's CV lists *"Power BI, tableaux de bord interactifs, analyse
  statistique"*.
- **Zakaria (client-facing background)** ranked highest on *Conseiller relation client* and
  *Téléconseiller* — pure customer-service roles.

The model identified the statistical/reporting overlap **with no shared job titles and no
keyword rules**. This demonstrates that the system discriminates between profiles on substance
rather than returning a generic ranking.

### 6.3 The reranker changes the ranking — evidence that Stage 3 adds value

For the qualified candidate, the LLM's ordering **differed from the semantic ordering**:

| Job | Semantic rank | LLM rank |
|---|---|---|
| Téléconseiller Néerlandais (Casablanca) | 0.749 — 1st | 95 — 1st |
| Marrakech — chargés de clientèle | 0.700 — 2nd | **75 — 3rd ⬇** |
| Conseiller bilingue (télétravail) | 0.687 — 3rd | **92 — 2nd ⬆** |

The embedding placed the Marrakech role second. The LLM demoted it, reasoning that the
candidate — with 4+ years of experience — is **overqualified** for a position advertised as
requiring under 2 years, and noting the associated turnover risk.

This is recruiter judgement that vector similarity **cannot express**: cosine similarity
measures topical closeness, not seniority fit. The disagreement between the two stages is the
clearest evidence that the third stage contributes information the second cannot, and
therefore that the layered architecture is justified rather than redundant.

### 6.4 Explanations

For the qualified candidate, the system produced assessments such as:

> *"Ce candidat est un profil exceptionnellement bien adapté au poste de téléconseiller
> néerlandais à Casablanca. Avec un néerlandais certifié C1 et plus de 4 ans d'expérience
> approfondie dans le service client et la vente pour le marché néerlandophone, il dépasse
> largement les exigences du poste."*

with concrete strengths: C1 CNAVT certification, 4+ years in Dutch-speaking call centres,
CSAT above 92%, Salesforce/Zendesk proficiency.

For a blocked candidate:

> *"Le candidat possède des compétences techniques solides en analyse de données et reporting,
> mais manque de l'expérience en management d'équipe et de la maîtrise du néerlandais."*

with gaps naming the Dutch requirement as *éliminatoire*.

A recruiter can act on these sentences directly; a bare score of `0.749` supports no
conversation with either the candidate or the client.

---

## 7. Explainability as a requirement, not a feature

This system makes recommendations that affect people's employment. That places it in a
category where explanation is an obligation rather than a convenience:

- **Regulatory.** Automated decision-making about individuals attracts specific obligations
  under GDPR (relevant to the Dutch/Belgian clients served) and Morocco's *Loi 09-08*, among
  them the ability to explain the logic involved.
- **Operational.** A recruiter must justify a shortlist to a client company and give a
  candidate a reason. "The cosine similarity was 0.41" is not usable in either conversation.
- **Diagnostic.** Explanations expose errors. The overqualification finding in §6.3 was only
  visible because the system was required to articulate its reasoning.

The architecture supports this at every stage: Stage 1 emits **blocking reasons**, Stage 2
emits a **numeric similarity**, and Stage 3 emits **strengths, gaps and a summary in natural
language**. Every recommendation can be traced to a stated cause.

---

## 8. Persisting results: the `matches` table

Assessments are stored in a `matches` table — a **junction table** implementing the
many-to-many relationship between candidates and jobs (one candidate may match many jobs; one
job may match many candidates). Neither entity can hold this relationship alone, so it is
modelled as its own table.

### 8.1 Relational integrity

```sql
candidate_id bigint NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
job_uid      text   NOT NULL REFERENCES jobs(job_uid)  ON DELETE CASCADE,
UNIQUE (candidate_id, job_uid)
```

- **Foreign keys** ensure a match can only reference a candidate and a job that actually
  exist; the database rejects orphaned references.
- **`ON DELETE CASCADE`** removes a candidate's matches when the candidate is deleted — no
  orphaned rows, and a clean implementation of a data-erasure request.
- **`UNIQUE (candidate_id, job_uid)`** permits one assessment per pair, enabling an upsert
  rather than accumulating duplicates on re-runs.

### 8.2 Why the assessment is stored rather than recomputed

Recomputing an assessment on demand would consume API quota, add latency, and — as documented
in §10 — **return a different score each time**. Persisting the assessment means the score a
recruiter saw yesterday is the score they see today.

### 8.3 The workflow

The `status` column tracks the recruitment process defined by the agency:

```
suggested → presented → approved → applied → hired
                     ↘ declined              ↘ rejected
```

`declined` (the candidate refuses) and `rejected` (the company refuses) are distinguished,
because the two outcomes carry different operational meaning.

A `CHECK` constraint restricts `status` to these values. Without it, the column would silently
accept `'Presented'` or `'presnted'`, and a query filtering on `'presented'` would return
**wrong results with no error** — a failure mode that is far harder to detect than a crash.

### 8.4 Machine inference must not overwrite human state

The upsert deliberately refreshes the assessment fields **but not `status` or `note`**:

```sql
ON CONFLICT (candidate_id, job_uid) DO UPDATE SET
    similarity = EXCLUDED.similarity,
    llm_score  = EXCLUDED.llm_score,
    ...
    -- status and note are intentionally NOT updated
```

Re-running the matcher must never reset a match a recruiter has already advanced to
`presented` back to `suggested`. This is the **same principle** applied to job expiry in Step 4
and to OCR provenance in Step 2:

> The system distinguishes what it computes from what a human has established, and defers to
> the human.

That this rule appears independently in three separate subsystems indicates a coherent
architectural stance rather than an ad-hoc decision.

---

## 9. Defects identified and resolved

Four issues were found by inspecting real output — none would have been visible from the code
alone.

**9.1 Non-Latin characters in generated text.** The model intermittently emitted Chinese
characters inside French sentences (for example a certification label rendered with the Chinese
word for "Dutch" embedded in it). Resolved with an explicit prompt instruction *and* a
programmatic sanitiser that strips CJK ranges from all text fields.

**9.2 Filler content in the `gaps` list.** Rather than returning an empty list when a candidate
had no shortcomings, the model wrote entries such as *"Aucune lacune majeure identifiée"* — which
a user interface would render under a warning icon, misleading the reader. Resolved by
instructing the model to return `[]` and filtering known filler phrases.

**9.3 Over-broad filtering (a defect introduced by the fix for 9.2).** The filler filter was
initially applied to both `gaps` and `strengths`, which stripped *"dépasse les exigences"* —
legitimate as a **strength**, nonsense as a **gap**. The filter was narrowed to `gaps` only.
*A fix applied too broadly can create a new defect; the scope of a correction matters as much
as its content.*

**9.4 Inconsistent enumerated values.** Because summaries are requested in French, the model
occasionally returned `verdict = "faible"` instead of `"weak"`. As an enumerated field used
for filtering, a query for `'weak'` would silently miss those rows — **the identical failure
mode** that the `CHECK` constraint on `status` was designed to prevent, here occurring in real
data. Resolved by normalising the value in the validation layer and adding a `CHECK`
constraint at the database level.

**The recurring pattern in all four:** instructions to a probabilistic model are *requests*,
not guarantees. Every LLM output is therefore validated and normalised in code. This
**defence-in-depth** approach — instruct *and* enforce — is the same strategy applied to the
Dutch keyword verification in Step 4, where the API's relevance ranking is not trusted on its
own.

---

## 10. Limitations

- **Score instability.** Repeated runs produced different LLM scores for the same pair (one job
  scored 82, then 95, then 78) despite `temperature = 0`; the free model is not fully
  deterministic. **LLM scores should be treated as a ranking signal, not a precise
  measurement.** The deterministic semantic score is retained alongside it partly for this
  reason.
- **Absolute similarity values are low** (typically 0.25–0.75). This is expected: CVs and job
  postings are different genres of text and never reach the ~0.9 seen between two similar
  sentences. **The ranking is meaningful; the absolute magnitude is not.**
- **No labelled ground truth.** Without human-annotated correct matches, formal metrics such as
  precision@k cannot be computed. Evaluation here is comparative (does the system rank the
  right candidate highest?) rather than absolute.
- **No lexical baseline yet.** A TF-IDF implementation would allow the semantic gains to be
  quantified rather than argued. This is identified as the highest-value next addition.
- **Single hard gate.** Only the Dutch requirement is currently enforced; city, contract type
  and minimum experience could be added as further gates.

---

## 11. Conclusion and transition

The matching engine connects the two halves of the system through a three-stage pipeline:
deterministic **eligibility gates** that encode non-negotiable requirements, **semantic
retrieval** using multilingual embeddings and in-database vector search, and **LLM reranking**
that supplies both refined judgement and human-readable justification.

The results demonstrate that the system ranks a qualified candidate approximately 70% above
mismatched profiles, correctly blocks ineligible candidates with stated reasons, discriminates
between profiles on substance, and — in the reranking stage — identifies considerations such as
overqualification that vector similarity cannot represent.

Assessments are persisted in a relationally-sound junction table that tracks each candidate–job
pair through the agency's recruitment workflow, under the consistent rule that computed values
never overwrite human decisions.

The system is complete as a pipeline but currently operable only from a terminal. The final
phase provides a user interface, making the workflow usable by a recruiter rather than a
developer.

**Next step → Step 6: User Interface and Deployment.**
