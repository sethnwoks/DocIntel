import os
from typing import Optional
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough
from langchain_openai import ChatOpenAI
from langchain_classic.retrievers import EnsembleRetriever
from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever

from app.retrievers.parade_db import ParadeDBBM25Retriever
from app.retrievers.pgvector import PGVectorRetriever
from app.retrievers.reranker import BGERerankerCompressor


SYSTEM_PROMPT = """You are a precise document-based Q&A assistant. Answer ONLY using the provided context chunks below. Do NOT use any outside knowledge.

RULES:
1. If the answer is not found in the context, say "I don't know" — do not guess or infer.
2. If the question asks to compare entities, find information about EACH entity in the context and compare them side by side. If an entity has no information in the context, say so explicitly.
3. If the question asks about a specific entity (e.g., "who is Seth?"), search ALL chunks for mentions of that entity and provide the relevant details.
4. Cite your sources using [Source N] references.
5. Be concise and factual. Do not add opinions.
6. If multiple chunks contain relevant info, synthesize them into a coherent answer.

Context:
{context}"""


def format_docs(docs: list[Document]) -> str:
    """Format documents for context injection."""
    context_parts = []
    for i, doc in enumerate(docs):
        metadata = doc.metadata or {}
        filename = metadata.get("filename", "unknown")
        chunk_index = metadata.get("chunk_index", 0)
        doc_id = metadata.get("document_id", "unknown")
        content = doc.page_content

        tag = metadata.get("retriever", "UNKNOWN").upper()
        if "rerank_score" in metadata:
            tag += " + RERANK"
            similarity = round(metadata["rerank_score"], 4)
        else:
            similarity = round(metadata.get("bm25_score", metadata.get("vector_distance", 0.0)), 4)
        
        context_parts.append(f"[Source {i+1}] ({tag}) {content}")
    
    return "\n\n---\n\n".join(context_parts)


def build_rag_chain(
    tenant_id: str,
    db_session_factory: async_sessionmaker[AsyncSession],
    k: int = 50,
    rerank_top_n: int = 7,
    document_ids: Optional[list[str]] = None,
) -> Runnable:
    """Build the RAG chain with hybrid retrieval + reranking."""
    
    # Individual retrievers
    bm25_retriever = ParadeDBBM25Retriever(
        db_session_factory=db_session_factory,
        tenant_id=tenant_id,
        k=k,
        document_ids=document_ids,
    )
    
    vector_retriever = PGVectorRetriever(
        db_session_factory=db_session_factory,
        tenant_id=tenant_id,
        k=k,
        document_ids=document_ids,
    )
    
    # Hybrid retriever with weighted fusion (matches current 0.4/0.6)
    # id_key="chunk_id" tells EnsembleRetriever to key on the chunk UUID that
    # both retrievers stamp, instead of its default of page_content. Same
    # content text in two different chunks would otherwise be fused as one.
    hybrid_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[0.4, 0.6],
        id_key="chunk_id",
    )
    
    # Reranker compressor
    reranker = BGERerankerCompressor(
        batch_size=8,
        top_n=rerank_top_n,
    )
    
    # Compression retriever (hybrid -> rerank)
    compression_retriever = ContextualCompressionRetriever(
        base_compressor=reranker,
        base_retriever=hybrid_retriever,
    )
    
    # Prompt template.
    # SYSTEM_PROMPT already ends with "Context:\n{context}". Appending
    # another "Context:\n{context}" here rendered the chunks TWICE, and
    # gpt-4o-mini answers "I don't know." to the doubled prompt even when the
    # answer is verbatim in it. Only the question is appended.
    prompt = ChatPromptTemplate.from_template(
        SYSTEM_PROMPT + "\n\nQuestion: {question}"
    )
    
    # LLM.
    # Model is env-configurable because gpt-4o-mini is not usable here: it
    # answers "I don't know." to every question, including ones where the
    # answer is verbatim in the context. Measured 8/8 refusals at temperature 0
    # on "what promotion did Seth get", with the promotion letter sitting in
    # the prompt. gpt-4o answered 7/8 on the identical input. RAG_LLM_MODEL
    # exists so the cost/latency trade is a .env edit, not a code change.
    llm = ChatOpenAI(
        model=os.getenv("RAG_LLM_MODEL", "gpt-4o"),
        temperature=0.1,
        max_tokens=1000,
    )
    
    # Chain: retrieve -> format -> prompt -> llm -> parse
    #
    # RunnableDict passes the ENTIRE input to each value, so the retriever was
    # receiving {"question": "..."} rather than the question string. BM25 then
    # bound that dict to its :question parameter and asyncpg rejected it:
    # "invalid input for query argument $1 ... (expected str, got dict)".
    # Every /query call raised before reaching the LLM. The lambda pulls the
    # question out first so the retriever gets a str.
    chain = (
        {
            "context": RunnableLambda(lambda x: x["question"])
            | compression_retriever
            | format_docs,
            "question": RunnablePassthrough(),
        }
        | prompt
        | llm
        | StrOutputParser()
    )
    
    return chain


def get_rag_chain(
    tenant_id: str,
    db_session_factory: async_sessionmaker[AsyncSession],
    k: int = 50,
    rerank_top_n: int = 7,
    document_ids: Optional[list[str]] = None,
) -> Runnable:
    """Get or create the RAG chain (can be cached at app startup)."""
    return build_rag_chain(
        tenant_id=tenant_id,
        db_session_factory=db_session_factory,
        k=k,
        rerank_top_n=rerank_top_n,
        document_ids=document_ids,
    )