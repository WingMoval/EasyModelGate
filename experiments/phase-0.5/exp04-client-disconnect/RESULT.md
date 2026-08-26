# Experiment 04 — Client Disconnect Propagation

## Purpose

Prove the full cancellation chain required for EasyModelGate:

```
Client disconnect → Gateway stops relay → upstream response aclose → upstream stops generating
```

and that request-logging survives the streaming-task cancellation without any
message queue.

## Environment

| Item | Value |
|---|---|
| Fake upstream | FastAPI/uvicorn @ 127.0.0.1:19081, 1 SSE event/sec for N sec (`fake_upstream/app.py`) |
| Temporary gateway | FastAPI StreamingResponse + httpx.AsyncClient.stream @ 127.0.0.1:19080 (`test_gateway/app.py`) — the exact candidate EMG relay design |
| Client | httpx AsyncClient inside orchestrator |
| Runtime | Python 3.12.13, fastapi 0.141.1, starlette 1.6.0, uvicorn 0.52.4, httpx 0.28.1 (env `easymodelgate-test`) |
| Date | 2026-08-26 |

## Procedure

```bash
~/.micromamba/envs/easymodelgate-test/bin/python \
  experiments/phase-0.5/exp04-client-disconnect/scripts/run_exp04.py
```

Orchestrator boots both servers as subprocesses, then runs:

- Case C (normal): stream `duration=3`, read to `[DONE]`.
- Case D (cancel): stream `duration=60`, read for 3.5 s, then abruptly `aclose()`
  the client-side response. All three components write timestamped lifecycle logs;
  orchestrator correlates them into `samples/disconnect_metrics.json`.
- Case E (logging): gateway schedules the "request log" write as an independent
  `asyncio.create_task` (with simulated 1 s IO delay) from the relay generator's
  `finally`; verified it lands after cancellation with correct `error_type`.

## Raw Observations

Case C (normal completion):

```
chunks_received=4 (3 ticks + [DONE])   wall=3035 ms
gateway_finished_normally=true
upstream_completed_normally=true       no_disconnect_events=true
request_log entry: error_type=null
```

Case D (client cancel at T):

```
T_client_disconnect        = …321.6962
T_gateway_detected         = …321.6983   (CancelledError in relay gen)
T_upstream_aclosed         = …321.6985   (await resp.aclose() done)
T_fake_upstream_stopped    = …321.6983   (its generator got CancelledError)

gateway_detection_ms            = 2
upstream_close_ms               = 0
total_disconnect_propagation_ms = 2      (client FIN → upstream generator dead)
chain_complete                  = true

post_disconnect_req_log (written 1.000 s AFTER disconnect, task survived):
{"request_id":"case-cancel","error_type":"client_disconnected",…}
```

Upstream-side log confirms the generator observed `cancelled_error` then ran its
`generator_finally_connection_closed` — i.e., generation really stopped instead of
continuing for the remaining ~57 s of the requested duration.

## Result

```
CLIENT_DISCONNECT_PROPAGATION = WORKING
CHAIN client→gateway→aclose→upstream-stop = VERIFIED END-TO-END
gateway_detection_ms ≈ 2 ms (event-driven, Starlette listen_for_disconnect)
total_disconnect_propagation_ms ≈ 2 ms (localhost; bounded by TCP, not by tick)
LOG_SURVIVES_STREAM_CANCEL     = YES (independent asyncio.create_task, no queue)
MINIMUM_RELIABLE_IMPLEMENTATION=
  async def gen():
      try:
          async for chunk in upstream.aiter_bytes(): yield chunk
      except asyncio.CancelledError:
          raise
      finally:
          await upstream_resp.aclose()
          loop.create_task(persist_request_log(...))   # NOT awaited here
```

## PASS / FAIL

**PASS** — meets the phase gate condition exactly as specified.

## Impact on EasyModelGate v0.1

- Adopts the above generator shape verbatim for `/v1/chat/completions` relay.
- Request-log writes must be spawned as detached tasks from `finally` (optionally
  wrapped in a small in-memory queue later); never `await`ed inside the cancelled
  scope. No message queue introduced — requirement satisfied.
- GPU-idle risk (Phase 0 Risk #1) mitigated by construction; real-llama.cpp spot
  check recommended during integration testing (Phase v0.1 test matrix #11).

## Files Produced

- fake_upstream/app.py (+ runtime_log.jsonl, server.log)
- test_gateway/app.py (+ runtime_log.jsonl, request_log.jsonl, server.log)
- scripts/run_exp04.py
- samples/disconnect_metrics.json
