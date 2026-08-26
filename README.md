# EasyModelGate

English | [简体中文](README.zh-CN.md)

A lightweight API gateway for local OpenAI-compatible model servers,
officially validated with **llama.cpp**.

## Overview

EasyModelGate sits between clients such as OpenCode and a local
llama.cpp server. It does not load models or manage GPUs — it adds the
operational layer that a bare model server lacks:

```
OpenCode / OpenAI-compatible Client
        ↓
EasyModelGate  (:3000)
        ↓
llama.cpp server  (:8080)
        ↓
Local Model (Qwen etc.)
```

Core principle: **transparent proxy first**. EasyModelGate never modifies
model output or Tool Calling content. Streaming SSE and Tool Calling
arguments are relayed byte-exact.

## Why EasyModelGate

Connecting straight to a local model server leaves you without:

- authentication
- per-key rate limiting
- queueing with visibility (`queue_wait_ms`)
- token usage accounting (incl. `cached_tokens`)
- request observability (status / duration / TTFT / upstream status)
- quota control
- client-disconnect propagation to stop wasted GPU inference

EasyModelGate adds all of the above **without modifying model protocol
content**.

## Features

- API Key authentication (`emg_` keys, SHA-256 hash storage, show-once)
- OpenAI-compatible proxy (`/v1/chat/completions`, `/v1/models`, `/health`)
- Non-streaming and Streaming support
- Byte-preserving SSE relay with read-only incremental scanner
- Tool Calling passthrough (zero concatenation, zero re-serialization)
- Client Disconnect cancellation (propagated to upstream)
- Concurrency queue via configurable slots semaphore
- Metrics: `queue_wait_ms`, `upstream_duration_ms`, `ttft_ms`
- Usage: prompt / completion / total tokens + `cached_tokens`
- RPM limiting (in-memory fixed window)
- Soft Token Quota per key
- CLI management: users / keys / usage analytics
- Usage Analytics: hour / day / ISO week / month / custom ranges
- SQLite persistence (WAL) with schema v1
- systemd deployment templates (user & system level)

## Architecture

EasyModelGate does not load models itself.
It forwards requests to an upstream llama.cpp OpenAI-compatible API and
relays responses byte-exact while observing them side-band for metrics.
See [docs/decisions](docs/decisions/) for design rationale
(SSE relay, disconnect propagation, key storage).

## Requirements

- Linux
- Python 3.12
- A running llama.cpp server exposing an OpenAI-compatible API

micromamba is recommended for environment management but is not a hard
dependency of the program itself.

EasyModelGate does **not**: download models, load GGUF files,
install CUDA/NVIDIA drivers, schedule GPUs, or compile llama.cpp.

## Quick Start

```bash
# Get the code
git clone https://github.com/WingMoval/EasyModelGate.git
cd EasyModelGate

# Create a Python 3.12 environment
micromamba create -y -n easymodelgate python=3.12.13
$HOME/micromamba/envs/easymodelgate/bin/pip install -r requirements.txt

# Configure
cp configs/config.example.toml configs/config.toml   # edit base_url / port

# Upstream secret (pick one; skip if your llama-server has no --api-key)
echo <key> > configs/upstream_key && chmod 600 configs/upstream_key
# or: export EMG_UPSTREAM_API_KEY=<key>

# Create a user and an API key (the full key is shown exactly once)
PY=$HOME/micromamba/envs/easymodelgate/bin/python
$PY -m easymodelgate --config configs/config.toml user create --username alice
$PY -m easymodelgate --config configs/config.toml key create --user alice \
    --name laptop

# Start the gateway (default :3000)
$PY -m easymodelgate --config configs/config.toml serve

# Verify
curl http://127.0.0.1:3000/health
curl http://127.0.0.1:3000/v1/models -H "Authorization: Bearer emg_xxx"
curl http://127.0.0.1:3000/v1/chat/completions \
     -H "Authorization: Bearer emg_xxx" -H "Content-Type: application/json" \
     -d '{"model":"<upstream-model>","messages":[{"role":"user","content":"hi"}]}'
```

## OpenCode Integration

Point an OpenCode provider at the gateway:

```
baseURL = http://127.0.0.1:3000/v1
apiKey  = emg_...
```

Keep a second provider pointing directly at llama.cpp as an instant
rollback path — switching back requires no client changes beyond the
provider selection.

## Testing

```bash
python -m pytest -q
```

Current v0.1.0 baseline: **118 passed**.
The automated test suite uses a programmable fake upstream and does not
require a GPU or a real llama.cpp process.

## Security

- Plaintext user keys are never stored in SQLite (SHA-256 hash only)
- The complete key is shown only once at creation
- The upstream secret lives in a separate file (`chmod 600`) or env var
- Logs do not store prompts / responses / reasoning / tool arguments
- Error envelopes never contain key material or request bodies

## Known Limitations

- llama.cpp is the officially validated backend; other
  OpenAI-compatible services are not covered by the v0.1 compatibility
  guarantee
- RPM is single-instance in-memory fixed window
- The RPM window resets when the process restarts
- Token Quota is soft (a request may overshoot before later ones are
  rejected); no reservation mechanism
- `/v1/models` is exempt from RPM / Token Quota
- No Admin HTTP API
- No Web Dashboard
- No HA
- No multi-node clustering

## Documentation

| Content | Path |
|---|---|
| Deployment guide (systemd) | docs/deployment/EasyModelGate-v0.1-Deployment.md |
| Frozen specification | docs/specifications/EasyModelGate-v0.1-Final-Specification.md |
| Design decisions | docs/decisions/ |
| Real protocol samples | docs/protocol/llamacpp/ |
| Stage reports | docs/development/ |
| Release notes | docs/releases/ |
| Experiments | experiments/phase-0.5/ |

## License

Apache License 2.0
