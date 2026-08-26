# Experiment 02 — httpx SSE Iterator Comparison

## Purpose

Determine how `httpx` streaming iterators expose the real llama.cpp SSE wire stream,
to freeze the EasyModelGate relay-read design:

- `Response.aiter_raw()` vs `aiter_bytes()` vs `aiter_lines()`
- Does one TCP/HTTP chunk always equal one SSE event?
- Are events ever split across chunks? Do chunks bundle multiple events?
- How are streaming `delta.tool_calls` fragments exposed by each iterator?

## Environment

| Item | Value |
|---|---|
| Upstream | llama-server @ 127.0.0.1:8080 (same build as EXP-01) |
| Client | Python 3.12.13 + httpx 0.28.1, env `easymodelgate-test` |
| Auth | runtime-loaded from OpenCode provider config (never logged) |
| Date | 2026-08-26 |

## Procedure

Script: `scripts/exp02_sse_iterator.py`

```bash
~/.micromamba/envs/easymodelgate-test/bin/python \
  experiments/phase-0.5/exp02-httpx-sse-iterator/scripts/exp02_sse_iterator.py
```

Six captures, each a fresh identical request:

- plain prompt (`include_usage=true`): × {raw, bytes, lines}
- tool-call prompt (`tools=get_weather`, stream): × {raw, bytes, lines}

Per byte-chunk recorded: seq, length, head-bytes, standalone/incremental UTF-8
decodability, count of `\n\n`-terminated events completed inside the chunk,
whether the chunk continued a split event, whether it ended mid-event.

## Raw Observations

Plain stream (5 SSE events total):

| iterator | HTTP chunks | events/chunk | split events |
|---|---|---|---|
| aiter_raw | 3 (502B, 765B, 14B) | 2 / 2 / 1 | none |
| aiter_bytes | 3 (503B≈, same shape) | 2 / 2 / 1 | none |

Tool-call stream (9 SSE events total):

| iterator | HTTP chunks | events/chunk | notable |
|---|---|---|---|
| aiter_raw | 8 | 1,1,1,1,1,1,**2**,1 | chunk#7 (780B) bundles finish chunk + usage chunk |
| aiter_bytes | 8 | same shape | – |
| aiter_lines | 18 line-items | 9 data + 9 blank | blank lines yielded as empty strings |

Key facts:

- `content-encoding: none` from llama.cpp → raw and bytes were byte-identical in
  practice (raw differs from bytes only when upstream compresses; we control the
  request Accept-Encoding, so this is avoidable).
- **TCP chunk ≠ SSE event: CONFIRMED** — multiple SSE events regularly arrive in a
  single HTTP chunk; final `[DONE]\n\n` arrived as its own 14-byte chunk.
- **No event was split across two chunks in these runs** — but this is luck/scheduling,
  not a guarantee; the scanner design must tolerate splits.
- `aiter_lines` preserved order and blank lines (as empty-string items) and stripped
  line terminators; `[DONE]` and the usage line were directly observable.
- No UTF-8 multibyte splits occurred anywhere (all ASCII here; decoder-based check used).

Streaming tool call as seen through `aiter_lines` (delta.tool_calls sequence):

```
event#3: index=0  id="ViwE…"  name="get_weather"  arguments="{"
event#5: index=0  id=None     name=None           arguments="\"city\":\""
event#7: index=0  id=None     name=None           arguments="Paris"
event#9: index=0  id=None     name=None           arguments="\""
event#11:index=0  id=None     name=None           arguments="}"
finish_reason chunk, then usage chunk, then [DONE]
```

→ `arguments` IS fragmented across 5 separate SSE events; only the first carries
`id`/`function.name`; every fragment repeats `index`.

## Result

```
SSE_ITERATOR_RECOMMENDATION      = hybrid
  transport                       = resp.aiter_bytes()
  client output                   = chunk yielded UNCHANGED (byte-exact passthrough)
  metadata                        = read-only incremental scanner fed a copy of the
                                    same bytes (split on b"\n\n", carry partial tail)

SSE_SCANNER_DESIGN               =
  - buffer incomplete tail across chunks (tolerates mid-event splits even though
    none observed)
  - on each complete event: if startswith(b"data:") -> strip prefix;
      * body == "[DONE]"            -> mark done, stop reading upstream
      * b'"usage"' in body          -> json.loads once, extract tokens (EXP-01 format)
      * first data event            -> record TTFT
  - never json.dumps / never rebuild events

INCREMENTAL_SSE_SCANNER_REQUIRED = YES (raw chunk boundaries are not event boundaries)
RAW_BYTES_DIRECT_YIELD_TO_CLIENT = YES
SCANNER_READS_COPY_ONLY          = YES
TCP_CHUNK_EQ_SSE_EVENT           = NO  (disproved)
SINGLE_EVENT_SPLIT_ACROSS_CHUNKS = NOT OBSERVED (must still be handled)
ONE_CHUNK_CONTAINS_MULTI_EVENTS  = YES (observed repeatedly)
```

## PASS / FAIL

**PASS**

## Impact on EasyModelGate v0.1

- Relay loop = one `async for chunk in resp.aiter_bytes()`:
  `yield chunk` (unchanged) + `scanner.feed(chunk)`. Single pass, zero copies beyond
  the scanner's small carry buffer, no re-serialization — satisfies the Phase 0
  principle (no JSON-parse→dump→reconstruct).
- Do not use `aiter_raw` (no benefit; we forbid upstream compression by not sending
  Accept-Encoding, keeping bytes==wire).
- Do not use `aiter_lines` for the relay path (would force re-adding "\n", losing the
  original CRLF/LF form; fine for tests/debug tooling though).

## Files Produced

- samples/plain-raw-chunks.json, samples/plain-bytes-chunks.json, samples/plain-lines-obs.json
- samples/toolcall-raw-chunks.json, samples/toolcall-bytes-chunks.json, samples/toolcall-lines-obs.json
- scripts/exp02_sse_iterator.py
