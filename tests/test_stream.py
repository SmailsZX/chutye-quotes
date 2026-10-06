"""Тесты stream_snapshot парсера."""
import pytest
import asyncio
from app.import_service import stream_snapshot, _find_object_end


class TestFindObjectEnd:
    def test_simple_object(self):
        assert _find_object_end('{"a":1}') == 6

    def test_nested_object(self):
        assert _find_object_end('{"a":{"b":1}}') == 12

    def test_no_closing_brace(self):
        assert _find_object_end('{"a":1') == -1

    def test_empty_object(self):
        assert _find_object_end('{}') == 1

    def test_string_with_brace_inside(self):
        # скобка внутри строки не должна считаться
        assert _find_object_end('{"a":"{}"}') == 9


class TestStreamSnapshot:
    @pytest.mark.asyncio
    async def test_parse_single_quote(self):
        """Парсит один объект цитаты из снимка."""
        data = b'{"quotes":[{"id":"q1","author":"A","text":"T"}]}'

        class FakeRequest:
            async def stream(self):
                yield data

        chunks = []
        async for chunk in stream_snapshot(FakeRequest()):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0]["id"] == "q1"
        assert chunks[0]["author"] == "A"
        assert chunks[0]["text"] == "T"

    @pytest.mark.asyncio
    async def test_parse_multiple_quotes(self):
        data = b'{"quotes":[{"id":"q1","author":"A","text":"T1"},{"id":"q2","author":"B","text":"T2"}]}'

        class FakeRequest:
            async def stream(self):
                yield data

        chunks = []
        async for chunk in stream_snapshot(FakeRequest()):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0]["id"] == "q1"
        assert chunks[1]["id"] == "q2"

    @pytest.mark.asyncio
    async def test_malformed_no_bracket(self):
        data = b'not json at all'

        class FakeRequest:
            async def stream(self):
                yield data

        with pytest.raises(ValueError, match="no opening bracket"):
            async for _ in stream_snapshot(FakeRequest()):
                pass

    @pytest.mark.asyncio
    async def test_missing_quotes_key(self):
        data = b'{"foo": [1,2,3]}'

        class FakeRequest:
            async def stream(self):
                yield data

        with pytest.raises(ValueError, match="missing 'quotes' key"):
            async for _ in stream_snapshot(FakeRequest()):
                pass

    @pytest.mark.asyncio
    async def test_underspecified_array(self):
        """Незамкнутый массив — ошибка."""
        data = b'{"quotes":[{"id":"q1"}'

        class FakeRequest:
            async def stream(self):
                yield data

        with pytest.raises(ValueError, match="unterminated"):
            async for _ in stream_snapshot(FakeRequest()):
                pass

    @pytest.mark.asyncio
    async def test_chunked_stream(self):
        """Работает при постраничной подаче данных."""
        data = b'{"quotes":[{"id":"q1","author":"A","text":"T"}]}'
        half = len(data) // 2

        class FakeRequest:
            async def stream(self):
                yield data[:half]
                yield data[half:]

        chunks = []
        async for chunk in stream_snapshot(FakeRequest()):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0]["id"] == "q1"

    @pytest.mark.asyncio
    async def test_invalid_json_skipped(self):
        """Невалидные JSON-объекты пропускаются, не ломают поток."""
        data = b'{"quotes":[{"id":"q1","author":"A","text":"T"},{"broken"}}]}'

        class FakeRequest:
            async def stream(self):
                yield data

        chunks = []
        async for chunk in stream_snapshot(FakeRequest()):
            chunks.append(chunk)

        assert len(chunks) == 1
        assert chunks[0]["id"] == "q1"
