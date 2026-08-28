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