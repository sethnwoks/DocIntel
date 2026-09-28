from typing import Any, List
from sqlalchemy import text

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_openai import OpenAIEmbeddings


class PGVectorRetriever(BaseRetriever):
    """LangChain retriever wrapping pgvector similarity search."""

    def __init__(
        self,
        db_session_factory: Any,
        tenant_id: str,
        k: int = 50,
        document_ids: List[str] | None = None,
        embedding_model: str = "text-embedding-3-small",
    ):
        super().__init__()
        self._db_session_factory = db_session_factory
        self._tenant_id = tenant_id
        self._k = k
        self._document_ids = document_ids
        self._embeddings = OpenAIEmbeddings(model=embedding_model)

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

        # Get query embedding
        query_embedding = await self._embeddings.aembed_query(query)

        vector_sql = text(f"""
            SELECT id, content, metadata, embedding <-> :embedding AS distance
            FROM chunks
            WHERE tenant_id = :tenant_id
              {where_clause}
            ORDER BY embedding <-> :embedding
            LIMIT :k
        """)
        vector_params = {**base_params, "embedding": str(query_embedding), "k": self._k}

        async with self._db_session_factory() as db:
            result = await db.execute(vector_sql, vector_params)
            rows = result.fetchall()

        docs = []
        for row in rows:
            chunk_id, content, metadata, distance = row
            metadata = metadata or {}
            # Convert distance to similarity (1 - normalized distance)
            metadata["vector_distance"] = float(distance or 0.0)
            metadata["retriever"] = "vector"
            metadata["chunk_id"] = str(chunk_id)
            docs.append(Document(page_content=content, metadata=metadata))

        return docs

    def _get_relevant_documents(self, query: str) -> List[Document]:
        import asyncio
        return asyncio.run(self._aget_relevant_documents(query))