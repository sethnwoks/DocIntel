# DocIntel

A multi-tenant web app for asking questions about your own documents. Upload a document, ask a question, and get an answer with the exact passages it came from. Each organisation sees only its own documents.

<!--
  ┌─────────────────────────────────────────────────────────────┐
  │  VIDEO GOES HERE                                           │
  │                                                             │
  │  Record ~60-90s: log in, show the ingested document in the │
  │  sidebar, select it, ask a question, show the answer with  │
  │  its cited passages.                                       │
  │                                                             │
  │  Then replace this comment with:                            │
  │  <img src="docs/demo.gif" width="700">                      │
  └─────────────────────────────────────────────────────────────┘
-->

## What's inside

- **Hybrid retrieval** — ParadeDB BM25 and pgvector dense search, fused with reciprocal rank fusion
- **Local reranking** — a BGE cross-encoder run through ONNX Runtime, so it works on CPU with no PyTorch in the image
- **Grounded answers** — every reply links the passages it drew on, with per-passage similarity
- **Tenant isolation** — every query is scoped from a signed token, so one organisation's documents are unreachable from another's
- **Async ingestion** — uploads are parsed, chunked and embedded in a Celery worker, not the request
- **Evaluation harness** — 48 golden cases scored with DeepEval, committed with the project

The retrieval model is **280 MB and runs on onnxruntime**. The equivalent LangChain reranker pulls in PyTorch and a 2 GB dependency for the same job.

## Quick start

Requires Docker and Docker Compose. Nothing else — no Python, Node, or database install.

```bash
git clone https://github.com/sethnwoks/DocIntel.git
cd DocIntel

cp .env.example .env
echo "JWT_SECRET_KEY=$(openssl rand -hex 32)" >> .env
# add your OpenAI key to .env

docker compose up -d postgres
```

Create the schema:

```bash
docker exec -i rag_postgres psql -U postgres -d rag_db < scripts/schema.sql
docker exec -i rag_postgres psql -U postgres -d rag_db < scripts/migration_parsed_documents.sql
docker exec -i rag_postgres psql -U postgres -d rag_db < scripts/migration_bm25.sql
```

Start everything:

```bash
docker compose up -d --build
```

| Service | URL |
|---|---|
| App | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| pgAdmin | http://localhost:5050 |

First build takes 10–25 minutes cold — it compiles the Python dependency tree and the Next.js bundle, and fetches the 280 MB reranker model. After that, startup is about a minute.

Open http://localhost:3000, create an account, and upload a PDF. Uploads are processed in the background, so the document sits at `processing` for a few seconds before it becomes queryable.

## Tech stack

Next.js 15 · TypeScript · Tailwind · FastAPI · SQLAlchemy 2.0 · PostgreSQL · ParadeDB · pgvector · LangChain · OpenAI (embeddings + generation) · ONNX Runtime · Celery · Redis · DeepEval

## Design decisions

**Hybrid retrieval instead of one method.** BM25 matches keywords; dense vectors match meaning. They fail in different ways, so running both and fusing with reciprocal rank fusion catches what either would miss on its own.

**Reranking locally instead of using LangChain's.** LangChain ships `CrossEncoderReranker`, but it depends on `sentence-transformers` and PyTorch — roughly 2 GB in the image. The ONNX export of the same model is 280 MB, runs on CPU, and costs nothing per query. I wrote the compressor against LangChain's `BaseDocumentCompressor` interface, so it stays a one-line swap.

**Switched embedding providers under a hard constraint.** Voyage AI's free tier caps at 3 requests per minute, which was failing ingestion outright — documents marked `failed`, no chunks stored, every query returning "I don't know." Adding a payment method was the obvious fix and wasn't available. Moving to OpenAI cost nothing in the schema, because the 1536-dimension output matched the existing column.

## Does any of it actually work

I built the measurement before trusting the output, because "it returns an answer" isn't evidence.

- **48 hand-written golden cases** derived from the source paper, not synthesised — 44 answerable, 4 deliberately unanswerable to test whether the system admits ignorance
- **Three metrics per run** — faithfulness (is the answer grounded in the retrieved chunks), correctness against a hand-written answer, and answer relevancy
- **A repeatable harness** at [`backend/goldenset-testdocuments/run_eval.py`](backend/goldenset-testdocuments/run_eval.py)

Then I ran the *identical* system twice against byte-identical input and compared:

| | Run 1 | Run 2 |
|---|---|---|
| Faithfulness | 0.959 | 0.936 |
| Correctness vs golden | 0.731 | 0.727 |
| Answer relevancy | 0.822 | 0.803 |
| Identical 7-chunk retrieval order | — | **1 of 48** |
| Identical top-1 chunk | — | 41 of 48 |
| Pass/fail verdicts that flipped | — | **14** |

The chunker is not the cause — chunk boundaries are byte-identical across runs, all 67 verified by hash. The cause is that **the embedding endpoint does not return reproducible vectors**: 23 of 67 came back different for identical text, up to 0.048 L2 on unit-norm vectors. Enough to reorder near-ties.

The practical conclusion: **the noise floor is wider than most retrieval improvements people report.** A change that "fixes three cases" here is inside the noise. Any honest A/B needs paired comparison on frozen retrieval, or a much larger case set.

Tenant isolation was verified the same way — a second tenant asking a question only the first tenant's documents could answer returned zero sources and a refusal, while the owning tenant got seven cited sources.

## What's next

- **Ingestion beyond PDF** — DOCX, CSV and TXT parsing, using the same chunking pipeline
- **Streaming answers** — token-by-token delivery instead of waiting for the full response
- **Continuous evaluation** — run the 48-case golden suite on every change, so a regression is caught by CI rather than by a user
- **Shorter-lived access tokens** — 15-minute tokens with a rotated refresh flow, so a leaked session expires quickly

## Acknowledgements

[PyMuPDF4LLM](https://github.com/pymupdf/pymupdf4llm) · [pgvector](https://github.com/pgvector/pgvector) · [ParadeDB](https://github.com/paradedb/paradedb) · [FastAPI](https://fastapi.tiangolo.com/) · [ONNX Runtime](https://onnxruntime.ai/)
