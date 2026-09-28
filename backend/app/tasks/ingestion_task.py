import hashlib
import json
import logging
import os

from openai import OpenAI
from app.db.session import get_connection
from app.tasks.celery_app import celery_app
try:
    import pymupdf4llm
except ImportError:
    pymupdf4llm = None
try:
    from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
except ImportError:
    MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter = None, None


logger = logging.getLogger(__name__)

# Chunk configuration — 1500 chars (~375 tokens) with 200 char overlap (~50 tokens)
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200


def _chunk_text(text: str) -> list[str]:
    """Simple fixed-size character chunker with overlap."""
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start : start + CHUNK_SIZE].strip())
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if c]


def _compute_chunk_hash(chunk_content: str) -> str:
    """Compute SHA-256 hash of chunk content."""
    return hashlib.sha256(chunk_content.encode('utf-8')).hexdigest()


@celery_app.task(
    name="app.tasks.ingestion_task.process_document_task",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def process_document_task(self, document_id: str, tenant_id: str):
    conn = get_connection()
    cur = conn.cursor()

    try:
        # ── 1. Check if already processed (idempotency guard) ────────────────────
        cur.execute(
            "SELECT status, content_hash FROM documents WHERE id = %s AND tenant_id = %s",
            (document_id, tenant_id),
        )
        doc_row = cur.fetchone()
        if not doc_row:
            raise ValueError(f"Document {document_id} not found for tenant {tenant_id}")
        
        # If already completed, skip processing
        if doc_row['status'] == 'completed':
            logger.info(f"[{document_id}] Already completed for tenant {tenant_id}, skipping")
            return {
                "document_id": document_id,
                "status": "already_completed",
                "chunks_stored": 0,
            }
        
        # If failed from a previous attempt, reset and retry
        if doc_row['status'] == 'failed':
            logger.warning(f"[{document_id}] Previously failed for tenant {tenant_id}, resetting to pending and retrying")
            cur.execute(
                "UPDATE documents SET status = 'pending' WHERE id = %s", (document_id,)
            )
            conn.commit()

        # If currently processing, another worker has it - skip to avoid conflict
        if doc_row['status'] == 'processing':
            logger.info(f"[{document_id}] Currently being processed by another worker for tenant {tenant_id}, skipping")
            return {
                "document_id": document_id,
                "status": "already_processing",
                "chunks_stored": 0,
            }

        # ── 2. Fetch storage path and compute/update document hash if needed ─────
        storage_path = doc_row.get('storage_path')  # Will be None if we only selected status/hash
        if not storage_path:
            # Need to get full document details
            cur.execute(
                "SELECT storage_path, filename, created_at FROM documents WHERE id = %s",
                (document_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Document {document_id} not found in DB")
            storage_path = row['storage_path']
            filename = row['filename']
            doc_created_at = row['created_at']
            doc_created_at_iso = doc_created_at.isoformat() if doc_created_at else None
        else:
            # We have storage_path from the first query, need filename and created_at
            cur.execute(
                "SELECT filename, created_at FROM documents WHERE id = %s",
                (document_id,),
            )
            row = cur.fetchone()
            filename = row['filename']
            doc_created_at = row['created_at']
            doc_created_at_iso = doc_created_at.isoformat() if doc_created_at else None

        # Update document content_hash if not already set (should be set by upload.py, but just in case)
        if not doc_row['content_hash']:
            # Compute hash from stored file
            file_hash = None
            try:
                with open(storage_path, 'rb') as f:
                    file_hash = hashlib.sha256()
                    for chunk in iter(lambda: f.read(4096), b""):
                        file_hash.update(chunk)
                    file_hash = file_hash.hexdigest()
                
                # Update document with computed hash
                cur.execute(
                    "UPDATE documents SET content_hash = %s WHERE id = %s",
                    (file_hash, document_id),
                )
                conn.commit()
                logger.info(f"[{document_id}] Computed and stored content hash: {file_hash}")
            except Exception as hash_error:
                logger.warning(f"[{document_id}] Could not compute file hash: {hash_error}")
                # Continue without hash - not critical for chunk deduplication

        # ── 3. Mark as processing ──────────────────────────────────────────────
        cur.execute(
            "UPDATE documents SET status = 'processing' WHERE id = %s", (document_id,)
        )
        conn.commit()
        logger.info(f"[{document_id}] status → processing | path: {storage_path}")

        # ── 4. Parse with PyMuPDF4LLM (fast, lightweight extraction) ───────────
        if pymupdf4llm is None:
            raise EnvironmentError("pymupdf4llm is not installed — cannot parse document")
        logger.info(f"[{document_id}] Running PyMuPDF4LLM converter...")
        full_text = pymupdf4llm.to_markdown(storage_path)
        parsed_json = pymupdf4llm.to_json(storage_path)

        # ── 5. Persist JSON to parsed_documents (audit layer) ──────────────────
        cur.execute(
            """
            INSERT INTO parsed_documents (document_id, tenant_id, docling_json)
            VALUES (%s, %s, %s)
            ON CONFLICT (document_id) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                docling_json = EXCLUDED.docling_json
            """,
            (document_id, tenant_id, json.dumps(parsed_json)),
        )
        conn.commit()
        logger.info(f"[{document_id}] Processed document JSON persisted/updated")

        # ── 6. Chunk the text ──────────────────────────────────────────────────
        if MarkdownHeaderTextSplitter is not None and RecursiveCharacterTextSplitter is not None:
            logger.info(f"[{document_id}] Chunking using MarkdownHeaderTextSplitter + RecursiveCharacterTextSplitter...")
            headers_to_split_on = [
                ("#", "Header 1"),
                ("##", "Header 2"),
                ("###", "Header 3"),
            ]
            markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
            md_splits = markdown_splitter.split_text(full_text)
            
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
            )
            split_docs = text_splitter.split_documents(md_splits)
            chunk_texts = [doc.page_content for doc in split_docs]
            
            chunk_metadatas = []
            for idx, doc in enumerate(split_docs):
                meta = {
                    **doc.metadata,
                    "document_id": document_id,
                    "tenant_id": tenant_id,
                    "filename": filename,
                    "source": filename,
                    "document_created_at": doc_created_at_iso,
                    "chunk_index": idx,
                    "total_chunks": len(split_docs),
                    "parser": "PyMuPDF4LLM"
                }
                chunk_metadatas.append(meta)
        else:
            logger.warning(f"[{document_id}] langchain-text-splitters is not installed. Falling back to simple character chunker.")
            chunks = _chunk_text(full_text)
            chunk_texts = chunks
            chunk_metadatas = [
                {
                    "document_id": document_id,
                    "tenant_id": tenant_id,
                    "filename": filename,
                    "source": filename,
                    "document_created_at": doc_created_at_iso,
                    "chunk_index": idx,
                    "total_chunks": len(chunks),
                    "parser": "PyMuPDF4LLM"
                }
                for idx in range(len(chunks))
            ]

        if not chunk_texts:
            raise ValueError("Ingestion produced no text content from this document")

        # ── 7. Compute hashes for all chunks ───────────────────────────────────
        chunk_hashes = [_compute_chunk_hash(content) for content in chunk_texts]

        # ── 8. Embed chunks via OpenAI ─────────────────────────────────────
        openai_key = os.getenv("OPENAI_API_KEY")
        if not openai_key:
            raise EnvironmentError("OPENAI_API_KEY is not set — cannot embed chunks")

        client = OpenAI(api_key=openai_key)
        logger.info(f"[{document_id}] Embedding {len(chunk_texts)} chunks with text-embedding-3-small...")

        # OpenAI API has a 2048-input batch limit, but we'll keep 128 for consistency
        BATCH = 128
        all_embeddings: list[list[float]] = []
        for i in range(0, len(chunk_texts), BATCH):
            batch = chunk_texts[i : i + BATCH]
            response = client.embeddings.create(input=batch, model="text-embedding-3-small")
            all_embeddings.extend([item.embedding for item in response.data])

        logger.info(f"[{document_id}] Embeddings received: {len(all_embeddings)} vectors")

        # ── 9. Batch insert chunks + embeddings into pgvector with deduplication ─
        inserted_count = 0
        for idx, (chunk_content, meta_dict, embedding, chunk_hash) in enumerate(zip(chunk_texts, chunk_metadatas, all_embeddings, chunk_hashes)):
            try:
                cur.execute(
                    """
                    INSERT INTO chunks (document_id, tenant_id, content, embedding, metadata, content_hash)
                    VALUES (%s, %s, %s, %s::vector, %s::jsonb, %s)
                    ON CONFLICT (document_id, content_hash) DO NOTHING
                    """,
                    (
                        document_id,
                        tenant_id,
                        chunk_content,
                        str(embedding),          # pgvector accepts '[0.1, 0.2, ...]' format
                        json.dumps(meta_dict),
                        chunk_hash,
                    ),
                )
                if cur.rowcount > 0:
                    inserted_count += 1
            except Exception as insert_error:
                logger.warning(f"[{document_id}] Failed to insert chunk {idx}: {insert_error}")
                # Continue with other chunks

        conn.commit()
        logger.info(f"[{document_id}] {inserted_count} new chunks inserted into chunks table (skipped {len(chunk_texts) - inserted_count} duplicates)")

        # ── 10. Mark as completed ───────────────────────────────────────────────
        cur.execute(
            "UPDATE documents SET status = 'completed' WHERE id = %s", (document_id,)
        )
        conn.commit()
        logger.info(f"[{document_id}] status → completed")

        return {
            "document_id": document_id,
            "status": "completed",
            "chunks_stored": inserted_count,
        }

    except Exception as exc:
        # On failure, wipe out any partial data for this document
        logger.error(f"[{document_id}] Ingestion FAILED: {exc}")
        try:
            # Delete any chunks that were partially inserted for this document
            cur.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
            # Delete parsed document record if it exists
            cur.execute("DELETE FROM parsed_documents WHERE document_id = %s", (document_id,))
            # Mark document as failed
            cur.execute(
                "UPDATE documents SET status = 'failed' WHERE id = %s", (document_id,)
            )
            conn.commit()
            logger.info(f"[{document_id}] Wiped partial data and marked as failed")
        except Exception as cleanup_error:
            logger.error(f"[{document_id}] Failed to cleanup after error: {cleanup_error}")
            # Don't raise the cleanup error - we want to report the original error
        
        raise self.retry(exc=exc)

    finally:
        cur.close()
        conn.close()
