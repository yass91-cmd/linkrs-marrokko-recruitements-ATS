# Step 6 — The Web Application: Interfaces, Authentication and Authorization

## 1. Objective

The preceding five steps produced a working pipeline: a CV goes in, a structured
profile comes out, jobs are collected and scored, and explained matches are
persisted. Every one of those steps ran from a terminal.

A recruitment agency does not operate from a terminal. Step 6 turns the pipeline
into a system that two distinct groups of people can actually use:

- **candidates**, who submit a CV and want to know what happened to it;
- **recruiters**, who need to review profiles, enrich job data from phone calls,
  and move people through a hiring pipeline.

These two audiences have opposing requirements. Candidates must reach the system
with no barrier and see only their own data. Recruiters need dense information
across all candidates — which is precisely the data that must never leak. This
chapter is therefore as much about **access control** as about interface design,
and it documents two genuine security defects found and fixed during development.

## 2. Choosing the framework

The first prototype used **Streamlit**, which is excellent for what it is: a way
to put an interface on a Python script in twenty lines. It was the right tool
while the pipeline was still being explored.

It stopped being the right tool once the deliverable became a product. Streamlit
imposes constraints that a recruitment platform cannot accept:

| Requirement | Streamlit |
|---|---|
| Distinct public and private areas | No routing; one app, one entry point |
| Session-based authentication | Not part of the model |
| Control over presentation | Constrained to its own component styling |
| Meaningful URLs (`/admin/candidates/7`) | Not addressable |

The application was rebuilt on **FastAPI** with **Jinja2** server-side templates.
FastAPI was already a dependency, it provides real routing and dependency
injection, and Jinja2 renders complete HTML pages — which for a data-display
application is simpler and faster than a JavaScript front-end consuming an API.
No client-side framework was introduced, because none was needed: there is no
client-side state to manage.

This is the recurring principle from Step 4, applied to interface design: choose
the tool that fits the constraint, not the tool that is fashionable.

## 3. Architecture: two audiences, one application

The application is organised into four routers, separated by audience and by
authentication requirement.

| Router | Prefix | Audience | Protection |
|---|---|---|---|
| `api/main.py` | `/` | Candidates | Session-scoped ownership |
| `api/candidate_auth.py` | `/auth/*`, `/me` | Candidates | Google OAuth |
| `api/admin.py` | `/admin/*` | Recruiters | Password + session |
| `api/tasks.py` | `/api/tasks/*` | Machines | Shared token |

The fourth router deserves note: it is authenticated by a **token in a header**,
not a session cookie. Sessions are a browser mechanism designed for human users;
an automation platform calling an endpoint on a schedule is not a browser. Using
the wrong mechanism would have meant either weakening the session system or
storing cookies in a workflow tool. Different callers get different credentials.

Fifteen templates render these routes, built on two layouts: `base.html` for the
public site and `admin/_base_admin.html` for the recruiter workspace. The
relationship between them is discussed in §8.

## 4. The candidate journey

The candidate-facing flow is four screens, deliberately short.

**Landing page.** States what the service does — matching Moroccan candidates to
Dutch-language roles — and offers a single action. An earlier version presented
two competing buttons ("upload" and "sign in"); this was reduced to one, because
a landing page with two primary actions has no primary action.

**Sign-in, then upload.** Uploading requires a Google account. This is not
friction for its own sake: it solves an identity problem documented in Step 2.
OCR misread the character `1` as `l` in an email address, producing
`boudrigayasserl@gmail.com` instead of `boudrigayasser1@gmail.com` — a plausible
address that passed format validation and created a duplicate profile. A
Google-verified email cannot be misread. Requiring sign-in replaces an unreliable
identifier extracted from a document with an authoritative one from an identity
provider:

```python
# The Google-verified email is authoritative — it replaces whatever was
# read from the document, which OCR can corrupt (the l/1 problem).
candidate.email = verified_email
candidate.warnings = [w for w in candidate.warnings if "mail" not in w.lower()]
```

Because `save_candidate` upserts on email, a candidate who uploads a revised CV
updates their existing profile instead of creating a second one.

**Review and correction.** The extracted profile is shown in a fully editable
form — every field, including repeating education and experience entries. This is
a direct consequence of the provenance principle from Step 2. The system records
that a value came from OCR and may be wrong; the logical next step is to let the
person who knows the truth correct it. Automated extraction is treated as a draft
for human confirmation, not as an authority.

Corrections trigger re-embedding. A profile whose text has changed but whose
vector has not would be matched on data the candidate has already rejected:

```python
# The profile text changed, so the embedding must be recomputed —
# otherwise matching would still use the uncorrected data.
_embed_candidate(candidate_id, row)
```

**Personal space (`/me`).** A signed-in candidate sees their profile and the
positions proposed to them. The query filters deliberately:

```sql
WHERE m.candidate_id = %s AND m.eligible = true
  AND m.status IN ('presented','approved','applied','hired')
```

Candidates do not see `suggested` matches, nor the numeric scores. What the
system computes internally and what a candidate should be shown are different
things: a raw score of 34/100 is a useful signal for a recruiter and a
demoralising message for a person.

## 5. The recruiter workspace

The admin area comprises seven screens serving the workflow defined at the start
of the project: *scrape → HR confirms → candidate matched → candidate approves →
company applies → result recorded*.

**Dashboard.** Counts, a funnel by match status, top-scoring pairs, recent
arrivals.

**Candidates.** The list plus the semantic search from Step 5, so a recruiter can
type *"néerlandophone avec expérience centre d'appel à Casablanca"* and retrieve
profiles by meaning rather than keyword. Each row shows its `source_method`
(`native`, `ocr`, `telegram/vision`) — provenance surfaced in
the interface, so a recruiter knows how much to trust what they are reading.

**Candidate detail.** The full profile, extraction warnings, and every match with
its strengths, gaps and French summary from the reranker. A dropdown advances the
workflow status.

**Jobs.** Filter chips reflecting recruiter tasks rather than database fields:
*À appeler*, *Nouvelles*, *Sans candidats*, *Vérifiées*, *Actives*, *Toutes*. A
collection button runs the multi-query collector from Step 4 and reports what it
found.

**Job detail.** A two-column layout that keeps two kinds of knowledge separate:
scraped data on the left, an HR enrichment form on the right. A salary read from
a posting and a salary confirmed by telephone are not the same fact, and they are
stored in different columns (`details.salary` versus `hr_salary`). This is the
provenance principle again, applied to job data.

**Pipeline.** A board with one column per workflow stage, giving a view of every
active placement.

**Deletion.** Both jobs and candidates can be permanently removed. Candidate
deletion is not a convenience but a legal requirement — GDPR Article 17 — and it
must be complete:

```python
"""
GDPR Art. 17 (right to erasure): this must remove ALL personal data, including
raw_text (which holds the full CV) and the embedding (derived from it).
Their matches are removed automatically by ON DELETE CASCADE.
"""
```

The `ON DELETE CASCADE` defined in Step 3 is what makes this erasure rather than
a partial delete. A deletion that leaves the raw CV text, the embedding, or match
rows bearing the person's assessments behind is not erasure. Because embeddings
are derived from personal data, they *are* personal data, and removing them is
part of compliance rather than an optimisation.

## 6. Authentication: two systems for two audiences

The two audiences justified two different mechanisms.

### 6.1 Recruiters: email and password

A shared credential compared against environment variables, with a signed session
cookie. Three details matter more than the mechanism itself:

```python
# Constant-time comparison on BOTH fields: a normal == leaks information
# through timing, and short-circuiting on email would reveal whether it exists.
email_ok = secrets.compare_digest(email.strip().lower(), ADMIN_EMAIL.strip().lower())
password_ok = secrets.compare_digest(password, ADMIN_PASSWORD)
```

**Constant-time comparison.** A normal `==` returns as soon as it finds a
differing character, so response time correlates with how many leading characters
were correct — enough, over many requests, to recover a secret one character at a
time. `secrets.compare_digest` always examines the whole value.

**No short-circuit.** Both comparisons run even when the first fails. An
`if email_ok:` guard would make responses measurably faster for unknown
addresses, revealing which emails exist (*user enumeration*).

**One generic error.** The interface says *"identifiants incorrects"*, never
*"unknown email"*. Telling an attacker which half was correct hands them a
verified address.

The whole admin area is protected by one dependency declared on the router:

```python
router = APIRouter(prefix="/admin", tags=["admin"],
                   dependencies=[Depends(require_admin)])
```

This protects every existing route and every route added later. The alternative —
a check inside each handler — fails the moment someone forgets one, and that
failure is silent.

A related decision concerns the session signing key. The first implementation
fell back to a hardcoded default when the environment variable was absent:

```python
secret_key=os.getenv("SESSION_SECRET", "dev-only-change-me")
```

Since that literal is in the source, and the source is in version control, a
deployment missing the variable would sign sessions with a publicly known key —
allowing anyone to forge an administrator cookie. The application now refuses to
start:

```python
SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET is not set — refusing to start insecurely")
```

A missing secret must stop the application, never silently degrade it. Failing
loudly is safer than failing quietly.

### 6.2 Candidates: Google sign-in via Supabase

Candidates authenticate with Google through Supabase Auth. No passwords are
stored, and the resulting email address is verified by Google.

The implementation required the **PKCE** flow rather than the default. Supabase's
standard OAuth returns the token in the URL *fragment* (`#access_token=...`), and
browsers never transmit fragments to the server — they exist only in the client.
For a server-rendered application this is unusable. PKCE instead returns a
single-use `?code=` in the query string, which the backend exchanges for a
session:

```python
verifier, challenge = _pkce_pair()
request.session["pkce_verifier"] = verifier
url = (f"{SUPABASE_URL}/auth/v1/authorize?provider=google"
       f"&redirect_to={APP_BASE_URL}/auth/callback"
       f"&code_challenge={challenge}&code_challenge_method=s256")
```

The verifier stays in the server session and never travels with the redirect, so
intercepting the code alone is insufficient to complete the exchange.

### 6.3 One identity per session

An early defect: signing in as a recruiter and then as a candidate left both
identities in a single session cookie. The navigation displayed the recruiter's
email on public pages, and — more seriously — a request carried two identities at
once, leaving authorization checks with no single correct answer.

Signing in under either role now clears the other:

```python
# One identity per session: signing in as candidate ends any admin session.
request.session.pop("admin", None)
request.session.pop("email", None)
request.session["candidate_email"] = email.lower()
```

Roles must be mutually exclusive within a session. Otherwise the question *"what
is this user allowed to do?"* is ambiguous, and ambiguity in an authorization
system is a defect regardless of whether it has yet been exploited.

## 7. Debugging case studies

### 7.1 An unprotected update route (IDOR)

The most serious defect found during Step 6 was not a crash. The route accepting
candidate corrections took an identifier from the URL and wrote to that row:

```
POST /candidate/3/update
```

Nothing verified that the requester had any relation to candidate 3. Anyone could
enumerate identifiers and overwrite any profile. This is an **Insecure Direct
Object Reference**, among the most common vulnerability classes in real
applications, and it survived initial review because the code was correct in
every respect except the one that mattered.

The distinction it illustrates is fundamental: **authentication** establishes who
a requester is; **authorization** establishes whether they may act on a specific
object. The application had begun to address the first and had not addressed the
second at all.

The fix records ownership at upload time and enforces it at write time:

```python
# Authorization: only the visitor who owns this profile may edit it.
# Without this check, anyone could overwrite any profile by guessing an id (IDOR).
if request.session.get("own_candidate_id") != candidate_id:
    return templates.TemplateResponse(
        request, "error.html",
        {"message": "Vous n'êtes pas autorisé à modifier ce profil."})
```

### 7.2 A public key protecting private data

Testing whether the Supabase **anon key** could read the candidates table
returned every candidate's name, email and phone number.

The finding is not that a key leaked. It is that **this key is public by design**:
Supabase intends it to be embedded in browser code, and its entire security model
assumes Row-Level Security is enabled. RLS was not enabled. The protection the
architecture depended upon had never been switched on, and nothing in the
application's behaviour indicated its absence.

Before changing anything, it was necessary to establish that enabling RLS would
not break the system. The application connects as `postgres`, which owns the
tables, and table owners bypass RLS unless it is explicitly forced; the automation
platform uses the `service_role` key, which bypasses it by design. Only the anon
key would be affected — and nothing legitimate used it to read data.

```sql
ALTER TABLE public.candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.matches    ENABLE ROW LEVEL SECURITY;
```

Enabled with no policies, this is **default-deny**: access is refused unless a
rule explicitly permits it.

| Accessor | Before | After |
|---|---|---|
| Anon key (public by design) | Full PII on all candidates | No rows returned |
| Application (`postgres`, owner) | Working | Working |
| Automation (`service_role`) | Working | Working |

### 7.3 A framework signature change

Every page returned `500`. The cause was a change in Starlette 1.6: the historic
`TemplateResponse("page.html", {"request": request, ...})` signature was replaced
by `TemplateResponse(request, "page.html", {...})`. Tutorials and much existing
documentation still show the old form.

The lesson concerns dependency versions rather than templates: an application
built from examples written against an earlier release can be uniformly wrong in
a way that resembles a bug in one's own logic.

### 7.4 A duplicated template block

After editing the navigation, every page failed with
`jinja2.exceptions.TemplateSyntaxError: Encountered unknown tag 'elif'`.

The message was misleading — `{% elif %}` is valid Jinja. The real cause was an
edit that merged with the existing markup instead of replacing it, producing a
premature `{% endif %}` followed by an orphaned `{% elif %}`. A second attempt
introduced the same block twice, which Jinja rejects because a block name must be
unique within a template.

Both faults had one source: applying an edit to a file whose current state was
assumed rather than verified.

## 8. Template inheritance and interface separation

A recurring requirement was that the recruiter's identity must never appear on
public pages. The first implementation tested the session inside the shared
layout, which meant the recruiter's email rendered on the landing page whenever
they were signed in.

The correct mechanism is an overridable block. The public layout defines the
default navigation; the admin layout overrides it:

```html
<!-- base.html -->
<nav>{% block nav %} ... candidate navigation ... {% endblock %}</nav>
```

```html
<!-- admin/_base_admin.html -->
{% block nav %}
  <span class="nav-user">{{ request.session.get('email') }}</span>
  <a href="/logout">Déconnexion</a>
{% endblock %}
```

The recruiter identity can now only render inside pages that extend the admin
layout. This is structural rather than conditional: the public site cannot display
it, regardless of session state.

The recruiter entrance is a small link in the site footer. This is presentation,
**not** a security control — `/admin` is protected by its dependency whether or
not anything links to it. Obscurity is never protection; it merely stops a private
entrance from advertising itself.

## 9. Results

The application comprises **15 templates** and **26 routes** across four routers,
and covers the full workflow end to end:

- a candidate signs in, uploads a CV, corrects the extraction and confirms it;
- a recruiter reviews profiles, runs matching in both directions, searches
  semantically, enriches jobs by telephone, and advances the pipeline;
- an automation platform submits CVs and triggers collection through a
  token-authenticated interface.

Access control was verified route by route for an unauthenticated visitor:

| Route | Behaviour |
|---|---|
| `/` | 200 — public landing |
| `/upload` | 303 → Google sign-in |
| `/login` | 200 — recruiter form |
| `/admin` | 307 → `/login` |
| `/me` | 303 → Google sign-in |
| `/auth/logout` | 303 → `/` |

## 10. Limitations

Stated precisely, because naming a gap is more useful than implying its absence.

- **A single shared recruiter account.** No per-user accounts, so there is no
  audit trail of who changed what. Production would require a users table with
  hashed passwords (bcrypt or argon2).
- **No CSRF tokens.** `same_site="lax"` mitigates cross-site requests but does
  not eliminate them.
- **No rate limiting** on the login route; brute force is possible.
- **No HTTPS in development**, so credentials cross the network in clear text
  until deployment behind TLS.
- **Session-scoped ownership.** A candidate returning in a different browser
  cannot edit their profile until they sign in again. Linking profiles to the
  Supabase user identity rather than the session would resolve this.
- **Synchronous processing.** Upload blocks for ten to twenty seconds while
  extraction runs. A loading state was added, but the correct solution is a
  background queue.
- **RLS with no policies** is default-deny, which is safe but blunt. A
  browser-based candidate client would require explicit policies.

## 11. Conclusion and transition

Step 6 turned a pipeline into a system that two different groups of people can
use, with the boundary between them enforced rather than assumed.

The step's most valuable outcome was not an interface but a distinction. Steps 1
to 5 were concerned with correctness: does the system extract the right fields,
retrieve the right jobs, produce a defensible score? Step 6 introduced a second
question that correctness alone cannot answer — *who is allowed to see this?* —
and answering it exposed two real defects: an update route that verified identity
but not ownership, and a database whose protection had never been enabled.

Both were failures of assumption rather than logic. The code did what it was
written to do; what was missing had never been written at all. That is the
characteristic shape of a security defect, and it is why such defects are found by
asking adversarial questions rather than by testing expected behaviour.

Step 7 addresses the remaining gap. The system requires candidates to visit a
website, but a significant part of the target population reaches services through
messaging applications instead. The next step extends intake to a conversational
channel, which raises its own questions about platform constraints, terms of
service, and where processing should occur.
