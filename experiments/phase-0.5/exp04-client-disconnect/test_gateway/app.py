"""EXP-04-B: Temporary minimal gateway on 127.0.0.1:19080.

Client -> this gateway (FastAPI StreamingResponse + httpx.AsyncClient.stream)
       -> fake slow upstream (19081)

Validates the exact candidate relay design of EasyModelGate v0.1, including:
- client-disconnect propagation (cancel -> finally -> upstream aclose)
- post-disconnect request-log persistence via an un-awaited background task
"""
import asyncio
import json
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from starlette.responses import StreamingResponse

HERE = Path(__file__).resolve().parent
LOG = HERE / "runtime_log.jsonl"
REQ_LOG = HERE / "request_log.jsonl"
UPSTREAM = "http://127.0.0.1:19081/v1/chat/completions"

app = FastAPI()
client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5.0, write=30.0, read=None, pool=10.0)
)


def log(event: str, rid="-", extra=None):
    rec = {"ts": time.time(), "side": "gateway", "event": event, "request_id": rid}
    if extra is not None:
        rec["extra"] = extra
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


async def persist_request_log(request_id: str, error_type, started_at: float):
    """Simulated request-log write. Runs as an INDEPENDENT task so that it
    survives the cancellation of the streaming relay generator."""
    try:
        await asyncio.sleep(1.0)  # simulate slow SQLite/IO write
        rec = {
            "ts": time.time(),
            "request_id": request_id,
            "started_at": started_at,
            "error_type": error_type,
        }
        with open(REQ_LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
        log("request_log_persisted", rid, {"error_type": error_type})
    except Exception as e:
        log("request_log_persist_FAILED", rid, {"err": repr(e)})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def relay(request: Request):
    body = await request.json()
    rid = body.get("request_id", "-")
    started_at = time.time()
    log("relay_started", rid)

    upstream_resp = await client.send(
        client.build_request("POST", UPSTREAM, json=body), stream=True
    )
    log("upstream_status", rid, {"status": upstream_resp.status_code})

    async def gen():
        cancelled = False
        try:
            async for chunk in upstream_resp.aiter_bytes():
                log("chunk_relayed", rid, {"bytes": len(chunk)})
                yield chunk
            log("relay_finished_normally", rid)
        except asyncio.CancelledError:
            cancelled = True
            log("client_disconnect_detected", rid)  # T_gateway_cancel
            raise
        finally:
            await upstream_resp.aclose()            # T_upstream_aclose
            log("upstream_aclosed", rid)
            err = "client_disconnected" if cancelled else None
            asyncio.get_running_loop().create_task(
                persist_request_log(rid, err, started_at)
            )

    return StreamingResponse(gen(), media_type="text/event-stream")
