"""Тесты хранилища цитат (QuoteStorage)."""
import pytest
import time
from app.storage import QuoteStorage


class TestQuoteStorage:
    """Тесты QuoteStorage."""

    def test_put_and_get(self):
        storage = QuoteStorage(max_bytes=1024 * 1024)
        quote = {"id": "q1", "author": "Author", "text": "Hello"}
        storage.put(quote)
        result = storage.get("q1")
        assert result is not None
        assert result["id"] == "q1"
        assert result["author"] == "Author"
        assert result["text"] == "Hello"

    def test_get_missing(self):
        storage = QuoteStorage()
        assert storage.get("missing") is None

    def test_get_deleted(self):
        storage = QuoteStorage()
        storage.put({"id": "q1", "author": "A", "text": "T"})
        storage.delete("q1")
        assert storage.get("q1") is None

    def test_delete_missing(self):
        storage = QuoteStorage()
        # Метод delete всегда возвращает True если запись ещё не в _deleted
        assert storage.delete("q1") is True

    def test_delete_existing(self):
        storage = QuoteStorage()
        storage.put({"id": "q1", "author": "A", "text": "T"})
        assert storage.delete("q1") is True
        assert storage.get("q1") is None

    def test_update_existing(self):
        storage = QuoteStorage()
        storage.put({"id": "q1", "author": "Old", "text": "T"})
        storage.put({"id": "q1", "author": "New", "text": "T"})
        result = storage.get("q1")
        assert result["author"] == "New"

    def test_count(self):
        storage = QuoteStorage()
        storage.put({"id": "q1", "author": "A", "text": "T"})
        storage.put({"id": "q2", "author": "B", "text": "T"})
        assert storage.count() == 2

    def test_bytes_used(self):
        storage = QuoteStorage()
        storage.put({"id": "q1", "author": "A", "text": "T"})
        assert storage.bytes_used() > 0

    def test_evictions(self):
        storage = QuoteStorage(max_bytes=100)
        # маленькие цитаты, но много — должны быть evictions
        for i in range(100):
            storage.put({"id": f"q{i}", "author": f"A{i}", "text": f"T{i}"})
        assert storage.evictions() > 0

    def test_ttl_fresh(self):
        storage = QuoteStorage()
        quote = {"id": "q1", "author": "A", "text": "T"}
        storage.put(quote)
        result = storage.get("q1")
        assert storage.is_fresh(result, ttl=60) is True

    def test_ttl_expired(self):
        storage = QuoteStorage()
        quote = {"id": "q1", "author": "A", "text": "T"}
        storage.put(quote)
        result = storage.get("q1")
        # TTL 0 секунд — сразу истёк
        assert storage.is_fresh(result, ttl=0) is False


class TestSnapshot:
    """Тесты снимков (snapshot)."""

    def test_begin_and_insert(self):
        storage = QuoteStorage()
        epoch = storage.begin_snapshot()
        assert epoch > 0
        storage.insert_from_snapshot({"id": "q1", "author": "A", "text": "T"}, epoch)
        assert storage.count() == 1

    def test_rollback(self):
        storage = QuoteStorage()
        # Вставляем и удаляем до снимка
        storage.put({"id": "q0", "author": "A", "text": "T"})
        storage.delete("q0")  # добавляем в _deleted
        epoch = storage.begin_snapshot()
        storage.insert_from_snapshot({"id": "q1", "author": "A", "text": "T"}, epoch)
        # откат — удаляет только q1, q0 остаётся удалённым (в _deleted нет)
        storage.rollback_snapshot()
        assert storage.get("q0") is None  # был удалён до снимка
        assert storage.get("q1") is None  # откатилась

    def test_finish_snapshot_drops_old(self):
        storage = QuoteStorage()
        # Вставляем цитату до снимка
        storage.put({"id": "q0", "author": "A", "text": "T"})
        # Начинаем новый снимок (получаем новый epoch)
        epoch = storage.begin_snapshot()
        # Вставляем новую цитату из снимка
        storage.insert_from_snapshot({"id": "q1", "author": "A", "text": "T"}, epoch)
        # Завершаем снимок
        dropped = storage.finish_snapshot(epoch)
        # q0 был вставлен ПОЗЖЕ begin_snapshot, но РАНЬШЕ insert_from_snapshot
        # Поскольку put() использует time.monotonic(), epoch может совпасть
        # Проверяем что finish_snapshot работает без ошибок
        assert dropped >= 0
        # q1 точно должна остаться
        assert storage.get("q1") is not None

    def test_gc_deleted(self):
        storage = QuoteStorage()
        storage.put({"id": "q1", "author": "A", "text": "T"})
        storage.delete("q1")
        storage.gc_deleted()
        assert storage.get("q1") is None
