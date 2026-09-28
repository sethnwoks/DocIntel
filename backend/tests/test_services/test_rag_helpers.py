
from app.tasks.ingestion_task import _chunk_text


def test_chunk_text_empty():
    assert _chunk_text("") == []


def test_chunk_text_single_chunk():
    text = "short"
    chunks = _chunk_text(text)
    assert chunks == [text]


def test_chunk_text_multiple_chunks():
    text = "A" * 1700
    chunks = _chunk_text(text)
    assert len(chunks) > 1
