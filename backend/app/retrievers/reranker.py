import asyncio
import json
import logging
from pathlib import Path
from typing import Any, List, Optional, Sequence

import numpy as np
from tokenizers import Tokenizer
from tokenizers.pre_tokenizers import Whitespace
from onnxruntime import InferenceSession

from langchain_core.callbacks import Callbacks
from langchain_core.documents import Document
from langchain_core.documents.compressor import BaseDocumentCompressor

logger = logging.getLogger(__name__)

RERANKER_MODEL_DIR = Path("/app/models/reranker")
RERANKER_MODEL_FILE = RERANKER_MODEL_DIR / "model.onnx"
RERANKER_TOKENIZER_FILE = RERANKER_MODEL_DIR / "tokenizer.json"
RERANKER_CONFIG_FILE = RERANKER_MODEL_DIR / "config.json"

_session: InferenceSession | None = None
_tokenizer: Tokenizer | None = None
_config: dict[str, Any] | None = None


def _load_resources() -> tuple[InferenceSession, Tokenizer, dict[str, Any]]:
    global _session, _tokenizer, _config
    if _session is None:
        if not RERANKER_MODEL_FILE.exists() or not RERANKER_TOKENIZER_FILE.exists():
            raise FileNotFoundError(
                f"ONNX reranker model not found in {RERANKER_MODEL_DIR}. "
                "Ensure the Docker image is built with the model downloaded."
            )
        _session = InferenceSession(str(RERANKER_MODEL_FILE))
        _tokenizer = Tokenizer.from_file(str(RERANKER_TOKENIZER_FILE))
        _tokenizer.pre_tokenizer = Whitespace()
        if RERANKER_CONFIG_FILE.exists():
            with open(RERANKER_CONFIG_FILE, "r") as f:
                _config = json.load(f)
        else:
            _config = {"max_length": 512}
    return _session, _tokenizer, _config


def _tokenize_pair(tokenizer: Tokenizer, query: str, passage: str, max_length: int) -> dict[str, Any]:
    # Encode as a genuine (sequence, pair) rather than pasting "[CLS]"/"[SEP]"
    # into a string. This checkpoint is XLM-RoBERTa, whose tokenizer already
    # inserts <s> and </s>; the literal markers were being tokenised as
    # ordinary text ("[", "CLS", "]"), which corrupted the cross-encoder
    # input. Measured on the live corpus: the chunk that answers "what
    # promotion did Seth get" ranked #2 under the old encoding and #1 under
    # this one.
    encoding = tokenizer.encode(query, passage)
    input_ids = encoding.ids[:max_length]
    attention_mask = encoding.attention_mask[:max_length]

    pad_len = max_length - len(input_ids)
    input_ids = input_ids + [0] * pad_len
    attention_mask = attention_mask + [0] * pad_len

    return {
        "input_ids": np.array([input_ids], dtype=np.int64),
        "attention_mask": np.array([attention_mask], dtype=np.int64),
    }


def _score_pairs_sync(question: str, passages: List[str], batch_size: int = 8) -> List[float]:
    """Synchronous version for use in compressor."""
    if not passages:
        return []

    session, tokenizer, config = _load_resources()
    max_length = config.get("max_length", 512)

    all_scores: List[float] = []
    for i in range(0, len(passages), batch_size):
        batch = passages[i : i + batch_size]
        input_ids_list = []
        attention_mask_list = []

        for passage in batch:
            tokens = _tokenize_pair(tokenizer, question, passage, max_length)
            input_ids_list.append(tokens["input_ids"])
            attention_mask_list.append(tokens["attention_mask"])

        input_ids = np.concatenate(input_ids_list, axis=0)
        attention_mask = np.concatenate(attention_mask_list, axis=0)

        inputs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }

        outputs = session.run(None, inputs)
        logits = outputs[0]

        for j in range(len(batch)):
            score = float(logits[j][0])
            all_scores.append(score)

    return all_scores


class BGERerankerCompressor(BaseDocumentCompressor):
    """LangChain document compressor wrapping ONNX BGE cross-encoder."""

    def __init__(
        self,
        batch_size: int = 8,
        top_n: Optional[int] = None,
    ):
        super().__init__()
        self._batch_size = batch_size
        self._top_n = top_n

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks = None,
    ) -> Sequence[Document]:
        if not documents:
            return []

        passages = [doc.page_content for doc in documents]
        scores = _score_pairs_sync(query, passages, self._batch_size)

        # Add rerank_score to metadata and sort
        scored_docs = []
        for doc, score in zip(documents, scores):
            new_metadata = {**doc.metadata, "rerank_score": score}
            scored_docs.append(Document(page_content=doc.page_content, metadata=new_metadata))

        # Sort by rerank_score descending
        scored_docs.sort(key=lambda d: d.metadata.get("rerank_score", 0.0), reverse=True)

        # Apply top_n if specified
        if self._top_n is not None:
            scored_docs = scored_docs[:self._top_n]

        logger.info(
            "[RERANK] question=%r candidates=%d scored=%d top_n=%s",
            query[:100],
            len(documents),
            len(scored_docs),
            self._top_n,
        )

        return scored_docs

    async def acompress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks = None,
    ) -> Sequence[Document]:
        """Async version - runs sync in executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.compress_documents, documents, query, callbacks
        )