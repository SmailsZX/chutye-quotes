"""Тесты каталога (circuit breaker, fetch)."""
import pytest
from unittest.mock import MagicMock, patch
from unittest.mock import AsyncMock

from app.catalog import CatalogClient, CatalogUnavailable


class TestCatalogClient:
    def test_initial_state(self):
        client = CatalogClient()
        assert client._base_url is None
        assert client._fail_count == 0
        assert client._open_until == 0.0

    def test_set_source(self):
        client = CatalogClient()
        client.set_source("http://example.com")
        assert client._base_url == "http://example.com"

    def test_set_source_trims_trailing_slash(self):
        client = CatalogClient()
        client.set_source("http://example.com/")
        assert client._base_url == "http://example.com"

    @pytest.mark.asyncio
    async def test_fetch_without_source_raises(self):
        client = CatalogClient()
        with pytest.raises(CatalogUnavailable, match="catalog source not set"):
            await client.fetch_quote("q1")

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        client = CatalogClient()
        client.set_source("http://example.com")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "q1", "author": "A", "text": "T"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        with patch.object(client, '_client', mock_client):
            result = await client.fetch_quote("q1")

        assert result is not None
        assert result["id"] == "q1"
        assert client._fail_count == 0

    @pytest.mark.asyncio
    async def test_fetch_404_returns_none(self):
        client = CatalogClient()
        client.set_source("http://example.com")
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        with patch.object(client, '_client', mock_client):
            result = await client.fetch_quote("q1")

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_timeout_raises_unavailable(self):
        import httpx
        client = CatalogClient()
        client.set_source("http://example.com")

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        mock_client.aclose = AsyncMock()

        with patch.object(client, '_client', mock_client):
            with pytest.raises(CatalogUnavailable):
                await client.fetch_quote("q1")

        assert client._fail_count > 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_threshold(self):
        import httpx
        client = CatalogClient()
        client.set_source("http://example.com")

        for i in range(5):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("err"))
            mock_client.aclose = AsyncMock()
            with patch.object(client, '_client', mock_client):
                try:
                    await client.fetch_quote("q1")
                except CatalogUnavailable:
                    pass

        assert client._is_open() is True

    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_on_success(self):
        client = CatalogClient()
        client.set_source("http://example.com")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "q1", "author": "A", "text": "T"}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.aclose = AsyncMock()

        with patch.object(client, '_client', mock_client):
            result = await client.fetch_quote("q1")

        assert result is not None
        assert client._is_open() is False

    def test_retry_after_blocked(self):
        client = CatalogClient()
        client.set_source("http://example.com")
        client._apply_retry_after(10)
        assert client._is_retry_blocked() is True
