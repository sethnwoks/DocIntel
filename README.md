# DocIntel

Multi-tenant RAG platform. Upload documents, get an isolated knowledge base per organisation, query it with citations. FastAPI + Next.js, hybrid BM25/vector retrieval with a cross-encoder reranker, Celery for ingestion, six services in Docker Compose.

![DocIntel signed in, showing an ingested 19-page paper split into 67 chunks](assets/docintel-document-ingested.png)

## The problem this actually solves

Calling an LLM is easy. The hard part of a multi-tenant RAG system is that **tenant A must never see tenant B's data**, and that has to hold at every layer: upload paths, chunk rows, vector search, BM25, the reranker, the prompt, and the API responses. Retrieval is tenant-scoped in the SQL itself, so isolation is a property of the queries rather than something enforced after the fact.

I verified this with a second tenant asking a question that only the first tenant's documents could answer: zero sources returned, answer was a refusal, while the owning tenant got seven cited sources.

## The part I found more interesting: measuring whether any of it works

Most RAG projects stop at "it returns an answer." I wanted to know whether a change to retrieval actually improved anything, so I built the measurement first.

- **48 hand-written golden cases** derived from the source paper, not synthesised — 44 answerable, 4 deliberately unanswerable to test whether the system admits ignorance
- **Three metrics per run** via DeepEval: faithfulness (is the answer grounded in the retrieved chunks), correctness against my hand-written answer, and answer relevancy
- **A repeatable harness** at [`backend/goldenset-testdocuments/run_eval.py`](backend/goldenset-testdocuments/run_eval.py)

Then I ran the *identical* system twice against byte-identical input and compared.

| | Run 1 | Run 2 |
|---|---|---|
| Faithfulness | 0.959 | 0.936 |
| Correctness vs golden | 0.731 | 0.727 |
| Answer relevancy | 0.822 | 0.803 |
| Same 7 chunks retrieved, same order | — | **1 of 48** |
| Same top-1 chunk | — | 41 of 48 |
| Pass/fail verdicts that flipped | — | **14** |

The cause is not the chunker. Chunk boundaries are byte-identical across runs (all 67 verified by hash). The cause is that **the embedding endpoint does not return reproducible vectors** — 23 of 67 came back different for identical text, up to 0.048 L2 on unit-norm vectors. Enough to reorder near-ties.

The practical conclusion: **the noise floor is wider than most retrieval improvements people report.** A change that "fixes three cases" here is inside the noise. Any honest A/B needs paired comparison on frozen retrieval, or a much larger case set.

That finding is the reason this repo is worth more than a screenshot.

## How it works

```
Browser ──POST /api/upload──> FastAPI ──task.delay──> Redis ──> Celery worker
   │                                                              │
   │                                            PyMuPDF4LLM: PDF -> markdown + JSON
   │                                            header-aware split -> chunks
   │                                            OpenAI embeddings
   │                                                     │
   │                                                     v
   │                          PostgreSQL: chunks + pgvector + pg_search BM25
   │                                                     │
   └──POST /api/query──> tenant-scoped hybrid retrieval ──> ONNX BGE rerank ──> gpt-4o
                              BM25 + cosine, RRF fused         7 chunks        answer + sources
```

- **Ingestion** is a real Celery task. Upload returns `pending` immediately; the worker parses, chunks, embeds and inserts, then flips the row to `completed`. The parsed markdown and structural JSON are kept in a JSONB column so re-chunking never requires re-parsing.
- **Retrieval** runs BM25 (ParadeDB `pg_search`) and pgvector cosine as two retrievers, fuses them with reciprocal rank fusion, then reranks with a quantised BGE cross-encoder on ONNX Runtime — no PyTorch in the image.
- **Auth** is JWT in an HttpOnly cookie, with the tenant resolved in the FastAPI dependency layer so no handler can forget to scope its query.

## Running it

Requires Docker Compose v2 and an OpenAI API key.

```bash
git clone <this-repo> && cd multi-tenant-rag
cp .env.example .env      # then set OPENAI_API_KEY and JWT_SECRET_KEY (32+ chars)
```

Create the schema once:

```bash
docker compose up -d postgres
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
| Frontend | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/health |
| pgAdmin | http://localhost:5050 |

First build is slow — the ONNX reranker weights are ~280 MB and the Python image installs the scientific stack. Budget 10–25 minutes cold.

Then sign up, upload a PDF, wait for the row to reach `completed`, and ask a question.

There is also a terminal client at `scripts/rag_cli/` for upload, query and status without the UI:

```bash
python -m scripts.rag_cli.main --help
```

## Known limitations

Things I know are wrong or unfinished, rather than leaving you to find them:

- **Retrieval is not reproducible run-to-run**, for the embedding reason measured above. This is upstream, not fixable in this codebase, but it makes small A/B comparisons meaningless.
- **Chunk-insert failures are swallowed.** `ingestion_task.py` catches insert errors with a bare `except`, then marks the document `completed` regardless, and mislabels a shortfall as "duplicates". A partially-ingested document currently reports success. Not yet fixed.
- **Malformed UUIDs return 500, not 422.** Passing a non-UUID document id raises inside asyncpg instead of being rejected as a validation error.
- **The upload endpoint does not validate file type.** The UI advertises PDF, DOCX, CSV and TXT, but only PDF is actually parsed and verified — a `.docx` or `.csv` will be accepted, queued, and then fail inside the worker. There is no server-side allow-list.
- **The GEval correctness criterion is misconfigured for the unanswerable cases.** The judge writes reasoning that says the refusal was correct and then scores it 0.087. The score contradicts its own explanation. All four refusals are in fact correct.
- **Three of my goldens are wrong**, not the model: `rag008`, `rag023` and `rag024` are cases where my hand-written answer disagrees with the source paper. I found these by auditing failures against the PDF.
- **`rag039` cites the wrong page** in its `source_pages` metadata.
- **No LICENSE file yet** — needs choosing before this is public.

## Tests

There is a pytest suite at `backend/tests/` (34 test functions across API, services, tasks and CLI).

It is **not** green, and I would rather say so than claim otherwise:

- 10 pass
- 6 fail — all six are bad fixtures of mine that use placeholder strings like `"some-id"` as document ids, which the database rejects before the 404 path is reached
- 3 CLI modules fail to collect because they import `scripts.rag_cli` from the repo root while the suite runs with `backend/` on the path

The application code is not implicated in those failures. Fixing them is the next thing I'd do.

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15.3, React 19, TypeScript 5, Tailwind 3.4 |
| API | FastAPI 0.141, Uvicorn, Python 3.12 |
| Task queue | Celery 5.6 (prefork), Redis 8.1 |
| Database | ParadeDB (PostgreSQL + pgvector 0.5 + pg_search BM25) |
| Parsing | PyMuPDF4LLM 1.28 |
| Embeddings | OpenAI `text-embedding-3-small` (1536-dim) |
| Reranking | ONNX Runtime 1.30 + BGE cross-encoder, INT8 quantised |
| Orchestration | LangChain 1.4 |
| Auth | python-jose JWT, bcrypt, HttpOnly cookies |
| Evaluation | DeepEval 4.2.6 (dev only, not in the app image) |

## Layout

```
backend/app/
  api/routers/       auth, upload, query, documents
  api/dependencies.py  resolves the current tenant for every request
  auth/              JWT issue/verify, bcrypt
  chains/rag_chain.py  prompt construction + BM25/vector ensemble
  retrievers/        parade_db.py (BM25), pgvector.py (vector), reranker.py (ONNX)
  tasks/             Celery app, ingestion pipeline
  db/, crud/, models/
backend/tests/
backend/goldenset-testdocuments/
  golden_deepeval.jsonl   48 hand-written cases (under testragdoc/)
  run_eval.py             evaluation harness
scripts/             schema.sql, migrations, rag_cli
frontend/            Next.js app
```

## Acknowledgements

[PyMuPDF4LLM](https://github.com/pymupdf/pymupdf4llm) · [pgvector](https://github.com/pgvector/pgvector) · [ParadeDB](https://github.com/paradedb/paradedb) · [FastAPI](https://fastapi.tiangolo.com/)
