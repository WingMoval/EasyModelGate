"""EXP-04-A: Fake slow SSE upstream on 127.0.0.1:19081.

Yields one SSE event per second for N seconds (body {"duration": N}, default 60).
Logs its full lifecycle as JSON lines into fake_upstream/runtime_log.jsonl.
"""
import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.responses import StreamingResponse

HERE = Path(__file__).resolve().parent
LOG = HERE / "runtime_log.jsonl"

app = FastAPI()


def log(event: str, detail=None):
    rec = {"ts": time.time(), "side": "upstream", "event": event}
    if detail is not None:
        rec["detail"] = detail
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    duration = int(body.get("duration", 60))
    rid = body.get("request_id", "-")
    log("request_accepted", {"request_id": rid, "duration": duration})

    async def gen():
        try:
            for i in range(duration):
                yield f'data: {{"choices":[{{"delta":{{"content":"t{i}"}}}}]}}\n\n'.encode()
                log("chunk_generated", {"request_id": rid, "seq": i})
                await asyncio.sleep(1.0)
            yield b"data: [DONE]\n\n"
            log("stream_completed_normally", {"request_id": rid})
        except asyncio.CancelledError:
            log("cancelled_error", {"request_id": rid})
            raise
        finally:
            log("generator_finally_connection_closed", {"request_id": rid})

    return StreamingResponse(gen(), media_type="text/event-stream")
