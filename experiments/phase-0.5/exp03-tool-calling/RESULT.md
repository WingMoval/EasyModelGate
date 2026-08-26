# Experiment 03 — Tool Calling Streaming (Qwen + llama.cpp real wire format)

## Purpose

Freeze the Tool Calling passthrough strategy by capturing the REAL wire format of
the current `llama-server` + `qwen3.8-local` stack:

- Non-streaming `tool_calls` structure
- Streaming `delta.tool_calls` fragmentation behavior
- End-to-end confirmation that a real OpenCode agent session still works unchanged

## Environment

| Item | Value |
|---|---|
| Upstream | llama-server @ 127.0.0.1:8080 (`--jinja` tool calling, Qwen3.8-27B) |
| Client | Python 3.12.13 + httpx 0.28.1 |
| OpenCode | v1.18.23, provider `local-qwen/qwen3.8-local` (existing config, untouched) |
| Auth | runtime-loaded from OpenCode provider config (never logged) |
| Date | 2026-08-26 |

## Procedure

Script: `scripts/exp03_tool_calling.py`

```bash
~/.micromamba/envs/easymodelgate-test/bin/python \
  experiments/phase-0.5/exp03-tool-calling/scripts/exp03_tool_calling.py
```

Tool schema: `get_weather(city)` (declared only; never executed by the gateway).
Prompt: "What is the weather in Paris right now? Use the get_weather tool."

Real-agent check:

```bash
mkdir -p /tmp/emg-exp03-dir && echo alpha-data > /tmp/emg-exp03-dir/file_a.txt \
  && echo beta-data > /tmp/emg-exp03-dir/file_b.txt
cd /tmp/emg-exp03-dir
opencode run --model local-qwen/qwen3.8-local \
  "List the files in the current directory using the ls tool, then tell me exactly how many files you see and their names. Do not modify anything."
```

## Raw Observations

### A — Non-stream (`samples/tool-call-nonstream.json`)

HTTP 200. `choices[0].finish_reason = "tool_calls"`.

```json
"tool_calls": [{
  "id": "WS6d…(present)",
  "type": "function",
  "function": {
    "name": "get_weather",
    "arguments": "{\"city\":\"Paris\"}"
  }
}]
```

- `arguments` is a SINGLE JSON-encoded string (not an object).
- Top-level `usage` present.

### B — Stream (`samples/tool-call-stream.sse`, 9 events)

delta.tool_calls fragment sequence (verbatim):

| # | index | id | type | name | arguments fragment |
|---|---|---|---|---|---|
| 1 | 0 | Ofmk…(36ch) | function | get_weather | `{` |
| 2 | 0 | null | null | null | `"city":"` |
| 3 | 0 | null | null | null | `Paris` |
| 4 | 0 | null | null | null | `"` |
| 5 | 0 | null | null | null | `}` |

Then: chunk with `finish_reason="tool_calls"`, then usage chunk (`choices:[]`,
prompt 285 / completion 26 / total 311), then `[DONE]`.

Reassembled arguments parse as valid JSON: `{"city":"Paris"}`.
First fragment carries id+type+name; later fragments carry ONLY `index`+fragment.

### C — Real OpenCode agent run

Terminal log (abridged):

```
> build · qwen3.8-local
$ ls            (no output)
$ ls -la        → file_a.txt, file_b.txt listed
2 files:
1. `file_a.txt`
2. `file_b.txt`
OPENCODE_EXIT=0
```

Full agent loop verified: OpenCode → llama.cpp → Qwen emits tool call → OpenCode
executes `ls` → result returned → Qwen continues (and self-corrected after an empty
first `ls` by retrying `ls -la`) → final answer. No config changes were made or
required; no wire capture attempted (would require touching main config — skipped
per rules).

## Result

```
TOOL_ARGUMENTS_FRAGMENTED   = YES  (5 fragments for one call)
TOOL_CALL_INDEX_PRESENT     = YES  (index=0 on every fragment)
TOOL_CALL_ID_PRESENT        = YES  (first fragment only; later fragments omit it)
FUNCTION_NAME_PRESENT       = YES  (first fragment only)
ARGUMENTS_TYPE              = JSON-encoded STRING, streamed as text fragments
FINISH_REASON               = tool_calls  (non-stream and stream identical)
USAGE_IN_TOOL_STREAM        = YES via include_usage injection
GATEWAY_CONCAT_ARGUMENTS    = NO  (client-side responsibility; confirmed feasible)
GATEWAY_RESERIALIZE         = NO
TOOL_CALL_PASSTHROUGH_STRATEGY =
  Request side : forward tools/tool_choice/parallel_tool_calls/response_format
                 verbatim inside the transparent JSON dict.
  Response/SSE : byte-exact relay (hybrid scanner from EXP-02); gateway never
                 parses delta.tool_calls, never touches index/id/arguments.
  Rationale    : fragments are pure text splits; any re-encoding or chunk-boundary
                 change risks client-side reassembly corruption. Byte passthrough
                 makes corruption structurally impossible.
```

## PASS / FAIL

**PASS** (A, B and C all pass)

## Impact on EasyModelGate v0.1

- Confirms Phase 0 §4: zero tool-call awareness required in v0.1 beyond transparency.
- `finish_reason="tool_calls"` flows through untouched; usage capture works in
  tool-calling streams too (include_usage injection compatible).
- OpenCode compatibility risk rated LOW provided relay is byte-exact (guaranteed by
  EXP-02 hybrid design).

## Files Produced

- samples/tool-call-nonstream.json
- samples/tool-call-stream.sse
- scripts/exp03_tool_calling.py
