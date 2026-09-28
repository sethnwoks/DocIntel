import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.async_session import get_async_db
from app.api.dependencies import get_current_tenant_id, get_current_user_id
from app.chains.rag_chain import get_rag_chain

router = APIRouter(prefix="/query", tags=["query"])
logger = logging.getLogger(__name__)

RERANK_TOP_N = 7
HYBRID_K = 50


class QueryRequest(BaseModel):
    question: str
    document_ids: list[str] | None = None


class SourceReference(BaseModel):
    filename: str
    chunk_index: int
    document_id: str
    similarity: float
    bm25: bool
    reranked: bool = False


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceReference]


# Global chain cache (tenant_id -> chain)
_chain_cache: dict[str, Any] = {}


def get_chain(
    tenant_id: str,
    db_session_factory: async_sessionmaker,
    document_ids: list[str] | None = None,
) -> Any:
    """Get or create cached RAG chain for tenant."""
    cache_key = f"{tenant_id}:{tuple(document_ids) if document_ids else 'all'}"
    if cache_key not in _chain_cache:
        _chain_cache[cache_key] = get_rag_chain(
            tenant_id=tenant_id,
            db_session_factory=db_session_factory,
            k=50,
            rerank_top_n=7,
            document_ids=document_ids,
        )
    return _chain_cache[cache_key]


def _extract_sources(docs: list) -> list[SourceReference]:
    """Extract SourceReference objects from retrieved documents."""
    sources = []
    for i, doc in enumerate(docs):
        metadata = doc.metadata or {}
        filename = metadata.get("filename", "unknown")
        chunk_index = metadata.get("chunk_index", 0)
        doc_id = metadata.get("document_id", "unknown")
        
        retriever = metadata.get("retriever", "unknown")
        reranked = "rerank_score" in metadata
        
        if reranked:
            similarity = round(metadata.get("rerank_score", 0.0), 4)
        elif retriever == "bm25":
            similarity = round(metadata.get("bm25_score", 0.0), 4)
        else:
            similarity = round(metadata.get("vector_distance", 0.0), 4)
        
        sources.append(SourceReference(
            filename=filename,
            chunk_index=chunk_index,
            document_id=doc_id,
            similarity=similarity,
            bm25=(retriever == "bm25"),
            reranked=reranked,
        ))
    return sources


@router.post("/", response_model=QueryResponse)
async def query_rag(
    request: QueryRequest,
    db: AsyncSession = Depends(get_async_db),
    tenant_id: str = Depends(get_current_tenant_id),
    user_id: str = Depends(get_current_user_id),
):
    try:
        # Get session factory for chain (we need the factory, not the session)
        from app.db.async_session import AsyncSessionLocal
        
        # Get chain for this tenant
        chain = get_chain(tenant_id, AsyncSessionLocal, request.document_ids)
        
        # Invoke chain
        answer = await chain.ainvoke({"question": request.question})
        
        # Get retrieved documents from chain for source extraction
        # We need to run the retriever separately to get docs for source extraction
        from app.chains.rag_chain import build_rag_chain
        retrieval_chain = build_rag_chain(
            tenant_id=tenant_id,
            db_session_factory=AsyncSessionLocal,
            k=50,
            rerank_top_n=7,
            document_ids=request.document_ids,
        )
        
        # Extract the retriever part to get docs
        # The chain structure is: {"context": retriever | format_docs, "question": passthrough}
        # We need to access the retriever
        from app.chains.rag_chain import build_rag_chain
        temp_chain = build_rag_chain(
            tenant_id=tenant_id,
            db_session_factory=AsyncSessionLocal,
            k=50,
            rerank_top_n=7,
            document_ids=request.document_ids,
        )
        # Extract retriever from chain (it's the first step)
        retriever = temp_chain.first  # This won't work directly
        
        # Instead, invoke the retriever directly
        from app.retrievers.parade_db import ParadeDBBM25Retriever
        from app.retrievers.pgvector import PGVectorRetriever
        from app.retrievers.reranker import BGERerankerCompressor
        from langchain_classic.retrievers import EnsembleRetriever
        from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever
        from app.db.async_session import AsyncSessionLocal
        
        bm25_retriever = ParadeDBBM25Retriever(
            db_session_factory=AsyncSessionLocal,
            tenant_id=tenant_id,
            k=50,
            document_ids=request.document_ids,
        )
        vector_retriever = PGVectorRetriever(
            db_session_factory=AsyncSessionLocal,
            tenant_id=tenant_id,
            k=50,
            document_ids=request.document_ids,
        )
        hybrid = EnsembleRetriever(retrievers=[bm25_retriever, vector_retriever], weights=[0.4, 0.6])
        reranker = BGERerankerCompressor(batch_size=8, top_n=7)
        compression_retriever = ContextualCompressionRetriever(base_compressor=reranker, base_retriever=hybrid)
        
        retrieved_docs = await compression_retriever.ainvoke(request.question)
        sources = _extract_sources(retrieved_docs)
        
        # Log to audit
        log_sql = text("""
            INSERT INTO audit_logs (tenant_id, user_id, question, answer, chunks_used)
            VALUES (:tenant_id, :user_id, :question, :answer, :chunks_used)
        """)
        await db.execute(
            log_sql,
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "question": request.question,
                "answer": answer,
                "chunks_used": json.dumps([
                    {"document_id": s.document_id, "filename": s.filename, "chunk_index": s.chunk_index, "bm25": s.bm25}
                    for s in sources
                ]),
            },
        )
        await db.commit()

        return QueryResponse(answer=answer, sources=sources)

    except Exception as e:
        logger.error(f"Error processing query: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")