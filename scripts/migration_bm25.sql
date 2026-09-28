-- Migration: Switch from PostgreSQL FTS to ParadeDB true BM25
-- Drops tsvector/GIN artifacts, creates ParadeDB BM25 index

-- 1. Remove PostgreSQL FTS artifacts (if they exist)
ALTER TABLE chunks DROP COLUMN IF EXISTS content_tsv;
DROP INDEX IF EXISTS idx_chunks_content_tsv;

-- 2. Drop existing ParadeDB BM25 index if present (idempotent)
DROP INDEX IF EXISTS idx_chunks_bm25;

-- 3. Create true BM25 index via ParadeDB pg_search
-- key_field='id' is mandatory: must be first column and have UNIQUE constraint
CREATE INDEX idx_chunks_bm25 ON chunks USING bm25 (id, content) WITH (key_field = 'id');

-- 4. Verify
SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'pg_search');
