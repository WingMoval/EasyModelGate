#!/usr/bin/env python
"""EXP-01: llama.cpp streaming usage wire behavior probe.

Reads upstream API key at runtime from the existing OpenCode provider config.
The key is never printed, logged, or written to any file.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8080"
MODEL = "qwen3.8-local"
OPENCODE_CONFIG = Path(
    os.environ.get(
        "EMG_OPENCODE_CONFIG",
        str(Path.home() / ".config" / "opencode" / "opencode.jsonc"),
    )
)
HERE = Path(__file__).resolve().parent.parent
SAMPLES = HERE / "samples"


def load_api_key() -> str:
    text = OPENCODE_CONFIG.read_text()
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    cfg = json.loads(text)
    return cfg["provider"]["local-qwen"]["options"]["apiKey"]


def analyze_sse(lines):
    data_lines = [ln for ln in lines if ln.startswith("data:")]
    done_idx = next((i for i, ln in enumerate(data_lines) if ln.strip() == "data: [DONE]" or ln.strip() == "data:[DONE]"), None)
    usage_idx = None
    usage_obj = None
    timings_present = False
    for i, ln in enumerate(data_lines):
        body = ln[5:].strip()
        if not body or body == "[DONE]":
            continue
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(obj.get("usage"), dict):
            if usage_idx is None:
                usage_idx = i
                usage_obj = obj["usage"]
        if "timings" in obj:
            timings_present = True
    return {
        "data_line_count": len(data_lines),
        "done_index": done_idx,
        "usage_index": usage_idx,
        "usage_before_done": (usage_idx is not None and done_idx is not None and usage_idx < done_idx),
        "usage_object": usage_obj,
        "usage_chunk_choices_empty": None,
        "timings_present": timings_present,
    }


def run_stream(client, payload, out_name):
    r = client.post(
        f"{BASE_URL}/v1/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    )
    status = r.status_code
    ctype = r.headers.get("content-type", "")
    lines = []
    for line in r.iter_lines():
        lines.append(line)
    (SAMPLES / out_name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    analysis = analyze_sse(lines)
    # find the usage chunk raw structure
    usage_chunk_raw = None
    for ln in lines:
        b = ln[5:].strip() if ln.startswith("data:") else ""
        if not b or b == "[DONE]":
            continue
        try:
            o = json.loads(b)
        except json.JSONDecodeError:
            continue
        if isinstance(o.get("usage"), dict):
            usage_chunk_raw = {k: (v if k != "choices" else f"<list len={len(v)}>") for k, v in o.items()}
            analysis["usage_chunk_choices_empty"] = (o.get("choices") == [])
            break
    return {
        "http_status": status,
        "content_type": ctype,
        **analysis,
        "usage_chunk_structure": usage_chunk_raw,
    }


def main():
    global API_KEY
    API_KEY = load_api_key()
    base_payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Reply with exactly: hello"}],
        "max_tokens": 32,
        "stream": True,
    }
    results = {}
    with httpx.Client(timeout=httpx.Timeout(connect=5.0, write=30.0, read=180.0, pool=10.0)) as client:
        # A: default (no stream_options)
        p = dict(base_payload)
        results["A_default"] = run_stream(client, p, "stream-without-stream-options.sse")

        time.sleep(0.3)
        # B: include_usage=true
        p = dict(base_payload, stream_options={"include_usage": True})
        results["B_include_true"] = run_stream(client, p, "stream-include-usage-true.sse")

        time.sleep(0.3)
        # C: include_usage=false
        p = dict(base_payload, stream_options={"include_usage": False})
        results["C_include_false"] = run_stream(client, p, "stream-include-usage-false.sse")

        time.sleep(0.3)
        # D: non-stream
        p = dict(base_payload)
        p["stream"] = False
        r = client.post(
            f"{BASE_URL}/v1/chat/completions",
            json=p,
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        body = r.text
        (SAMPLES / "non-stream-response.json").write_text(body + "\n", encoding="utf-8")
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            obj = {}
        results["D_nonstream"] = {
            "http_status": r.status_code,
            "content_type": r.headers.get("content-type", ""),
            "has_usage": isinstance(obj.get("usage"), dict),
            "usage": obj.get("usage"),
            "finish_reason": ((obj.get("choices") or [{}])[0].get("finish_reason")),
            "has_timings": "timings" in obj,
        }

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
