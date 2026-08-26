# EasyModelGate Phase 0.5
# Protocol and Environment Validation Report

Date: 2026-08-26
Status: **PHASE_0_5 = PASS**

---

## 1. Executive Summary

All five pre-development experiments passed against the real environment
(running `llama-server` + Qwen3.8-27B @ 127.0.0.1:8080, and a localhost
fake-upstream/gateway testbed). No result contradicts the Phase 0 research;
two conclusions were refined with measured data (SSE relay read method;
client-disconnect latency), and one new wire-format fact was discovered
(`prompt_tokens_details.cached_tokens`). The technical route for EasyModelGate
v0.1 is now fully determined and safe to freeze into the final specification.

## 2. Environment

| Item | Value |
|---|---|
| Host | Ubuntu 16.04.7 LTS, kernel 4.15.0-139-generic, x86_64, glibc 2.31 |
| Env tool | micromamba 2.9.0 (env: `easymodelgate-test`) |
| Python | 3.12.13 |
| Upstream | llama-server.service ("Qwen3.8-27B on GPU 4-7"), 127.0.0.1:8080, Bearer-auth required (401 without key) |
| Key handling | Read at runtime from existing OpenCode provider config; never printed/logged/persisted in any experiment artifact |
| OpenCode | v1.18.23 (existing config untouched) |

## 3. EXP-01 Streaming Usage

Result constants:

```
STREAM_DEFAULT_HAS_USAGE   = NO
STREAM_INCLUDE_USAGE_TRUE  = YES (final chunk before [DONE])
STREAM_INCLUDE_USAGE_FALSE = NO
USAGE_BEFORE_DONE          = YES
TIMINGS_AVAILABLE          = YES
EASYMODELGATE_USAGE_INJECTION = inject {"stream_options":{"include_usage":true}}
                              when stream=true and client omitted stream_options;
                              parse the choices==[] usage chunk side-band only.
```

Usage chunk shape (verbatim from capture): `{"choices":[],"created":…,"id":…,
"model":…,"system_fingerprint":…,"object":"chat.completion.chunk","usage":
{prompt/completion/total_tokens, prompt_tokens_details.cached_tokens},"timings":{…}}`.
Non-stream responses always carry `usage` + `finish_reason` + `timings`.

**New finding**: this build reports `prompt_tokens_details.cached_tokens`
(KV-cache hits) → v0.1 request_logs should add a `cached_tokens` column.

## 4. EXP-02 SSE Iterator

Measured facts:

- TCP chunk ≠ SSE event: chunks regularly bundle multiple SSE events
  (e.g., one 780 B chunk carried finish-chunk + usage-chunk); final `[DONE]`
  arrived as its own 14-byte chunk.
- No event was observed split across two HTTP chunks — but the design must not
  rely on that.
- `aiter_raw` vs `aiter_bytes`: identical here (`content-encoding: none`); raw is
  unnecessary because EMG controls upstream headers (no compression requested).
- `aiter_lines` preserves order/blanks but strips terminators → unsuitable as the
  relay transport (would force newline reconstruction).

Decision:

```
SSE_ITERATOR     = hybrid: transport = resp.aiter_bytes() yielded UNCHANGED to the client;
                   metadata = read-only incremental scanner fed a copy of the same bytes
SSE_SCANNER      = \n\n-delimited event splitter with partial-tail carry buffer;
                   per complete "data:" event: [DONE] detection / TTFT mark /
                   one-shot json.loads ONLY when b'"usage"' substring present.
                   No JSON re-serialization anywhere.
```

## 5. EXP-03 Tool Calling

Real wire format captured (non-stream JSON + full SSE):

```
TOOL_ARGUMENTS_FRAGMENTED   = YES (5 fragments: '{' , '"city":"' , 'Paris' , '"' , '}')
TOOL_CALL_INDEX_PRESENT     = YES (every fragment)
TOOL_CALL_ID_PRESENT        = YES (first fragment only)
FUNCTION_NAME_PRESENT       = YES (first fragment only)
ARGUMENTS_TYPE              = single JSON-encoded string, streamed as text pieces
FINISH_REASON               = tool_calls (stream & non-stream identical)
```

Real-agent verification: `opencode run` executed a read-only ls task end-to-end
(tool call → execution → result feedback → continuation → correct final answer),
exit 0, using its existing config unchanged.

## 6. EXP-04 Client Disconnect

Testbed: fake slow upstream :19081 (1 event/s) ← temp gateway :19080 implementing
the candidate relay (FastAPI StreamingResponse + httpx.AsyncClient.stream).

Measured propagation for an abrupt client close at t:

```
gateway_detection_ms            = 2
upstream_close_ms               = 0
total_disconnect_propagation_ms = 2
chain_complete                  = true   (fake upstream generator got CancelledError)
```

Normal-completion case unaffected (all chunks + [DONE], no spurious cancels).

Logging survival (EXP-04-E): request-log write spawned as a detached
`asyncio.create_task` from the relay generator's `finally` completed 1.0 s after
the disconnect with `error_type="client_disconnected"` — no message queue needed.

```
CLIENT_DISCONNECT_STRATEGY =
  async generator:
    try: async for chunk in upstream.aiter_bytes(): yield chunk
    except asyncio.CancelledError: raise
    finally:
        await upstream_resp.aclose()
        asyncio.get_running_loop().create_task(persist_request_log(...))  # detached
```

## 7. EXP-05 Python Environment

```
RECOMMENDED_PYTHON     = 3.12.13 (micromamba env easymodelgate-test; 3.11 fallback not needed)
FASTAPI_VERSION        = 0.141.1
STARLETTE_VERSION      = 1.6.0
HTTPX_VERSION          = 0.28.1
UVICORN_VERSION        = 0.52.4
AIOSQLITE_VERSION      = 0.22.1
PYTEST_VERSION         = 9.1.1
PYTEST_ASYNCIO_VERSION = 1.4.0
SQLITE_VERSION         = 3.53.2
OLD_OS_BLOCKER         = NO   (kernel 4.15 + glibc 2.31 fine for cp312 wheels)
```

HTTP smoke 200 OK; SQLite WAL persists across reopen; install produced zero
wheel/compiler/OpenSSL issues.

## 8. Final Technical Decisions

```
SSE_ITERATOR                     = aiter_bytes passthrough + read-only scanner (hybrid)
SSE_SCANNER_DESIGN               = incremental \n\n event splitter w/ carry buffer;
                                   side-band [DONE]/TTFT/usage extraction; never reserialize
STREAM_USAGE_STRATEGY            = inject stream_options.include_usage when absent (stream=true);
                                   parse trailing choices==[] usage chunk; log tokens +
                                   cached_tokens; forward chunk unchanged; NULL on absence
TOOL_CALL_PASSTHROUGH_STRATEGY   = fully transparent dict passthrough; byte-exact SSE relay;
                                   gateway never parses/concats/reserializes delta.tool_calls
CLIENT_DISCONNECT_STRATEGY       = Starlette-driven cancellation; finally{await aclose()};
                                   detached create_task for request logging
PYTHON_VERSION                   = 3.12.13 via micromamba (env easymodelgate-test pattern)
DEPENDENCY_VERSIONS              = fastapi 0.141.1 / starlette 1.6.0 / httpx 0.28.1 /
                                   uvicorn 0.52.4 / aiosqlite 0.22.1 / pydantic 2.13.4 /
                                   pytest 9.1.1 / pytest-asyncio 1.4.0 (all == pinned)
SQLITE_MODE                      = WAL + busy_timeout=5000 + synchronous=NORMAL (verified persistent)
```

## 9. Differences From Phase 0 Research

No contradictions with `docs/research/EasyModelGate-v0.1-Phase0-Technical-Research.md`.
Refinements/additions (recorded here only; Phase 0 report intentionally unmodified):

1. Relay read method refined: Phase 0 sketched "line passthrough"; EXP-02 showed
   line-mode forces newline reconstruction and hides real chunking. Final choice:
   byte-chunk passthrough + incremental scanner (superset of the original intent,
   stronger transparency guarantee).
2. Disconnect propagation was predicted reliable; now MEASURED at ≈2 ms end-to-end
   on localhost, with the exact generator pattern validated by execution.
3. New wire fact absent from Phase 0: `usage.prompt_tokens_details.cached_tokens`
   and `timings.cache_n` are emitted by this llama.cpp build → schema should add
   `cached_tokens` (and optionally keep timings out of scope).
4. Phase 0's httpx-default-timeout warning confirmed relevant during scripting
   (explicit `Timeout(connect=5, write=30, read=None, pool=10)` used everywhere).

## 10. Required Changes to v0.1 Specification

1. Add `cached_tokens INTEGER` column to `request_logs` (+ include in analytics sums optionally).
2. Specify relay loop normatively as: `aiter_bytes()` → yield unchanged → feed scanner copy.
3. Specify usage injection rule: only when `stream==true` AND client did not set `stream_options`;
   forward the resulting usage chunk unchanged (do NOT strip).
4. Specify timeout profile: connect 5s / write 60s / read None / pool 10s + configurable
   total-request deadline.
5. Specify request-log persistence as detached task created in relay `finally`.
6. Freeze dependency pins listed above; micromamba env spec (`python=3.12`).

## 11. Remaining Risks

1. Real-chain integration (OpenCode → EMG → llama.cpp) not yet exercised — deferred
   by design to v0.1 test matrix #19 (EXP-04 proved mechanism on testbed only).
2. Event-split-across-chunks never observed but possible under load; scanner already
   tolerates it (carry buffer) — covered by future unit tests rather than more experiments.
3. uvloop/httptools extras intentionally not installed; plain asyncio performance is
   sufficient for the <20 ms overhead target (GPU-bound service).
4. `parallel>1` behavior of upstream untested (out of v0.1 scope; Semaphore design unaffected).

## 12. Final Decision

**PHASE_0_5 = PASS**

All phase-gate conditions met; development of EasyModelGate v0.1 may proceed to
specification freeze.

---

## Appendix A — Recommended protocol samples for long-term archive (docs/protocol/)

Pending review; do NOT auto-copy yet.

| Sample | Reason |
|---|---|
| exp01/samples/stream-without-stream-options.sse | default streaming baseline |
| exp01/samples/stream-include-usage-true.sse | canonical streaming usage chunk format |
| exp01/samples/stream-include-usage-false.sse | opt-out proof |
| exp01/samples/non-stream-response.json | canonical non-stream envelope (usage+finish_reason+timings) |
| exp03/samples/tool-call-nonstream.json | canonical non-stream tool_calls structure |
| exp03/samples/tool-call-stream.sse | canonical delta.tool_calls fragmentation evidence |
| exp02/samples/plain-lines-obs.json, exp02/samples/toolcall-lines-obs.json | iterator semantics evidence |
| exp04/samples/disconnect_metrics.json | disconnect-latency measurement record |
