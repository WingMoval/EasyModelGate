# Changelog

All notable changes to EasyModelGate are documented here.

## [0.1.0] - 2026-08-26

First public release.

### Added

- OpenAI-compatible proxy for llama.cpp server (`/v1/chat/completions`,
  `/v1/models`, `/health`)
- API Key authentication (`emg_` keys, SHA-256 hash storage, show-once)
- Streaming passthrough with byte-exact fidelity (`aiter_bytes` +
  read-only incremental SSE scanner)
- Tool Calling transparent passthrough (zero re-serialization)
- Client disconnect cancellation propagated to upstream
- Request logging (status / tokens / cached_tokens / TTFT /
  queue_wait_ms / upstream_duration_ms)
- Concurrency queue with `upstream.slots` semaphore
- RPM limit (in-memory fixed window) and Soft Token Quota
- CLI management: user / key / usage summary
- Usage Analytics (hour/day/week/month/custom, ISO week correct)
- SQLite persistence (WAL) with schema v1
- systemd deployment templates (user & system level)
- 118 automated tests (fake upstream based, no GPU required)
- Real OpenCode A/B integration validation (8 scenarios)

### Known Limitations

- llama.cpp is the officially validated backend
- single-instance in-memory RPM (window resets on restart)
- Soft Token Quota (no reservation)
- no Admin API / Web Dashboard
- no HA / multi-node support
