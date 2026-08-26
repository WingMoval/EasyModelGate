# Experiment 01 — llama.cpp Streaming Usage

## Purpose

Determine the actual Usage wire behavior of the currently running llama.cpp build
(`llama-server.service`, Qwen3.8-27B, `127.0.0.1:8080`), specifically:

- Does a default streaming response (`stream=true`, no `stream_options`) contain `usage`?
- Is `stream_options.include_usage` honored (true → usage present, false → absent)?
- Where does the usage chunk appear relative to `[DONE]`?
- What is the exact structure of the usage chunk?
- What does the non-streaming response contain?

## Environment

| Item | Value |
|---|---|
| Upstream | llama-server @ 127.0.0.1:8080 (systemd unit `llama-server.service`, "Qwen3.8-27B on GPU 4-7") |
| Model id | `qwen3.8-local` |
| Auth | Bearer key read at runtime from existing OpenCode provider config (`~/.config/opencode/opencode.jsonc` → `.provider.local-qwen.options.apiKey`). Key never printed/logged/written. |
| Client | Python 3.12.13 + httpx 0.28.1 (micromamba env `easymodelgate-test`) |
| Date | 2026-08-26 |

## Procedure

Script: `scripts/exp01_streaming_usage.py`

Reproduce (key is resolved by the script from the config file; no manual copy):

```bash
~/.micromamba/envs/easymodelgate-test/bin/python \
  experiments/phase-0.5/exp01-streaming-usage/scripts/exp01_streaming_usage.py
```

Four probes against `POST /v1/chat/completions`, prompt `Reply with exactly: hello`,
`max_tokens=32`:

- A: `stream=true`, no `stream_options`
- B: `stream=true`, `"stream_options":{"include_usage":true}`
- C: `stream=true`, `"stream_options":{"include_usage":false}`
- D: `stream=false`

Full SSE bodies / JSON responses saved to `samples/`.

## Raw Observations

All four probes returned HTTP 200.

| Probe | Content-Type | data lines | [DONE] | usage chunk | timings |
|---|---|---|---|---|---|
| A default | text/event-stream | 4 | yes | **absent** | present (in content/finish chunks) |
| B include=true | text/event-stream | 5 | yes | **present**, index 3 of 4 (before DONE) | present |
| C include=false | text/event-stream | 4 | yes | **absent** | present |
| D non-stream | application/json | – | – | present | present |

Usage chunk raw structure (probe B, verbatim fields):

```json
{
  "choices": [],
  "created": 1787676065,
  "id": "chatcmpl-…",
  "model": "qwen3.8-local",
  "system_fingerprint": "b0-unknown",
  "object": "chat.completion.chunk",
  "usage": {
    "completion_tokens": 2,
    "prompt_tokens": 17,
    "total_tokens": 19,
    "prompt_tokens_details": { "cached_tokens": 13 }
  },
  "timings": {
    "cache_n": 13, "prompt_n": 4, "prompt_ms": 279.723,
    "prompt_per_token_ms": 69.93, "prompt_per_second": 14.29,
    "predicted_n": 2, "predicted_ms": 95.586,
    "predicted_per_token_ms": 95.586, "predicted_per_second": 10.46
  }
}
```

Non-stream (probe D): top-level keys `choices, created, id, model, object,
system_fingerprint, timings, usage`; `choices[0].finish_reason = "stop"`.

Note: this build also emits `prompt_tokens_details.cached_tokens` (KV-cache reuse),
and `timings.cache_n`. Useful for future cache analytics.

## Result

```
STREAM_DEFAULT_HAS_USAGE      = NO
STREAM_INCLUDE_USAGE_TRUE     = YES (final chunk, choices==[], before [DONE], includes timings)
STREAM_INCLUDE_USAGE_FALSE    = NO
USAGE_BEFORE_DONE             = YES
TIMINGS_AVAILABLE             = YES (both stream and non-stream)
NONSTREAM_HAS_USAGE           = YES (always, plus finish_reason)
EASYMODELGATE_USAGE_INJECTION = YES — inject {"stream_options":{"include_usage":true}}
                                when client omitted stream_options and stream=true;
                                parse the choices==[] usage chunk side-band for logging;
                                forward it to the client unchanged (valid OpenAI format).
```

## PASS / FAIL

**PASS** — behavior is deterministic and matches Phase 0 research prediction
(llama.cpp PR #16052 semantics confirmed on the actual build).

## Impact on EasyModelGate v0.1

- Confirms Strategy C from Phase 0 §9: zero-cost official mechanism for token accounting.
- Gateway must NOT recompute tokens; NULL only if upstream misbehaves.
- `prompt_tokens_details.cached_tokens` should be logged in request_logs as an extra
  column (cheap, enables future cache-hit analytics). Schema addition noted.
- The usage chunk is safe to forward: OpenAI SDK clients tolerate the trailing
  empty-choices chunk when they requested include_usage; when we inject it without
  the client asking, it remains spec-valid output (OpenCode/OpenAI SDKs handle
  `choices: []` chunks).

## Files Produced

- samples/stream-without-stream-options.sse
- samples/stream-include-usage-true.sse
- samples/stream-include-usage-false.sse
- samples/non-stream-response.json
- scripts/exp01_streaming_usage.py
