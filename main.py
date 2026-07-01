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

# ------------------------------------------------------------------
# CORS
# ------------------------------------------------------------------

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Expose-Headers": "Retry-After",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    response = await call_next(request)

    for k, v in CORS_HEADERS.items():
        response.headers[k] = v

    return response

@app.options("/{path:path}")
async def options(path: str):
    return Response(status_code=204, headers=CORS_HEADERS)

# ------------------------------------------------------------------
# Storage
# ------------------------------------------------------------------

orders = {}
next_order_id = 1

rate_buckets = {}

# ------------------------------------------------------------------
# Rate Limiter
# ------------------------------------------------------------------

@app.middleware("http")
async def rate_limit(request: Request, call_next):

    # Never rate limit OPTIONS
    if request.method == "OPTIONS":
        return await call_next(request)

    # Only rate limit /orders
    if request.url.path != "/orders":
        return await call_next(request)

    client = request.headers.get("X-Client-Id", "anonymous")

    now = time.time()

    timestamps = rate_buckets.get(client, [])
    timestamps = [t for t in timestamps if now - t < WINDOW]

    if len(timestamps) >= RATE_LIMIT:

        retry = max(1, int(WINDOW - (now - timestamps[0])) + 1)

        headers = dict(CORS_HEADERS)
        headers["Retry-After"] = str(retry)

        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers=headers,
        )

    timestamps.append(now)
    rate_buckets[client] = timestamps

    return await call_next(request)

# ------------------------------------------------------------------
# Root
# ------------------------------------------------------------------

@app.get("/")
def root():
    return {
        "status": "ok"
    }

# ------------------------------------------------------------------
# Idempotent POST
# ------------------------------------------------------------------

@app.post("/orders", status_code=201)
def create_order(
    idempotency_key: str = Header(..., alias="Idempotency-Key")
):

    global next_order_id

    if idempotency_key in orders:
        return orders[idempotency_key]

    order = {
        "id": next_order_id,
        "status": "created"
    }

    next_order_id += 1

    orders[idempotency_key] = order

    return order

# ------------------------------------------------------------------
# Pagination
# ------------------------------------------------------------------

@app.get("/orders")
def get_orders(
    limit: int = 10,
    cursor: str | None = None,
):

    limit = max(1, min(limit, TOTAL_ORDERS))

    if cursor is None:
        start = 1
    else:
        try:
            start = int(base64.b64decode(cursor.encode()).decode())
        except Exception:
            start = 1

    end = min(start + limit - 1, TOTAL_ORDERS)

    items = [
        {
            "id": i,
            "status": "catalog"
        }
        for i in range(start, end + 1)
    ]

    if end >= TOTAL_ORDERS:
        next_cursor = None
    else:
        next_cursor = base64.b64encode(
            str(end + 1).encode()
        ).decode()

    return {
        "items": items,
        "next_cursor": next_cursor
    }

# ------------------------------------------------------------------
# Local Run
# ------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
    )
