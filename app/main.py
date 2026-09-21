import time
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.storage import storage
from app.catalog import catalog, CatalogUnavailable
from app.import_service import process_import
from app.config import TTL_SECONDS

app = FastAPI()

# ---- метрики ----
_stats = {
    "served_local": 0,
    "served_from_catalog": 0,
    "catalog_reads": 0,
}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/catalog/source")
async def set_source(payload: dict):
    url = payload.get("url")
    if not url:
        raise HTTPException(400, "url required")
    catalog.set_source(url)
    return {"source": url}


@app.post("/import")
async def import_snapshot(request: Request):
    try:
        imported, dropped = await process_import(request)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"imported": imported, "dropped": dropped}


@app.put("/catalog/{quote_id}")
async def put_quote(quote_id: str, payload: dict):
    author = payload.get("author")
    text = payload.get("text")
    if not isinstance(author, str) or not (1 <= len(author) <= 200):
        raise HTTPException(422, "author length 1..200")
    if not isinstance(text, str) or not (1 <= len(text) <= 16384):
        raise HTTPException(422, "text length 1..16384")

    record = {"id": quote_id, "author": author, "text": text}
    # сохраняем остальные поля, если есть
    for k, v in payload.items():
        if k not in ("author", "text"):
            record[k] = v

    storage.put(record)
    return _public(record)


@app.delete("/catalog/{quote_id}")
async def delete_quote(quote_id: str):
    ok = storage.delete(quote_id)
    if not ok:
        raise HTTPException(404, "not found")
    return {"deleted": True}


@app.get("/quotes/{quote_id}")
async def get_quote(quote_id: str, response: Response):
    # 1. Локально
    local = storage.get(quote_id)
    if local is not None and storage.is_fresh(local, TTL_SECONDS):
        _stats["served_local"] += 1
        response.headers["X-Source"] = "LOCAL"
        return _public(local)

    # 2. Идём в каталог
    _stats["catalog_reads"] += 1
    try:
        remote = await catalog.fetch_quote(quote_id)
    except CatalogUnavailable:
        remote = None

    if remote is not None:
        storage.put(remote)
        _stats["served_from_catalog"] += 1
        response.headers["X-Source"] = "CATALOG"
        return _public(remote)

    # 3. Если локально есть, но просрочено — отдаём как LOCAL (fallback)
    if local is not None:
        _stats["served_local"] += 1
        response.headers["X-Source"] = "LOCAL"
        return _public(local)

    raise HTTPException(404, "not found")


@app.get("/stats")
async def stats():
    return {
        "served_local": _stats["served_local"],
        "served_from_catalog": _stats["served_from_catalog"],
        "catalog_reads": _stats["catalog_reads"],
        "evictions": storage.evictions(),
        "local": storage.count(),
        "bytes": storage.bytes_used(),
        "catalog": storage.count(),
    }


def _public(q: dict) -> dict:
    """Убираем внутренние поля перед отдачей читателю."""
    return {k: v for k, v in q.items() if not k.startswith("_")}