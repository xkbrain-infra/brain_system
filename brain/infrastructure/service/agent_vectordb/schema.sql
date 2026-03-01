-- Brain Docs Database Schema (backup DDL)
-- PostgreSQL 16 + pgvector 0.8.0

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,          -- spec, wf, knlg, evo
    scope TEXT NOT NULL DEFAULT 'G',
    category TEXT NOT NULL,        -- CORE, POLICY, STANDARD, TEMPLATE, ...
    title TEXT NOT NULL,
    description TEXT,
    path TEXT NOT NULL,
    content_hash TEXT,             -- SHA256 of file content
    last_modified DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_tags ( 
    id SERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    UNIQUE(doc_id, tag)
);

CREATE TABLE IF NOT EXISTS document_keywords (
    id SERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    UNIQUE(doc_id, keyword)
);

CREATE TABLE IF NOT EXISTS document_vectors (
    id SERIAL PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE UNIQUE,
    embedding vector(1024) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_domain ON documents(domain);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
CREATE INDEX IF NOT EXISTS idx_document_tags_tag ON document_tags(tag);
CREATE INDEX IF NOT EXISTS idx_document_keywords_keyword ON document_keywords(keyword);

-- HNSW index for cosine similarity search
CREATE INDEX IF NOT EXISTS idx_document_vectors_embedding
    ON document_vectors USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Full-text view
CREATE OR REPLACE VIEW document_full_view AS
SELECT
    d.id, d.domain, d.scope, d.category, d.title, d.description, d.path,
    d.content_hash, d.last_modified, d.created_at, d.updated_at,
    COALESCE(array_agg(DISTINCT t.tag) FILTER (WHERE t.tag IS NOT NULL), '{}') AS tags,
    COALESCE(array_agg(DISTINCT k.keyword) FILTER (WHERE k.keyword IS NOT NULL), '{}') AS keywords
FROM documents d
LEFT JOIN document_tags t ON d.id = t.doc_id
LEFT JOIN document_keywords k ON d.id = k.doc_id
GROUP BY d.id;
