import io
import hashlib
from app.api.routers.upload import compute_file_hash


class FakeUploadFile:
    def __init__(self, content: bytes, filename: str = "test.txt"):
        self.file = io.BytesIO(content)
        self.filename = filename


def test_compute_file_hash_success():
    content = b"hello world"
    f = FakeUploadFile(content)
    result = compute_file_hash(f)
    expected = hashlib.sha256(content).hexdigest()
    assert result == expected


def test_compute_file_hash_resets_position():
    content = b"abcdef"
    f = FakeUploadFile(content)
    _ = compute_file_hash(f)
    assert f.file.tell() == 0
