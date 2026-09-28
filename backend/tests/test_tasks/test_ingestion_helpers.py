import hashlib
from app.tasks.ingestion_task import _chunk_text, _compute_chunk_hash


def test_chunk_text_basic():
    text = "ABCDEFGHIJ"
    chunks = _chunk_text(text)
    assert len(chunks) > 0
    assert all(isinstance(c, str) for c in chunks)


def test_chunk_text_overlap():
    text = "0123456789" * 200
    chunks = _chunk_text(text)
    assert len(chunks) > 1
    for c in chunks:
        assert c in text


def test_compute_chunk_hash_deterministic():
    content = "hello world"
    h1 = _compute_chunk_hash(content)
    h2 = _compute_chunk_hash(content)
    assert h1 == h2
    assert len(h1) == 64


def test_compute_chunk_hash_unique():
    h1 = _compute_chunk_hash("content A")
    h2 = _compute_chunk_hash("content B")
    assert h1 != h2


def test_compute_file_hash_placeholder():
    import io
    data = b"fake file bytes"
    expected = hashlib.sha256(data).hexdigest()
    f = io.BytesIO(data)
    f.seek(0)
    hash_sha256 = hashlib.sha256()
    for chunk in iter(lambda: f.read(4096), b""):
        hash_sha256.update(chunk)
    assert hash_sha256.hexdigest() == expected
