# Step 7 — Automation and Messaging: Reaching Candidates Where They Already Are

## 1. Objective

Step 6 produced a working web interface: a candidate can upload a CV, and a recruiter can
review profiles, jobs and matches from a dashboard. That interface assumes the candidate comes
to the system.

For the population this project actually serves — call-centre applicants in Casablanca,
Marrakech and Rabat — that assumption is wrong. They do not browse to a careers portal; they
message. The system was asking people to come to it when it should have been going to them.

This phase adds a **messaging channel**: a candidate sends a photo of their CV to a bot, and
the same extraction, storage and embedding pipeline built in Steps 2, 3 and 5 runs on it —
with no website visit and no application form.

The result is **18 nodes in n8n Cloud, live and active**.

---

## 2. Choosing the channel

The obvious channel is WhatsApp: it is what the target population uses. Four options were
evaluated, and the obvious one was rejected.

| Option | Verdict |
|---|---|
| **Meta WhatsApp Cloud API** | Official, but production access requires **Business Verification** — a registered legal entity with supporting documents. Test mode caps delivery at **5 pre-verified recipients** with a **24-hour token**. |
| **OpenWA** | A reverse-engineered WhatsApp Web client. Its own README states that for regulated environments it should be treated as **not approved**. |
| **Whapi.cloud** | Same category, hosted. Free tier is **5 conversations/month**; **$29/month** thereafter. |
| **Telegram** ✅ | Official Bot API, free, no business verification, **permanent token**, and anyone may message the bot. |

Telegram won on three grounds simultaneously:

1. **Compliance.** It is an official, documented API used as intended — unlike the two
   reverse-engineered libraries, whose own documentation warns against this exact use.
2. **Cost.** Free, with no per-conversation billing.
3. **Demonstrability.** Anyone in a defence room can message the bot from their own phone and
   watch the pipeline run. WhatsApp's test mode would have required pre-registering the jury's
   telephone numbers in advance.

### 2.1 The consistency of the constraint

This is the same decision made in Step 4, applied to a different vendor. There, a job board was
not scraped because its `robots.txt` forbade it, and an official API was used instead. Here,
two WhatsApp libraries were declined because their terms and their own documentation forbade
this use, and an official API was used instead.

*A principle applied twice under real cost is a stance; applied once, it is a coincidence.* In
both cases the compliant route was also the more restrictive one, and was taken anyway.

### 2.2 The WhatsApp workflow still exists

A WhatsApp version of the workflow was built during this evaluation, wired to the
Meta Cloud API and reaching the same Supabase tables. It was not deployed, and it has since
been **removed from the repository** rather than kept as inert code — once Telegram was chosen
as the production channel, carrying an unused integration alongside it would have been clutter,
not evidence of thoroughness. What it lacked was credentials, not code: given a verified
business account, the same architecture described in this chapter would run against WhatsApp
with the trigger and send nodes swapped and nothing else changed. That portability is the
practical payoff of building the CV branch around a vision model and managed services rather
than around any one platform's API.

---

## 3. The architecture change: the hosting requirement disappeared

The original design had n8n call the FastAPI application built in Steps 2–6. That would have
required the application to be **publicly reachable**: a VPS, a domain, TLS certificates, and
an uptime obligation for a student project.

Introducing a **vision model** removed the requirement entirely. Instead of

```
image → Tesseract OCR → text → LLM → structured JSON
```

the workflow performs

```
image → vision model → structured JSON        (one call)
```

There is no OCR binary, so nothing has to run on a machine under the author's control:

```
Telegram → n8n Cloud → vision model (OpenRouter) → Supabase
                     → HuggingFace Inference API → vector
```

Every component is a managed service. **The hosting problem was dissolved rather than solved** —
the better outcome, and one that only became available because the extraction step was
re-examined rather than ported.

---

## 4. What the 18 nodes do

The workflow branches immediately after the Telegram trigger, on whether the incoming message
carries a file.

### 4.1 Text branch

A plain message is passed to an LLM assistant under an explicitly constrained prompt: reply in
**French**, in **at most three sentences**, and **never invent salaries, timelines or promises
of employment**. The reply is sent back through Telegram.

The constraint matters. An unconstrained assistant speaking on behalf of a recruitment agency
can fabricate an offer; the prompt forbids the categories of statement that would create an
expectation the agency has not made.

### 4.2 CV branch

| # | Node | Purpose |
|---|---|---|
| 1 | **Download file** | Retrieve the document or photo from Telegram's file API |
| 2 | **Format guard** | Accept `image/*` or `application/pdf`; anything else receives a polite refusal |
| 3 | **Encoder en base64** | Resolve n8n Cloud's binary storage and build the OpenRouter payload |
| 4 | **Vision extraction** | Read the CV directly into structured JSON |
| 5 | **Normaliser le profil** | Parse, validate, and attach provenance |
| 6 | **Supabase insert** | Upsert on `email` |
| 7 | **Reply** | Confirm to the candidate which fields were detected |
| 8 | **Texte pour embedding** | Compose the candidate text (same field selection as Step 5) |
| 9 | **HuggingFace** | Produce a 384-dimensional vector |
| 10 | **Normalise** | L2-normalise and validate the vector |
| 11 | **PATCH** | Write the vector to the candidate row |

The upsert on `email` is the same deduplication key used by the Python ingestion path, so a
candidate who applies through the website and again through Telegram produces **one row**, not
two.

---

## 5. Three platform problems worth documenting

These are the parts of the phase that required diagnosis rather than assembly.

### 5.1 n8n Cloud stores binaries on disk

On n8n Cloud, file data is written to the filesystem rather than held in the item. Reading
`$binary.data.data` therefore returns the **pointer string** `filesystem-v2` — not the file
contents. The vision call would have been sent a short identifier where an image was expected,
and would have returned confident nonsense.

The correct access path is the helper:

```js
const buffer = await this.helpers.getBinaryDataBuffer(i, 'data');
```

This defect would have been invisible in the version originally written, and would not have
produced an error — only wrong output. It is a good illustration of why the pipeline was tested
against real files rather than assumed correct.

### 5.2 PDFs and images take different paths

A CV arrives as either a phone photo or a PDF export, and the two cannot be sent identically:

- **Images** are sent as `image_url` content parts.
- **PDFs** are routed through OpenRouter's **file-parser plugin**.

Handling only images would have silently rejected the more professional half of the incoming
CVs.

### 5.3 Vector-space compatibility with the Python backfill

The vector produced here must land in the **same space** as every vector written by the Python
pipeline in Step 5 — otherwise cosine similarity between a Telegram candidate and an existing
job is meaningless.

`embeddings.py` calls `encode(..., normalize_embeddings=True)`. The question was whether the
HuggingFace Inference API does the same. It does not: the
`paraphrase-multilingual-MiniLM-L12-v2` repository has **no `Normalize` module** in its
`sentence-transformers` configuration, so the API returns **raw mean-pooled vectors**. The
workflow therefore normalises explicitly:

```js
// embeddings.py calls encode(..., normalize_embeddings=True), but
// paraphrase-multilingual-MiniLM-L12-v2 has no Normalize module in its
// sentence-transformers config, so the HF API returns raw mean-pooled vectors.
const norm = Math.sqrt(v.reduce((s, x) => s + x * x, 0));
```

with guards on **length (`!== 384`)**, **type**, and **HuggingFace error responses**. Each
guard returns `[]`, which stops the chain cleanly and leaves `embedding` null — a state the
**Python backfill already knows how to repair** on its next run.

That is a deliberate **reconciler pattern**: the JavaScript path is allowed to fail, because a
second independent process converges the data to the correct state. It is the right answer to a
duplicated-logic risk that cannot be fully eliminated, since the two paths are written in
different languages against different runtimes.

### 5.4 Provenance carries across languages

The provenance principle from Step 2 reappears here, in JavaScript, in a different system:

```js
source_method: 'telegram/vision',
```

and where a field cannot be read reliably:

```js
warnings.push('email_non_lisible');
```

A row therefore states **how it was produced** and **what was uncertain about it**, exactly as
OCR-derived rows do in the Python pipeline.

---

## 6. Results

The path was validated end to end with two real candidates who entered the system **only**
through Telegram:

| Candidate | Profile complete | Vector written |
|---|---|---|
| Jan de Vries | ✅ | ✅ |
| Sophie van den Berg | ✅ | ✅ |

Jan de Vries was then matched against three Dutch-language roles and scored **95 / 55 / 20** —
a wide, discriminating spread rather than three similar numbers.

The complete chain, with no server under the author's control:

```
Telegram → vision extraction → Supabase → embedding → explained match
```

A candidate photographs their CV and, without filling in a single form, becomes a ranked,
explained match against live openings.

---

## 7. Defects outstanding

Two defects are known, diagnosed, and **not yet fixed**. They are recorded here rather than
omitted.

### 7.1 The `candidates` table has no row-level security

Supabase's publishable key currently reads **every name, email and telephone number** in the
table. This is the most serious open issue in the system, and it concerns exactly the data
Step 5 was careful to keep out of the embedding model.

**The fix order matters.** The n8n workflow authenticates with the publishable key. Enabling RLS
first would break inserts, and the bot would stop saving CVs while still appearing to succeed
(see §7.2). The correct sequence is:

1. Issue a service-role key to n8n and swap the credential.
2. Verify that an insert still succeeds.
3. Enable RLS on `candidates` and add policies.

### 7.2 The bot reports success it has not verified

Both Supabase nodes are configured with `neverError: true`. A failed insert therefore continues
down the success path, and the candidate receives:

> ✅ Votre CV a bien été analysé

for a record that was never stored. The error handling built in this phase covers **vision
failures** — unreadable images, unsupported formats, model errors — but not **storage
failures**.

The fix is an `IF` node testing for the presence of an `id` in the Supabase response, routing
the negative branch to an honest failure message. This is the same class of defect as §9.4 in
Step 5: a silent wrong result is more dangerous than a crash, because nothing signals that
anything went wrong.

---

## 8. Limitations

- **No conversation memory.** Each message is handled independently. A candidate replying
  *"oui, niveau B2"* to the bot's own question is not understood as a reply, because the
  workflow holds no prior turn. Sessions would require storing conversation state keyed by chat
  ID.
- **No recruiter notification.** When a CV arrives, nobody is told. A recruiter has to open the
  dashboard and notice. A Telegram or email notification node would close this in one step.
- **`jobs/expire.py` has never fired.** The expiry logic written in Step 4 is correct but
  untriggered — no posting in the corpus is yet 7 days stale. It is therefore **unproven in
  production**, which is a weaker claim than "working".
- **`/api/tasks/collect` is unused.** Scheduled job collection was built but never wired to a
  scheduler, so collection remains a **manual button** in the admin interface. This phase
  automated candidate intake, but not job intake.
- **The original file is not yet kept for Telegram candidates.** Step 6 was extended to store
  the uploaded document itself (not only its extracted text) for the website and the earlier
  WhatsApp path, in a private Storage bucket with signed-URL access. The Telegram workflow
  already holds the file in memory as part of the vision call, so extending it is one additional
  HTTP node rather than new architecture — but it had not been done at the time of writing.

---

## 9. Conclusion

This phase changed how candidates reach the system rather than what the system does with them.
The extraction, storage, embedding and matching logic is unchanged; only the front door moved.

Three things distinguish the phase:

1. **A channel chosen against convenience.** WhatsApp was the natural fit and was rejected on
   the terms of its own documentation, consistent with the `robots.txt` decision in Step 4.
2. **An architecture that removed its own hosting requirement.** Replacing OCR-plus-LLM with a
   single vision call eliminated the need for a publicly reachable server.
3. **Two platform-mechanics problems solved with evidence** — n8n Cloud's on-disk binary
   storage, and the absence of a `Normalize` module in the embedding model's configuration —
   neither of which could have been resolved by reading the workflow code alone.

The duplication of embedding logic across Python and JavaScript is a real risk, mitigated but
not removed by the reconciler pattern in §5.3. And the system currently makes a claim it does
not verify (§7.2) over data it does not protect (§7.1). Both have specified fixes, in the
correct order, and both are stated here rather than left for a reader to discover.
