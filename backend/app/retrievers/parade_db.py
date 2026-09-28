from typing import Any, List
from sqlalchemy import text

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever


class ParadeDBBM25Retriever(BaseRetriever):
    """LangChain retriever wrapping ParadeDB BM25 search."""

    def __init__(
        self,
        db_session_factory: Any,
        tenant_id: str,
        k: int = 50,
        document_ids: List[str] | None = None,
    ):
        super().__init__()
        self._db_session_factory = db_session_factory
        self._tenant_id = tenant_id
        self._k = k
        self._document_ids = document_ids

    def _build_where_clause(self, document_ids: List[str] | None) -> tuple[str, dict]:
        if document_ids:
            return (
                "AND document_id = ANY(:document_ids)",
                {"document_ids": document_ids},
            )
        return ("", {})

    async def _aget_relevant_documents(self, query: str) -> List[Document]:
        where_clause, extra_params = self._build_where_clause(self._document_ids)
        base_params: dict[str, Any] = {
            "tenant_id": self._tenant_id,
            **extra_params,
        }

        bm25_sql = text(f"""
            SELECT id, content, metadata, pdb.score(id) AS bm25_score
            FROM chunks
            WHERE content ||| :question
              AND tenant_id = :tenant_id
              {where_clause}
            ORDER BY bm25_score DESC
            LIMIT :k
        """)
        bm25_params = {**base_params, "question": query, "k": self._k}

        async with self._db_session_factory() as db:
            result = await db.execute(bm25_sql, bm25_params)
            rows = result.fetchall()

        docs = []
        for row in rows:
            chunk_id, content, metadata, bm25_score = row
            metadata = metadata or {}
            metadata["bm25_score"] = float(bm25_score or 0.0)
            metadata["retriever"] = "bm25"
            metadata["chunk_id"] = str(chunk_id)
            docs.append(Document(page_content=content, metadata=metadata))

        return docs

    def _get_relevant_documents(self, query: str) -> List[Document]:
        import asyncio
        return asyncio.run(self._aget_relevant_documents(query))