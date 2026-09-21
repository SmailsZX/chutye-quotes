"""In-memory хранилище с LRU-эвикцией, TTL и компактной JSON-сериализацией."""

import json
import time
from collections import OrderedDict
from typing import Optional, Dict, Any

from app.config import MAX_BYTES, DELETED_TTL_SECONDS


def _raw_size(raw: str) -> int:
    """
    Реальный размер JSON-строки в памяти:
    длина UTF-8 + оверхед OrderedDict (~130 байт на запись).
    """
    return len(raw.encode("utf-8")) + 130


class QuoteStorage:
    """Хранилище цитат в памяти. Записи хранятся как JSON-строки."""

    def __init__(self, max_bytes: int = MAX_BYTES):
        # id -> JSON-строка записи
        self._quotes: OrderedDict[str, str] = OrderedDict()
        # id -> время кэширования (для TTL)
        self._meta: Dict[str, float] = {}
        # id -> время удаления (для DELETE)
        self._deleted: Dict[str, float] = {}
        self._max_bytes = max_bytes
        self._current_bytes = 0
        self._evictions = 0
        self._snapshot_epoch = 0.0

    # ---------- чтение ----------

    def get(self, quote_id: str) -> Optional[Dict[str, Any]]:
        if quote_id in self._deleted:
            return None
        raw = self._quotes.get(quote_id)
        if raw is None:
            return None
        self._quotes.move_to_end(quote_id)
        q = json.loads(raw)
        q["_cached_at"] = self._meta.get(quote_id, 0.0)
        return q

    # ---------- запись ----------

    def put(self, quote: Dict[str, Any]) -> None:
        """Атомарная вставка одной цитаты (актуальна на момент вызова)."""
        self._insert(dict(quote), time.monotonic())

    def _insert(self, quote: Dict[str, Any], cached_at: float) -> None:
        qid = quote["id"]
        self._deleted.pop(qid, None)

        old_raw = self._quotes.pop(qid, None)
        if old_raw is not None:
            self._current_bytes -= _raw_size(old_raw)

        # Служебные поля не пишем в JSON
        quote.pop("_cached_at", None)
        raw = json.dumps(quote, ensure_ascii=False, separators=(",", ":"))

        self._quotes[qid] = raw
        self._meta[qid] = cached_at
        self._current_bytes += _raw_size(raw)
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while self._current_bytes > self._max_bytes and self._quotes:
            qid, old_raw = self._quotes.popitem(last=False)
            self._current_bytes -= _raw_size(old_raw)
            self._meta.pop(qid, None)
            self._evictions += 1

    def delete(self, quote_id: str) -> bool:
        if quote_id in self._deleted:
            return False
        self._deleted[quote_id] = time.monotonic()
        old_raw = self._quotes.pop(quote_id, None)
        if old_raw is not None:
            self._current_bytes -= _raw_size(old_raw)
        self._meta.pop(quote_id, None)
        return True

    # ---------- снимок ----------

    def begin_snapshot(self) -> float:
        """
        Начать новый снимок. Возвращает epoch — метку для записей.
        ВАЖНО: _deleted НЕ очищаем здесь — только в finish_snapshot,
        чтобы неудачный снимок не сбрасывал удаления.
        """
        self._snapshot_epoch = time.monotonic()
        return self._snapshot_epoch

    def insert_from_snapshot(self, quote: Dict[str, Any], epoch: float) -> None:
        """Вставка одной записи из снимка (без списка!)."""
        self._insert(dict(quote), epoch)

    def finish_snapshot(self, epoch: float) -> int:
        """
        Удалить всё, что не пришло в снимке. Возвращает dropped.
        Только здесь очищаем _deleted — при успешном снимке.
        """
        if epoch == 0.0:
            return 0  # защита: rollback уже произошёл
        to_drop = [qid for qid, ts in self._meta.items() if ts != epoch]
        for qid in to_drop:
            raw = self._quotes.pop(qid, None)
            if raw is not None:
                self._current_bytes -= _raw_size(raw)
            self._meta.pop(qid, None)
        # Успешный снимок аннулирует все «снятые» цитаты
        self._deleted.clear()
        return len(to_drop)

    def rollback_snapshot(self) -> None:
        """
        Откатить незавершённый снимок: удалить всё, что успели вставить
        с текущим epoch. Старые записи (с другим _cached_at) не трогаем.
        _deleted не трогаем — он не был очищен в begin_snapshot.
        """
        epoch = self._snapshot_epoch
        if epoch == 0.0:
            return
        to_remove = [qid for qid, ts in self._meta.items() if ts == epoch]
        for qid in to_remove:
            raw = self._quotes.pop(qid, None)
            if raw is not None:
                self._current_bytes -= _raw_size(raw)
            self._meta.pop(qid, None)
        self._snapshot_epoch = 0.0

    # ---------- TTL ----------

    def is_fresh(self, quote: Dict[str, Any], ttl: float) -> bool:
        t = quote.get("_cached_at")
        if not t:
            return False
        return (time.monotonic() - t) < ttl

    def gc_deleted(self) -> None:
        now = time.monotonic()
        stale = [qid for qid, t in self._deleted.items()
                 if now - t > DELETED_TTL_SECONDS]
        for qid in stale:
            self._deleted.pop(qid, None)

    # ---------- метрики ----------

    def count(self) -> int:
        return len(self._quotes)

    def bytes_used(self) -> int:
        return self._current_bytes

    def evictions(self) -> int:
        return self._evictions


storage = QuoteStorage()