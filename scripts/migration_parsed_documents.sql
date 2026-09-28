-- Migration: Add parsed_documents audit table
-- Run: docker exec -i rag_postgres psql -U postgres -d rag_db < scripts/migration_parsed_documents.sql

CREATE TABLE IF NOT EXISTS parsed_documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    docling_json JSONB NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parsed_documents_doc ON parsed_documents(document_id);
CREATE INDEX IF NOT EXISTS idx_parsed_documents_tenant ON parsed_documents(tenant_id);
