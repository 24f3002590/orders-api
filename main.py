from fastapi import FastAPI, Header, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import base64
import time
import os

TOTAL_ORDERS = 49
RATE_LIMIT = 15
WINDOW = 10

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

orders = {}
next_id = 1
buckets = {}


@app.options("/{path:path}")
async def options(path: str):
    return Response(status_code=204)


@app.middleware("http")
async def limiter(request: Request, call_next):

    if request.method == "OPTIONS":
        return await call_next(request)

    if request.url.path != "/orders":
        return await call_next(request)

    client = request.headers.get("X-Client-Id", "anonymous")

    now = time.time()

    ts = buckets.get(client, [])
    ts = [t for t in ts if now - t < WINDOW]

    if len(ts) >= RATE_LIMIT:
        retry = max(1, int(WINDOW - (now - ts[0])) + 1)
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={"Retry-After": str(retry)},
        )

    ts.append(now)
    buckets[client] = ts

    return await call_next(request)


@app.get("/")
def root():
    return {"status": "ok"}


@app.post("/orders", status_code=201)
def create_order(idempotency_key: str = Header(..., alias="Idempotency-Key")):
    global next_id

    if idempotency_key in orders:
        return orders[idempotency_key]

    order = {
        "id": next_id,
        "status": "created",
    }

    next_id += 1

    orders[idempotency_key] = order

    return order


@app.get("/orders")
def get_orders(limit: int = 10, cursor: str | None = None):

    limit = max(1, limit)

    if cursor:
        try:
            start = int(base64.b64decode(cursor).decode())
        except Exception:
            start = 1
    else:
        start = 1

    end = min(start + limit - 1, TOTAL_ORDERS)

    items = [{"id": i, "status": "catalog"} for i in range(start, end + 1)]

    next_cursor = None
    if end < TOTAL_ORDERS:
        next_cursor = base64.b64encode(str(end + 1).encode()).decode()

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
    )
