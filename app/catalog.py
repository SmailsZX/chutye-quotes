"""Клиент каталога: таймаут, Retry-After, circuit breaker."""

import time
import asyncio
from typing import Optional, Dict, Any

import httpx

from app.config import (
    CATALOG_TIMEOUT,
    CATALOG_MAX_CONCURRENT,
    CIRCUIT_FAIL_THRESHOLD,
    CIRCUIT_OPEN_SECONDS,
    CIRCUIT_DEFAULT_RETRY_AFTER,
)


class CatalogClient:
    def __init__(self):
        self._base_url: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._sem = asyncio.Semaphore(CATALOG_MAX_CONCURRENT)
        self._fail_count = 0
        self._open_until = 0.0  # timestamp, до которого цепь разомкнута
        self._retry_after_until = 0.0  # уважаем Retry-After от каталога

    def set_source(self, url: str) -> None:
        self._base_url = url.rstrip("/")
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(CATALOG_TIMEOUT),
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    # ----- circuit breaker -----

    def _is_open(self) -> bool:
        return time.monotonic() < self._open_until

    def _is_retry_blocked(self) -> bool:
        return time.monotonic() < self._retry_after_until

    def _on_success(self) -> None:
        self._fail_count = 0
        self._open_until = 0.0

    def _on_failure(self) -> None:
        self._fail_count += 1
        if self._fail_count >= CIRCUIT_FAIL_THRESHOLD:
            self._open_until = time.monotonic() + CIRCUIT_OPEN_SECONDS
            self._fail_count = 0

    def _apply_retry_after(self, seconds: int) -> None:
        self._retry_after_until = max(
            self._retry_after_until,
            time.monotonic() + seconds,
        )

    # ----- запрос -----

    async def fetch_quote(self, quote_id: str) -> Optional[Dict[str, Any]]:
        """
        Возвращает:
          dict  — цитата найдена;
          None  — 404 (такой цитаты нет);
          raise CatalogUnavailable — каталог недоступен / 503 / таймаут.
        """
        if self._base_url is None:
            raise CatalogUnavailable("catalog source not set")
        if self._is_open() or self._is_retry_blocked():
            raise CatalogUnavailable("catalog temporarily skipped")

        url = f"{self._base_url}/quote/{quote_id}"
        async with self._sem:
            try:
                r = await self._client.get(url)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                self._on_failure()
                raise CatalogUnavailable(str(e)) from e

        if r.status_code == 200:
            self._on_success()
            return r.json()

        if r.status_code == 404:
            self._on_success()
            return None

        if r.status_code == 503:
            retry = r.headers.get("Retry-After")
            try:
                sec = int(retry) if retry is not None else CIRCUIT_DEFAULT_RETRY_AFTER
            except ValueError:
                sec = CIRCUIT_DEFAULT_RETRY_AFTER
            self._apply_retry_after(sec)
            self._on_failure()
            raise CatalogUnavailable("catalog busy")

        # другие коды — не должны приходить по ТЗ, но подстрахуемся
        self._on_failure()
        raise CatalogUnavailable(f"unexpected status {r.status_code}")


class CatalogUnavailable(Exception):
    pass


catalog = CatalogClient()