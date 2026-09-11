# Step 8 — Synthesis: What This Project Actually Argues

## 1. What was built

Across seven phases, a CV arrives in whatever form a candidate has it — a scan, a phone
photograph, a Word file, a message on Telegram — and leaves as a structured profile, embedded
into a shared vector space, ranked against live job openings with an explanation a recruiter can
act on, inside an interface that separates what a candidate may see from what a recruiter may
see.

| Phase | What it does |
|---|---|
| 1. Ingestion | Any CV format becomes text, with OCR fallback for scans and photographs |
| 2. Extraction | Regex for exact fields, an LLM for meaning, validated and flagged for provenance |
| 3. Database | Three related tables in Supabase/PostgreSQL, with pgvector for semantic search |
| 4. Job collection | An official API, queried in four languages, deduplicated on a stable identifier |
| 5. Matching | Eligibility gates, vector retrieval, then an LLM that scores and explains |
| 6. Web application | Two interfaces, two authentication systems, access control enforced structurally |
| 7. Automation | A messaging channel that removed its own hosting requirement |

That is the inventory. It is not, by itself, the argument. Read as seven separate features, the
project is a competent pipeline. Read for what recurs across them, it is something more
specific: a small number of positions, applied consistently, often at real cost to convenience.
This chapter names those positions.

## 2. The machine states what it does not know

The first version of Step 2 trusted its own output. It stopped trusting it the moment OCR
misread `boudrigayasser1@gmail.com` as `boudrigayasserl@gmail.com` — a single character, `1` to
`l` — and produced an address that was syntactically perfect and factually wrong. No format
check could have caught it, because the corrupted value was not malformed. It was a different
valid email.

The fix was not a better OCR engine. It was to stop asking the extraction to be certain and
start asking it to say when it was not:

```python
if source_is_ocr:
    if candidate.email:
        candidate.warnings.append("Email from a scanned/photo CV — verify with candidate.")
```

That single decision reappears, in different words, in every phase that follows it:

- **Step 3** stores `source_method` and `warnings` as permanent columns, not incidental fields —
  the doubt is kept, not discarded at the storage boundary.
- **Step 4** separates a salary read from a job posting (`details.salary`) from one confirmed by
  telephone (`hr_salary`). They are not the same claim, and the schema does not pretend they are.
- **Step 6** surfaces `source_method` in the recruiter's candidate list — `native`, `ocr`,
  `telegram/vision` — so a human decides how much to trust a row before acting on it, rather than
  the system deciding for them.
- **Step 7** carries the identical pattern into JavaScript, in a different runtime, written by a
  different tool: `source_method: 'telegram/vision'`, `warnings.push('email_non_lisible')`. The
  principle survived a change of programming language because it was never really about the
  language. It was about refusing to let an uncertain value pass as a certain one.

**The claim, stated once:** a system that cannot always be right must be able to say when it
might be wrong. Confidence should be a property the data carries, not an assumption baked into
how it is displayed.

## 3. Machine inference yields to human knowledge

A second position, independent of the first, appears wherever the system tries to infer state
that a human might already know with certainty.

**Job expiry (Step 4).** The API never announces that a posting has closed. Its absence from a
search result is inferred as staleness — but only conditionally:

```sql
UPDATE jobs SET status = 'expired'
WHERE status = 'active'
  AND hr_verified = false
  AND last_seen_at < now() - make_interval(days => %s)
```

`hr_verified = false` is the clause that matters. A job a recruiter confirmed by telephone is
never auto-expired because a scrape happened to miss it that week. A weak, indirect signal
(absence from search results) is not permitted to override a strong, direct one (a human
who called the company).

**Match status (Step 5).** Re-running the reranker refreshes scores but leaves the workflow
status untouched:

```sql
-- status and note are deliberately NOT updated
```

If a recruiter has already moved a candidate to `presented`, a re-scored match does not silently
revert them to `suggested`. The model's opinion may update; a person's decision does not get
overwritten because the model ran again.

**Candidate identity (Step 6).** A Google-verified email replaces whatever the extractor read
from the document — not because Google is smarter than the LLM, but because a verified identity
is a stronger claim than an inferred one, and the system is built to prefer the stronger claim
when both are available.

Three subsystems, three languages of implementation (SQL, SQL, Python), one rule: **when a human
has already established a fact, an automated re-inference of that fact must not override it.**
This is not a coincidence of naming. It is the same design decision, made three times, because
the situation that calls for it recurs.

## 4. Instruct the model, then verify what it returns

The project depends on LLMs for extraction, structuring, and assessment throughout — and treats
every one of those calls as a request, not a guarantee.

Step 2's schema does not merely ask the model for `[]` on an empty list; it coerces `null` into
`[]` regardless of what arrives, because the prompt is not self-enforcing:

```python
@field_validator("skills", "languages", "education", "experience", "projects", "warnings",
                 mode="before")
def none_to_list(cls, v):
    return [] if v is None else v
```

Step 5 tells the reranker never to write "no gaps found" as a gap, and then filters exactly that
phrase out of the response in code, because the instruction and the model's compliance with it
are two different things:

```python
filler = ("aucune lacune", "aucun gap", "pas de lacune", ...)
return [x for x in v if not any(f in str(x).lower() for f in filler)]
```

Step 7's vision extraction is wrapped in a fallback list of four models, because a prompt sent
to a model that has been silently withdrawn from the provider's catalogue returns nothing useful
no matter how well the prompt is written.

**The position:** a system prompt describes intent; it does not enforce behaviour. Every
instruction given to a model in this project is paired with code that checks whether the
instruction was actually followed, and repairs the case where it was not.

## 5. The compliant route was chosen when it was also the harder one

Step 4 found that `moncallcenter.ma`'s `robots.txt` disallowed automated access, and used an
official job-search API instead of scraping the more complete source. Step 7 found that two
WhatsApp libraries — OpenWA and Whapi — could have delivered the desired channel faster and with
less friction, and rejected both: OpenWA's own documentation states it should be treated as **not
approved** for a use like this one, and Whapi's free tier could not have sustained a real
demonstration. An official Bot API with no equivalent restriction was used instead.

Two vendors, two unrelated technologies, one rule applied to both under real inconvenience. A
principle followed once, when it happens to be convenient, is not evidence of anything. Followed
twice, at a measurable cost each time — a smaller job corpus in Step 4, a channel the target
population uses less in Step 7 — it is a position the project actually holds, not a coincidence
of what was easiest.

## 6. Two failures found by asking the adversarial question, not the functional one

Every phase up to Step 6 was tested by asking "does this produce the correct output for valid
input?" Step 6 was tested by asking a different question — "what can a user with bad intentions
do here?" — and that question found two real defects that the first one never would have.

**The IDOR.** `POST /candidate/{id}/update` verified that a request came from *someone*, but
never checked whether it came from the candidate that record belonged to. The code was correct
in every respect the functional question would have tested. It was wrong in the one respect the
adversarial question was built to find: authentication answers *who is this*; authorization
answers *may they touch this specific object*. The system had implemented the first and had not
yet implemented the second at all.

**The exposed table.** Row-Level Security was never enabled on `candidates`. Supabase's
publishable key is public by design — meant to sit in browser code — and its entire safety model
assumes RLS is switched on to constrain what that public key can see. It was not switched on, and
the application worked in every functional test throughout the project, because nothing in
normal use ever tried to read the table with that key. The defect was invisible to correctness
testing by construction; it only exists in the gap between what an admin session is meant to
access and what anyone holding the public key could access instead.

**The general lesson:** correctness and security are different questions, verified by different
methods. Testing that a system does what it should does not test whether it can be made to do
what it should not. Both defects here were fixed the same day they were found — the point is not
that they slipped through, which is ordinary, but that finding them required deliberately asking
a question the rest of the project's testing never asked.

## 7. What the architecture chose not to require

Step 7's most consequential decision was not which messaging platform to use — it was replacing
`image → OCR → text → LLM` with `image → vision model → JSON`. That single substitution removed
an entire category of infrastructure the original design depended on: a server running Tesseract,
reachable from the internet, for n8n to call.

```
Telegram → n8n Cloud → vision model (OpenRouter) → Supabase
                     → HuggingFace Inference API   → vector
```

Every component in that chain is a managed service. No VPS, no domain, no certificate, no uptime
obligation for a student project. This was not a workaround adopted because hosting was
unavailable — it was a re-examination of what the extraction step actually required, which
turned out to be less than the first design assumed. The hosting problem was not solved with
infrastructure. It was dissolved by not needing the infrastructure in the first place.

## 8. What is still owed

Two defects are diagnosed, fixed, and verified as of this writing:

- Row-Level Security is enabled on all three tables; the public key was re-tested and confirmed
  to return nothing.
- The n8n Supabase nodes now authenticate with a service-role credential rather than the public
  key, and file storage was corrected after two further bugs — a bucket-name mismatch and a
  malformed signed-URL prefix — both found by testing the actual output, not assuming success
  from a green checkmark.

What remains **stated, not fixed**, because a report claiming a system is finished is worth less
than one that says precisely what is not:

- **No lexical baseline.** The claim that semantic matching outperforms keyword matching is
  demonstrated on one hand-picked example (Step 5), not measured across the corpus. A TF-IDF
  comparison was scoped and never run.
- **No comparison between OCR and vision extraction**, despite both existing in the codebase side
  by side for exactly this purpose. Four attempts were blocked by free-model availability — one
  endpoint withdrawn, one rate-limited, one returning empty responses — and the comparison is
  recorded as a constraint rather than quietly dropped.
- **No automated tests.** Every verification in this project was manual: a script run, an output
  inspected, a query checked by hand. That was sufficient to build and debug the system. It is
  not sufficient to keep it correct as it changes.
- **A single shared recruiter account**, with no audit trail of who changed what — acceptable for
  a demonstration, not for a system handling real candidates.
- **Duplicate identity across channels.** A candidate who applies once through the website and
  once through Telegram, using two different email addresses, is stored as two people. This was
  observed directly during development and corrected by hand; nothing in the system detects it
  automatically.

## 9. Conclusion

The seven preceding chapters describe what was built. This one describes what was decided, and
the decisions repeat: flag uncertainty instead of hiding it; let human knowledge outrank
automated inference; instruct a model and then verify what it actually returned; take the
compliant path even when it costs more; test for what a system should refuse to do, not only for
what it should correctly do; and prefer removing a requirement over building around it.

None of these positions were declared in advance as principles to follow. Each was a response to
a specific failure — a misread character, an API that lied about its own identifiers, a route
that checked identity but not ownership, a public key that could read what it was never meant to.
That they converge on the same handful of ideas, independently, across a database schema, a
matching engine, a web framework, and a workflow tool in a different programming language, is the
part of this project worth taking seriously. It suggests the positions were not arbitrary choices
made once and forgotten. They were the correct response, arrived at again each time the same kind
of problem reappeared.
