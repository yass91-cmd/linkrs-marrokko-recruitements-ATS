-- Enable pgvector for semantic matching (Step 4)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS candidates (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             text,
    title            text,
    email            text,
    phone            text,
    location         text,
    skills           jsonb DEFAULT '[]'::jsonb,
    languages        jsonb DEFAULT '[]'::jsonb,
    education        jsonb DEFAULT '[]'::jsonb,
    experience       jsonb DEFAULT '[]'::jsonb,
    projects         jsonb DEFAULT '[]'::jsonb,
    years_experience real,
    summary          text,
    warnings         jsonb DEFAULT '[]'::jsonb,
    source_method    text,
    raw_text         text,
    embedding        vector(384),
    created_at       timestamptz DEFAULT now()
);


CREATE TABLE IF NOT EXISTS jobs (
    -- identity
    job_uid          text PRIMARY KEY,          -- stable identifier
    job_id           text,                      -- volatile; kept for reference only
    
    -- job facts (from the API)
    title            text,
    employer         text,
    city             text,
    is_remote        boolean,
    apply_link       text,
    description      text,
    details          jsonb,

    -- HR enrichment (workflow step 2)
    hr_verified      boolean NOT NULL DEFAULT false,
    hr_salary        text,
    hr_notes         text,

    -- your own internal note
    note             text,

    -- lifecycle
    status           text NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'filled', 'expired', 'closed')),

    -- AI (Step 4 matching)
    embedding        vector(384),

    -- audit
    last_seen_at     timestamptz DEFAULT now(),
    created_at       timestamptz DEFAULT now()
);