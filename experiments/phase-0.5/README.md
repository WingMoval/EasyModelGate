# EasyModelGate — Phase 0.5 Experiments

Protocol & environment validation before v0.1 development freeze.

Status: **all 5 experiments completed — see REPORT.md**

| Dir | Experiment | Result |
|---|---|---|
| exp01-streaming-usage | llama.cpp Streaming Usage wire behavior | PASS |
| exp02-httpx-sse-iterator | httpx SSE iterator comparison (raw/bytes/lines) | PASS |
| exp03-tool-calling | Tool Calling streaming wire format + real OpenCode run | PASS |
| exp04-client-disconnect | Client disconnect propagation via temp gateway + fake upstream | PASS |
| exp05-python-environment | Python/FastAPI stack compatibility (micromamba, py3.12) | PASS |

Rules honored: no changes to llama.cpp / OpenCode / systemd / GPU / system packages;
upstream API key read only at runtime from the existing OpenCode provider config and
never printed or persisted.
