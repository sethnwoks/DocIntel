import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.api.dependencies import get_current_tenant_id


def override_get_current_tenant_id():
    return "test-tenant-id"


app.dependency_overrides[get_current_tenant_id] = override_get_current_tenant_id


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_delete_document_not_found(client):
    resp = client.delete("/api/documents/nonexistent-id")
    assert resp.status_code == 404


def test_delete_document_success(client):
    with patch("app.api.routers.documents.get_async_db") as mock_db:
        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = {"id": "some-id"}
        mock_session.execute.return_value = mock_result
        mock_db.return_value.__aenter__.return_value = mock_session

        resp = client.delete("/api/documents/some-id")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"
