"""
Evaluate the live RAG chain against a hand-built DeepEval golden set.

Run inside the backend container, where the reranker model dir resolves:

    docker exec -w /app rag_backend python goldenset-testdocuments/run_eval.py --limit 5

The chain is built once by app.chains.rag_chain.build_rag_chain, exactly as the
/query endpoint builds it. Nothing here re-implements retrieval.

Retrieval capture works by wrapping BGERerankerCompressor.acompress_documents at
class level BEFORE the chain is built, so the instance created inside
build_rag_chain is the wrapped one. That records the documents the LLM actually
received. The /query endpoint instead runs the whole retriever stack a second
time to collect sources; that is avoided here because retrieval is deterministic
and running it twice would double the cost for no extra signal.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

from deepeval.dataset.golden import Golden
from deepeval.evaluate import AsyncConfig, DisplayConfig, ErrorConfig, evaluate
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric
from deepeval.metrics.g_eval import GEval
from deepeval.test_case import LLMTestCase
from deepeval.test_case.llm_test_case import SingleTurnParams

from app.chains.rag_chain import build_rag_chain
from app.db.async_session import AsyncSessionLocal
from app.retrievers.reranker import BGERerankerCompressor

GOLDEN_PATH = Path(__file__).parent / "testragdoc" / "golden_deepeval.jsonl"
RESULTS_PATH = Path(__file__).parent / "eval_results.json"

JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gpt-4o")

# Captured by the wrapper installed below, one entry per query.
CAPTURED: list = []


def _install_capture() -> None:
    original = BGERerankerCompressor.acompress_documents

    async def capturing(self, documents, query, **kwargs):
        out = await original(self, documents, query, **kwargs)
        CAPTURED.append(out)
        return out

    BGERerankerCompressor.acompress_documents = capturing


def load_goldens(limit: int | None, only: str | None) -> list[Golden]:
    rows = []
    with open(GOLDEN_PATH) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    if only:
        wanted = set(only.split(","))
        rows = [r for r in rows if r["additional_metadata"]["golden_id"] in wanted]
    if limit:
        rows = rows[:limit]

    goldens = []
    for r in rows:
        md = r["additional_metadata"]
        goldens.append(
            Golden(
                input=r["input"],
                expected_output=r["expected_output"],
                context=r.get("context"),
                additional_metadata=md,
            )
        )
    return goldens


async def collect_answers(
    goldens: list[Golden], tenant_id: str, document_id: str | None
) -> tuple[list[LLMTestCase], list[dict]]:
    chain = build_rag_chain(
        tenant_id=tenant_id,
        db_session_factory=AsyncSessionLocal,
        k=50,
        rerank_top_n=7,
        document_ids=[document_id] if document_id else None,
    )

    test_cases: list[LLMTestCase] = []
    trace: list[dict] = []

    for n, g in enumerate(goldens, 1):
        gid = g.additional_metadata["golden_id"]
        CAPTURED.clear()
        t0 = time.time()
        try:
            answer = await chain.ainvoke({"question": g.input})
        except Exception as exc:  # keep going; one bad query must not kill the run
            print(f"  [{n}/{len(goldens)}] {gid} GENERATION FAILED: {exc}", flush=True)
            trace.append({"golden_id": gid, "error": str(exc)})
            continue

        docs = CAPTURED[-1] if CAPTURED else []
        retrieval_context = [d.page_content for d in docs]
        elapsed = time.time() - t0

        test_cases.append(
            LLMTestCase(
                input=g.input,
                actual_output=answer,
                expected_output=g.expected_output,
                retrieval_context=retrieval_context,
                context=g.context,
                additional_metadata=g.additional_metadata,
            )
        )
        trace.append(
            {
                "golden_id": gid,
                "question": g.input,
                "actual_output": answer,
                "retrieval_context": retrieval_context,
                "chunk_indexes": [(d.metadata or {}).get("chunk_index") for d in docs],
                "rerank_scores": [round((d.metadata or {}).get("rerank_score", 0.0), 4) for d in docs],
                "n_retrieved": len(docs),
                "seconds": round(elapsed, 2),
            }
        )
        print(
            f"  [{n}/{len(goldens)}] {gid} ok - {len(docs)} chunks, {elapsed:.1f}s",
            flush=True,
        )

    return test_cases, trace


def answerable_goldens(cases: list[LLMTestCase]) -> list[LLMTestCase]:
    return [c for c in cases if c.additional_metadata.get("answerable", True)]


def unanswerable_goldens(cases: list[LLMTestCase]) -> list[LLMTestCase]:
    return [c for c in cases if not c.additional_metadata.get("answerable", True)]


def build_metrics(for_unanswerable: bool) -> list:
    faithfulness = FaithfulnessMetric(
        model=JUDGE_MODEL, include_reason=True, strict_mode=False
    )

    if for_unanswerable:
        # The correct behaviour is to decline. Penalise a confident invention.
        # AnswerRelevancy is deliberately NOT used here: it scores how much the
        # output addresses the question, so "I don't know." scores 0.0 even
        # though declining is exactly right. Measured on rag045.
        criteria = (
            "The question asks for information the source document does not report. "
            "Score 1 if the actual output says the information is not available, "
            "not stated, or declines to answer. Score 0 if it supplies a specific "
            "value, name, or claim as though the document stated it."
        )
    else:
        criteria = (
            "Score 1 if the actual output conveys the same substantive information as "
            "the expected output, allowing different wording, extra detail, and "
            "citation markers. Score 0 if it contradicts the expected output, omits "
            "its central claim, or answers a different question."
        )
        relevancy = AnswerRelevancyMetric(
            model=JUDGE_MODEL, include_reason=True, strict_mode=False
        )

    correctness = GEval(
        name="correctness_vs_golden",
        criteria=criteria,
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
        ],
        model=JUDGE_MODEL,
        strict_mode=False,
    )
    return [faithfulness, correctness, relevancy] if not for_unanswerable else [
        faithfulness,
        correctness,
    ]


def _rows_from(res, trace: list[dict]) -> list[dict]:
    rows = []
    for tr in res.test_results:
        # TestResult carries no golden_id, so recover it by matching the input
        # back to the trace built during generation.
        gid = next(
            (t["golden_id"] for t in trace if t.get("question") == tr.input), tr.name
        )
        rows.append(
            {
                "golden_id": gid,
                "question": tr.input,
                "actual_output": tr.actual_output,
                "metrics": {
                    md.name: {
                        "score": md.score,
                        "threshold": md.threshold,
                        "success": md.success,
                        "reason": md.reason,
                    }
                    for md in (tr.metrics_data or [])
                },
            }
        )
    return rows


def _complete(rows: list[dict], n_cases: int) -> bool:
    """True when every case produced a real score for every metric."""
    if len(rows) != n_cases:
        return False
    return all(
        m.get("score") is not None for r in rows for m in r["metrics"].values()
    )


def score_in_batches(
    subset: list[LLMTestCase],
    unanswerable: bool,
    trace: list[dict],
    batch_size: int,
    cooldown: float,
    attempts: int,
) -> list[dict]:
    """
    Score in small batches with a cooldown between them.

    The org is capped at 30k tokens/min on gpt-4o. A single faithfulness call
    re-sends 7 chunks of retrieval_context twice (once to extract truth
    statements, once to judge them), so it is roughly 5k tokens on its own.
    Running all 44 cases at once, or even one-at-a-time with a 1.5s throttle,
    blows the ceiling and deepeval's own retries are not enough to ride it out.
    Batching means a rate limit costs one small batch instead of the run.
    """
    collected: list[dict] = []
    batches = [subset[i : i + batch_size] for i in range(0, len(subset), batch_size)]

    for n, batch in enumerate(batches, 1):
        got: list[dict] = []
        for attempt in range(1, attempts + 1):
            try:
                res = evaluate(
                    test_cases=batch,
                    metrics=build_metrics(for_unanswerable=unanswerable),
                    async_config=AsyncConfig(
                        run_async=True, throttle_value=0, max_concurrent=1
                    ),
                    # Keep failures visible as N/A rows so _complete() can tell a
                    # partial batch from a good one.
                    error_config=ErrorConfig(
                        ignore_errors=True, skip_on_missing_params=True
                    ),
                    display_config=DisplayConfig(
                        show_indicator=False, print_results=False
                    ),
                )
                got = _rows_from(res, trace)
            except Exception as exc:
                print(
                    f"  batch {n}/{len(batches)} attempt {attempt}: {type(exc).__name__}",
                    flush=True,
                )
                got = []
            if _complete(got, len(batch)):
                break
            if attempt < attempts:
                wait = cooldown * attempt
                print(
                    f"  batch {n}/{len(batches)} incomplete, waiting {wait:.0f}s",
                    flush=True,
                )
                time.sleep(wait)
        collected.extend(got)
        done = len(collected)
        print(
            f"  batch {n}/{len(batches)}: {done}/{len(subset)} cases scored",
            flush=True,
        )
        if n < len(batches):
            time.sleep(cooldown)

    return collected


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default=os.getenv("EVAL_TENANT_ID"))
    ap.add_argument("--document", default=os.getenv("EVAL_DOCUMENT_ID"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default=None, help="comma-separated golden_ids")
    ap.add_argument("--out", default=str(RESULTS_PATH))
    ap.add_argument(
        "--score-only",
        action="store_true",
        help="rescore from an existing --out file, skip generation entirely",
    )
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--throttle", type=float, default=1.0)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument(
        "--cooldown",
        type=float,
        default=20.0,
        help="seconds to wait between batches, for the 30k tokens/min cap",
    )
    ap.add_argument("--attempts", type=int, default=4)
    args = ap.parse_args()

    if not args.tenant and not args.score_only:
        print("error: --tenant is required", file=sys.stderr)
        return 2

    _install_capture()

    if args.score_only:
        # Regeneration costs ~70s/case and is not needed: the previous run
        # already stored every answer and its retrieval context.
        with open(args.out) as fh:
            trace = json.load(fh)["trace"]
        goldens = {
            g.additional_metadata["golden_id"]: g for g in load_goldens(None, None)
        }
        test_cases = []
        for t in trace:
            if "error" in t or not t.get("retrieval_context"):
                continue
            g = goldens[t["golden_id"]]
            test_cases.append(
                LLMTestCase(
                    input=t["question"],
                    actual_output=t["actual_output"],
                    expected_output=g.expected_output,
                    retrieval_context=t["retrieval_context"],
                    context=g.context,
                    additional_metadata=g.additional_metadata,
                )
            )
        print(f"score-only: reusing {len(test_cases)} saved generations\n", flush=True)
    else:
        goldens = load_goldens(args.limit, args.only)
        print(
            f"evaluator model: {os.getenv('RAG_LLM_MODEL', 'gpt-4o')}  |  "
            f"judge: {JUDGE_MODEL}  |  {len(goldens)} cases",
            flush=True,
        )
        test_cases, trace = asyncio.run(
            collect_answers(goldens, args.tenant, args.document)
        )
        print(f"\ngenerated {len(test_cases)} answers, scoring\n", flush=True)

    all_results = {}
    for label, subset in (
        ("answerable", answerable_goldens(test_cases)),
        ("unanswerable", unanswerable_goldens(test_cases)),
    ):
        if not subset:
            continue
        print(f"--- scoring {label}: {len(subset)} cases ---", flush=True)
        all_results[label] = score_in_batches(
            subset,
            unanswerable=(label == "unanswerable"),
            trace=trace,
            batch_size=args.batch_size,
            cooldown=args.cooldown,
            attempts=args.attempts,
        )

    with open(args.out, "w") as fh:
        json.dump({"trace": trace, "scores": all_results}, fh, indent=2)
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
