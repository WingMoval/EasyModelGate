#!/usr/bin/env python
"""Phase 12 性能验收：Direct vs Gateway 延迟对比（真实 llama.cpp）。

用法：先手动启动 EasyModelGate（configs/config.toml，上游指向本机 llama-server），
再运行本脚本。输出 non-stream 与 stream-TTFT 的 median/min/max 及差值。
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
GATEWAY_KEY_FILE = ROOT / "data" / ".perf_key"
N = int(os.environ.get("EMG_PERF_RUNS", "7"))

# 可用环境变量覆盖（默认值不依赖任何特定机器）：
#   EMG_PERF_MODEL   性能采样使用的模型名（须同时存在于上游与网关）
MODEL = os.environ.get("EMG_PERF_MODEL", "qwen3.8-local")


def ensure_gateway_key():
    """复用或创建一把性能测试 Key（完整 Key 只存内存/临时文件 600）。"""
    if GATEWAY_KEY_FILE.is_file():
        return GATEWAY_KEY_FILE.read_text().strip()
    sys.path.insert(0, str(ROOT))
    from easymodelgate.cli import main
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["--config", str(ROOT / "configs/config.toml"),
              "key", "create", "--user", "alice", "--name", "perf"])
    key = next(ln.strip() for ln in buf.getvalue().splitlines()
               if ln.strip().startswith("emg_"))
    GATEWAY_KEY_FILE.write_text(key)
    GATEWAY_KEY_FILE.chmod(0o600)
    return key


def ttft_and_total(resp_line_iter, t0):
    first = None
    last = b""
    for line in resp_line_iter:
        if first is None and line.startswith(b"data:") and b"[DONE]" not in line \
                and line.strip() != b"":
            first = (time.perf_counter() - t0) * 1000
        last = line
        if line.strip() == b"data: [DONE]":
            break
    total = (time.perf_counter() - t0) * 1000
    return first, total


def run(client, url, headers, body_stream):
    payload = {"model": MODEL,
               "messages": [{"role": "user", "content": "Say OK"}],
               "max_tokens": 6}
    payload["stream"] = True if body_stream else False
    if not body_stream:
        t0 = time.perf_counter()
        r = client.post(url, headers=headers, json=payload)
        assert r.status_code == 200, r.text[:200]
        return None, (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    with client.stream("POST", url, headers=headers, json=payload) as r:
        assert r.status_code == 200
        first, total = ttft_and_total(r.iter_bytes(), t0)
    return first, total


def main():
    upstream_key = None
    kf = ROOT / os.environ.get("EMG_UPSTREAM_KEY_FILE", "configs/upstream_key")
    upstream_key = kf.read_text().strip() if kf.is_file() else None
    gw_key = ensure_gateway_key()

    targets = {
        "direct": ("http://127.0.0.1:8080",
                   {"Authorization": f"Bearer {upstream_key}"}),
        "gateway": ("http://127.0.0.1:3000",
                    {"Authorization": f"Bearer {gw_key}"}),
    }
    results = {}
    with httpx.Client(timeout=httpx.Timeout(5, write=30, read=None, pool=10)) as c:
        # 预热
        for name, (url, h) in targets.items():
            run(c, url + "/v1/chat/completions", h, False)
            run(c, url + "/v1/chat/completions", h, True)

        for label in ("direct", "gateway"):
            url, h = targets[label]
            ns, st = [], []
            for i in range(N):
                _, total = run(c, url + "/v1/chat/completions", h, False)
                ns.append(total)
                first, _total = run(c, url + "/v1/chat/completions", h, True)
                if first is not None:
                    st.append(first)
                time.sleep(0.15)
            results[label] = {"nonstream_ms": ns, "ttft_ms": st}

    def med(xs):
        return statistics.median(xs)

    d_ns = med(results["gateway"]["nonstream_ms"]) - med(results["direct"]["nonstream_ms"])
    d_ttft = med(results["gateway"]["ttft_ms"]) - med(results["direct"]["ttft_ms"])

    out = {
        "runs": N,
        "direct": {k: {"median": round(med(v), 1), "min": round(min(v), 1),
                       "max": round(max(v), 1)}
                   for k, v in results["direct"].items()},
        "gateway": {k: {"median": round(med(v), 1), "min": round(min(v), 1),
                        "max": round(max(v), 1)}
                    for k, v in results["gateway"].items()},
        "overhead": {"nonstream_median_delta_ms": round(d_ns, 1),
                     "ttft_median_delta_ms": round(d_ttft, 1)},
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    (ROOT / "logs" / "perf_phase12.json").write_text(
        json.dumps(out, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
