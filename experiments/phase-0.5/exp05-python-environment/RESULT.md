# Experiment 05 — Python/FastAPI Environment Compatibility

## Purpose

Freeze the official Python runtime and dependency set for EasyModelGate v0.1 on
this host (Ubuntu 16.04.7 / kernel 4.15 / glibc 2.31) using an isolated env —
without touching system Python or any existing environment.

## Environment

| Item | Value |
|---|---|
| OS | Ubuntu 16.04.7 LTS (Xenial), kernel `4.15.0-139-generic`, x86_64 |
| glibc | `ldd (Ubuntu GLIBC 2.31-0ubuntu9.16) 2.31` |
| Env managers present | conda 4.11.0 (`~/anaconda3`), **micromamba 2.9.0** (`~/.local/bin`) |
| Env manager used | **micromamba** (per rule: prefer micromamba when present) |
| System/base python | 3.8.3 (NOT touched) |
| Date | 2026-08-26 |

## Procedure

```bash
export MAMBA_ROOT_PREFIX=$HOME/micromamba
micromamba create -y -n easymodelgate-test python=3.12
$MAMBA_ROOT_PREFIX/envs/easymodelgate-test/bin/python -m pip install \
    fastapi starlette httpx uvicorn aiosqlite pytest pytest-asyncio
```

Smoke scripts:

```bash
# import/version smoke + HTTP smoke + SQLite smoke
experiments/phase-0.5/exp05-python-environment/scripts/exp05_smoke_http_sqlite.py
```

Read-only system checks executed (outputs recorded above): `uname -a`,
`/etc/os-release`, `ldd --version`. No system packages touched, no upgrades.

## Raw Observations

Dependency install: clean resolve from PyPI, zero warnings about wheels/glibc/
OpenSSL/compiler. All distributions shipped prebuilt wheels or pure Python.

Import smoke (env python):

```
python        = 3.12.13
fastapi       = 0.141.1
starlette     = 1.6.0
httpx         = 0.28.1
uvicorn       = 0.52.4
aiosqlite     = 0.22.1
pytest        = 9.1.1
pytest_asyncio= 1.4.0
pydantic      = 2.13.4
sqlite3(lib)  = 3.53.2
```

HTTP smoke (`smoke_results.json`):

```
GET http://127.0.0.1:19090/health → 200 {"status":"ok"}   (FastAPI+uvicorn in-process)
```

SQLite smoke:

```
PRAGMA journal_mode=WAL          → wal
busy_timeout=5000 / synchronous=NORMAL applied
CREATE + INSERT + COMMIT + CLOSE + REOPEN + SELECT → 'hello'
journal_mode after reopen        → wal (persisted)
```

Python 3.11 fallback was NOT needed — 3.12 worked on the first try
(kernel 4.15 and glibc 2.31 pose no problem for cp312 manylinux wheels).

## Result

```
RECOMMENDED_PYTHON    = 3.12.13 (micromamba env easymodelgate-test)
FASTAPI_VERSION       = 0.141.1
STARLETTE_VERSION     = 1.6.0
HTTPX_VERSION         = 0.28.1
UVICORN_VERSION       = 0.52.4
AIOSQLITE_VERSION     = 0.22.1
PYTEST_VERSION        = 9.1.1
PYTEST_ASYNCIO_VERSION= 1.4.0
SQLITE_VERSION        = 3.53.2 (system lib bundled with conda-forge python)
OLD_OS_BLOCKER        = NO
```

## PASS / FAIL

**PASS**

## Impact on EasyModelGate v0.1

- Freeze exactly these versions in `requirements.txt` (== pins) for development;
  the same micromamba env name pattern will be reused for the production env.
- micromamba is confirmed as the project env tool (conda 4.11 is too old to be
  desirable; it remains untouched).
- No compiler toolchain needed at install time → reproducible on this host.

## Files Produced

- scripts/exp05_smoke_http_sqlite.py
- smoke_results.json
