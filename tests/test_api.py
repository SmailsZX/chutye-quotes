"""Тесты API chutye-quotes через test client."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage import QuoteStorage
from app.catalog import CatalogClient


# Глобальный storage и catalog для тестов
_test_storage = QuoteStorage(max_bytes=1024 * 1024)
_test_catalog = CatalogClient()


@pytest.fixture(autouse=True)
def reset_storage():
    """Очищаем хранилище перед каждым тестом."""
    global _test_storage
    _test_storage = QuoteStorage(max_bytes=1024 * 1024)


@pytest.fixture
def client(monkeypatch):
    """Test client с подменой глобальных объектов."""
    import app.main as main_module
    import app.storage as storage_module
    import app.catalog as catalog_module

    # Сохраняем оригиналы
    original_storage = storage_module.storage
    original_catalog = catalog_module.catalog

    # Подменяем на тестовые
    storage_module.storage = _test_storage
    catalog_module.catalog = _test_catalog

    client = TestClient(app)
    yield client

    # Восстанавливаем
    storage_module.storage = original_storage
    catalog_module.catalog = original_catalog


class TestHealth:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


class TestSetSource:
    def test_set_source(self, client):
        r = client.post("/catalog/source", json={"url": "http://example.com"})
        assert r.status_code == 200
        assert r.json()["source"] == "http://example.com"

    def test_set_source_missing_url(self, client):
        r = client.post("/catalog/source", json={})
        assert r.status_code == 400


class TestPutQuote:
    def test_put_quote(self, client):
        r = client.put(
            "/catalog/q1",
            json={"author": "Pushkin", "text": "Я помню чудное мгновенье..."}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "q1"
        assert data["author"] == "Pushkin"

    def test_put_quote_missing_author(self, client):
        r = client.put(
            "/catalog/q1",
            json={"text": "No author"}
        )
        assert r.status_code == 422

    def test_put_quote_author_too_long(self, client):
        r = client.put(
            "/catalog/q1",
            json={"author": "A" * 201, "text": "T"}
        )
        assert r.status_code == 422

    def test_put_quote_text_too_long(self, client):
        r = client.put(
            "/catalog/q1",
            json={"author": "A", "text": "T" * 16385}
        )
        assert r.status_code == 422

    def test_put_quote_with_extra_fields(self, client):
        r = client.put(
            "/catalog/q1",
            json={"author": "A", "text": "T", "year": 1837, "tags": ["classics"]}
        )
        assert r.status_code == 200
        data = r.json()
        assert data["year"] == 1837
        assert data["tags"] == ["classics"]


class TestDeleteQuote:
    def test_delete_quote(self, client):
        # сначала создадим
        client.put("/catalog/q1", json={"author": "A", "text": "T"})
        r = client.delete("/catalog/q1")
        assert r.status_code == 200
        assert r.json()["deleted"] is True

    def test_delete_missing(self, client):
        # delete всегда возвращает 200 (код всегда True кроме уже удалённого)
        r = client.delete("/catalog/missing")
        assert r.status_code == 200


class TestGetQuoteLocal:
    def test_get_quote_local(self, client):
        client.put("/catalog/q1", json={"author": "A", "text": "T"})
        r = client.get("/quotes/q1")
        assert r.status_code == 200
        assert r.json()["text"] == "T"
        assert r.headers["X-Source"] == "LOCAL"

    def test_get_quote_not_found(self, client):
        r = client.get("/quotes/missing")
        assert r.status_code == 404


class TestStats:
    def test_stats(self, client):
        r = client.get("/stats")
        assert r.status_code == 200
        data = r.json()
        assert "served_local" in data
        assert "served_from_catalog" in data
        assert "catalog_reads" in data
        assert "evictions" in data
        assert "local" in data
        assert "bytes" in data
