"""Мок-каталог с режимами ok/503/hang и логом запросов."""

import time
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI()

QUOTES = {
    "q-9999999": {
        "id": "q-9999999",
        "author": "Тест",
        "text": "Цитата из каталога",
    },
    "q-8888888": {
        "id": "q-8888888",
        "author": "Сенека",
        "text": "Учись радоваться.",
    },
}

# Режим: "ok" | "503" | "hang"
MODE = {"value": "ok"}
# Retry-After (секунды) для 503
RETRY_AFTER = {"value": 5}
# Счётчик входящих запросов
REQUESTS = []


@app.get("/quote/{quote_id}")
async def get_quote(quote_id: str, request: Request):
    REQUESTS.append({
        "t": time.monotonic(),
        "id": quote_id,
    })

    mode = MODE["value"]

    if mode == "hang":
        # Просто висим — клиент упрётся в свой таймаут
        import asyncio
        await asyncio.sleep(3600)
        return {"never": "reached"}

    if mode == "503":
        return JSONResponse(
            status_code=503,
            content={"detail": "busy"},
            headers={"Retry-After": str(RETRY_AFTER["value"])},
        )

    # mode == "ok"
    quote = QUOTES.get(quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="not found")
    return quote


# ---------- admin ----------

@app.post("/admin/mode")
async def set_mode(payload: dict):
    mode = payload.get("mode", "ok")
    if mode not in ("ok", "503", "hang"):
        raise HTTPException(400, "mode must be ok | 503 | hang")
    MODE["value"] = mode
    return {"mode": mode}


@app.post("/admin/retry-after")
async def set_retry_after(payload: dict):
    RETRY_AFTER["value"] = int(payload.get("seconds", 5))
    return {"retry_after": RETRY_AFTER["value"]}


@app.get("/admin/log")
async def get_log():
    """Лог запросов — для проверки, долбит ли витрина каталог."""
    return {
        "total": len(REQUESTS),
        "requests": REQUESTS[-100:],  # последние 100
    }


@app.post("/admin/clear-log")
async def clear_log():
    REQUESTS.clear()
    return {"cleared": True}