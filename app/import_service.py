"""Стриминговый парсер снимка каталога."""

import json
import codecs
from typing import AsyncIterator, Dict, Any

from fastapi import Request

from app.storage import storage


async def stream_snapshot(request: Request) -> AsyncIterator[Dict[str, Any]]:
    """
    Потоково разбирает JSON-снимок:
      {"quotes":[
        {...},
        {...}
      ]}

    Бросает ValueError при несоответствии формату.
    """
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    buf = ""
    preamble = ""

    started = False
    finished = False

    async for chunk in request.stream():
        if not chunk:
            continue
        buf += decoder.decode(chunk)
        if finished:
            continue

        if not started:
            idx = buf.find("[")
            if idx == -1:
                preamble += buf
                buf = ""
                if len(preamble) > 100_000:
                    raise ValueError("malformed snapshot: no opening bracket")
                continue
            preamble += buf[:idx]
            buf = buf[idx + 1:]
            started = True

            if '"quotes"' not in preamble:
                raise ValueError("malformed snapshot: missing 'quotes' key")

        # Парсим все завершённые объекты
        while True:
            buf = buf.lstrip()
            if not buf:
                break
            if buf.startswith("]"):
                finished = True
                buf = ""
                break

            end = _find_object_end(buf)
            if end == -1:
                break

            obj_str = buf[:end + 1]
            buf = buf[end + 1:]
            buf = buf.lstrip()
            if buf.startswith(","):
                buf = buf[1:]

            try:
                quote = json.loads(obj_str)
            except json.JSONDecodeError:
                continue
            if isinstance(quote, dict) and "id" in quote and "author" in quote and "text" in quote:
                yield quote

    # Финальный flush декодера
    tail = decoder.decode(b"", final=True)
    if tail:
        buf += tail

    # ⚠️ ДОБАВЛЕНО: финальная обработка остатка буфера
    # (лечит потерю последней записи на границе чанков)
    if started and not finished:
        while True:
            buf = buf.lstrip()
            if not buf:
                break
            if buf.startswith("]"):
                finished = True
                break
            end = _find_object_end(buf)
            if end == -1:
                break
            obj_str = buf[:end + 1]
            buf = buf[end + 1:]
            buf = buf.lstrip()
            if buf.startswith(","):
                buf = buf[1:]
            try:
                quote = json.loads(obj_str)
            except json.JSONDecodeError:
                continue
            if isinstance(quote, dict) and "id" in quote and "author" in quote and "text" in quote:
                yield quote

    if not started:
        raise ValueError("malformed snapshot: no opening bracket")
    if not finished and "]" not in buf:
        raise ValueError("malformed snapshot: unterminated array")


def _find_object_end(s: str) -> int:
    """Возвращает индекс закрывающей } для первого объекта, или -1."""
    depth = 0
    in_string = False
    escape = False
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


async def process_import(request: Request) -> tuple[int, int]:
    """
    Потоковый импорт. Если тело невалидно — ValueError (→ 400),
    состояние откатывается через rollback_snapshot.
    """
    epoch = storage.begin_snapshot()
    imported = 0
    try:
        async for quote in stream_snapshot(request):
            storage.insert_from_snapshot(quote, epoch)
            imported += 1
    except ValueError:
        storage.rollback_snapshot()
        raise

    dropped = storage.finish_snapshot(epoch)
    storage.gc_deleted()
    return imported, dropped