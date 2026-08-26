#!/usr/bin/env python
"""EXP-04 orchestrator: starts fake upstream (19081) + gateway (19080),
runs normal-completion and client-cancel scenarios, measures propagation
latency, verifies post-disconnect log persistence, then tears down."""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent.parent          # exp04-client-disconnect/
PY = sys.executable
UP_LOG = HERE / "fake_upstream" / "runtime_log.jsonl"
GW_LOG = HERE / "test_gateway" / "runtime_log.jsonl"
REQ_LOG = HERE / "test_gateway" / "request_log.jsonl"
SAMPLES = HERE.parent / "exp04-client-disconnect" / "samples"
SAMPLES.mkdir(exist_ok=True)


def tail_records(path: Path, since_ts: float):
    out = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("ts", 0) >= since_ts:
                out.append(rec)
    return out


async def wait_for(url: str, timeout=15.0):
    t0 = time.time()
    async with httpx.AsyncClient() as c:
        while time.time() - t0 < timeout:
            try:
                r = await c.get(url, timeout=1.0)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.2)
    return False


def rid_of(rec):
    if rec.get("request_id"):
        return rec["request_id"]
    d = rec.get("detail") or {}
    return d.get("request_id")


def find_event(recs, event, rid=None):
    for r in recs:
        if r["event"] == event and (rid is None or rid_of(r) == rid):
            return r["ts"]
    return None


async def main():
    # fresh logs
    for p in (UP_LOG, GW_LOG, REQ_LOG):
        p.unlink(missing_ok=True)

    procs = []
    results = {"case_normal": {}, "case_cancel": {}}
    try:
        procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "19081",
             "--log-level", "warning"], cwd=HERE / "fake_upstream",
            stdout=open(HERE / "fake_upstream" / "server.log", "w"),
            stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen(
            [PY, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "19080",
             "--log-level", "warning"], cwd=HERE / "test_gateway",
            stdout=open(HERE / "test_gateway" / "server.log", "w"),
            stderr=subprocess.STDOUT))

        assert await wait_for("http://127.0.0.1:19081/health"), "upstream not ready"
        assert await wait_for("http://127.0.0.1:19080/health"), "gateway not ready"
        run_marker = time.time()

        # ---------------- Case C: normal completion ----------------
        rid_c = "case-normal"
        chunks = 0
        done_seen = False
        t0 = time.time()
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=30.0)) as c:
            async with c.stream("POST", "http://127.0.0.1:19080/v1/chat/completions",
                                json={"request_id": rid_c, "duration": 3}) as resp:
                assert resp.status_code == 200
                async for chunk in resp.aiter_bytes():
                    chunks += 1
                    if b"[DONE]" in chunk:
                        done_seen = True
        normal_wall_ms = (time.time() - t0) * 1000

        await asyncio.sleep(2.5)  # let simulated log write (1s) land
        gw_recs = tail_records(GW_LOG, run_marker)
        up_recs = tail_records(UP_LOG, run_marker)
        req_recs = tail_records(REQ_LOG, run_marker)

        results["case_normal"] = {
            "chunks_received": chunks,
            "done_seen": done_seen,
            "wall_ms": round(normal_wall_ms),
            "gateway_finished_normally": find_event(gw_recs, "relay_finished_normally", rid_c) is not None,
            "upstream_completed_normally": find_event(up_recs, "stream_completed_normally", rid_c) is not None,
            "no_disconnect_events": all(r.get("request_id") != rid_c or
                                        "disconnect" not in r["event"] and "cancel" not in r["event"]
                                        for r in gw_recs + up_recs),
            "req_log_entry": next((r for r in req_recs if r.get("request_id") == rid_c), None),
        }

        # ---------------- Case D: client cancel at ~3.5s ----------------
        for p in (UP_LOG, GW_LOG, REQ_LOG):
            p.unlink(missing_ok=True)
        marker_d = time.time()

        rid_d = "case-cancel"
        resp_ctx = None
        read_seconds = 3.5
        client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None))
        stream_cm = client.stream("POST", "http://127.0.0.1:19080/v1/chat/completions",
                                  json={"request_id": rid_d, "duration": 60})
        resp = await stream_cm.__aenter__()
        t_start = time.time()
        try:
            async for chunk in resp.aiter_bytes():
                if time.time() - t_start >= read_seconds:
                    break
        finally:
            t_disc = time.time()
            await resp.aclose()                      # abrupt client hang-up
            await stream_cm.__aexit__(None, None, None)
            await client.aclose()

        # poll component logs for the full propagation chain
        deadline = time.time() + 15
        gw_t_cancel = gw_t_aclosed = up_t_finally = None
        while time.time() < deadline:
            gw_recs = tail_records(GW_LOG, marker_d)
            up_recs = tail_records(UP_LOG, marker_d)
            gw_t_cancel = find_event(gw_recs, "client_disconnect_detected", rid_d)
            gw_t_aclosed = find_event(gw_recs, "upstream_aclosed", rid_d)
            up_t_cancel = (find_event(up_recs, "cancelled_error", rid_d)
                           or find_event(up_recs, "generator_finally_connection_closed", rid_d))
            if gw_t_cancel and gw_t_aclosed and up_t_cancel:
                break
            await asyncio.sleep(0.05)

        await asyncio.sleep(2.5)  # allow shielded-style background log write
        req_recs = tail_records(REQ_LOG, marker_d)
        entry = next((r for r in req_recs if r.get("request_id") == rid_d), None)

        m = lambda a, b: (round((b - a) * 1000) if (a is not None and b is not None) else None)
        results["case_cancel"] = {
            "T_client_disconnect": t_disc,
            "T_gateway_detected": gw_t_cancel,
            "T_upstream_aclosed": gw_t_aclosed,
            "T_fake_upstream_stopped": up_t_cancel,
            "gateway_detection_ms": m(t_disc, gw_t_cancel),
            "upstream_close_ms": m(gw_t_cancel, gw_t_aclosed),
            "total_disconnect_propagation_ms": m(t_disc, up_t_cancel),
            "chain_complete": None not in (gw_t_cancel, gw_t_aclosed, up_t_cancel),
            "post_disconnect_req_log": entry,
        }
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

    (SAMPLES / "disconnect_metrics.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
