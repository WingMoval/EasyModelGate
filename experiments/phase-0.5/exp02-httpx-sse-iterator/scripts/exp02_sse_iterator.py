#!/usr/bin/env python
"""EXP-02: httpx SSE iterator behavior comparison against real llama.cpp.

Compares Response.aiter_raw() / aiter_bytes() / aiter_lines() on identical
streaming requests. Records chunk-level observations. No secrets are printed;
the API key is loaded at runtime from the OpenCode provider config.
"""
import asyncio
import codecs
import json
import os
import re
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

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]


def load_api_key() -> str:
    text = OPENCODE_CONFIG.read_text()
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    return json.loads(text)["provider"]["local-qwen"]["options"]["apiKey"]


def chunk_record(seq: int, chunk: bytes, carry_before: bytes):
    buf = carry_before + chunk
    events_done = 0
    while b"\n\n" in buf:
        _, buf = buf.split(b"\n\n", 1)
        events_done += 1
    head = chunk[:80]
    try:
        head_repr = head.decode("utf-8")
        utf8_whole = True
    except UnicodeDecodeError:
        head_repr = repr(head)
        utf8_whole = False
    return {
        "seq": seq,
        "len": len(chunk),
        "head_80": head_repr.replace("\n", "\\n"),
        "utf8_standalone": utf8_whole,
        "events_completed_here": events_done,
        "had_partial_carry_after": len(buf) > 0,
    }


async def capture_mode(client: httpx.AsyncClient, mode: str, payload, out_name):
    recs = []
    seq = 0
    dec = codecs.getincrementaldecoder("utf-8")()
    lines_summary = {"total_lines": 0, "blank_lines": 0, "data_lines": 0,
                     "done_seen": False, "usage_line_seq": None}
    content_encoding = None
    status = None
    ctype = None
    tool_frags = []
    pending = b""
    async with client.stream(
        "POST", f"{BASE_URL}/v1/chat/completions", json=payload,
        headers={"Authorization": f"Bearer {API_KEY}"},
    ) as resp:
        status = resp.status_code
        ctype = resp.headers.get("content-type", "")
        content_encoding = resp.headers.get("content-encoding", "none")
        it = (
            resp.aiter_raw() if mode == "raw"
            else resp.aiter_bytes() if mode == "bytes"
            else resp.aiter_lines()
        )
        async for item in it:
            seq += 1
            if mode == "lines":
                line = item
                is_blank = (line.strip() == "")
                lines_summary["total_lines"] += 1
                if is_blank:
                    lines_summary["blank_lines"] += 1
                elif line.startswith("data:"):
                    lines_summary["data_lines"] += 1
                    body = line[5:].strip()
                    if body == "[DONE]":
                        lines_summary["done_seen"] = True
                    else:
                        try:
                            o = json.loads(body)
                        except json.JSONDecodeError:
                            o = {}
                        if isinstance(o.get("usage"), dict) and lines_summary["usage_line_seq"] is None:
                            lines_summary["usage_line_seq"] = seq
                        for tc in ((o.get("choices") or [{}])[0].get("delta", {}).get("tool_calls") or []):
                            tool_frags.append({
                                "line_seq": seq, "index": tc.get("index"),
                                "id": tc.get("id"), "name": tc.get("function", {}).get("name"),
                                "args_fragment": tc.get("function", {}).get("arguments"),
                            })
                recs.append({"seq": seq, "repr_head": repr(line[:90]),
                             "is_blank": is_blank})
            else:
                had_carry_before = len(pending) > 0
                buf = pending + item
                events_here = 0
                while b"\n\n" in buf:
                    _, buf = buf.split(b"\n\n", 1)
                    events_here += 1
                pending = buf
                head = item[:80]
                try:
                    head_repr = head.decode("utf-8")
                    utf8_whole = True
                except UnicodeDecodeError:
                    head_repr = repr(head)
                    utf8_whole = False
                rec = {
                    "seq": seq,
                    "len": len(item),
                    "head_80": head_repr.replace("\n", "\\n"),
                    "utf8_standalone": utf8_whole,
                    "continued_from_prev_chunk": had_carry_before,
                    "events_completed_here": events_here,
                    "partial_tail_after": len(pending) > 0,
                }
                try:
                    dec.decode(item)
                    rec["utf8_incremental_ok"] = True
                except UnicodeDecodeError:
                    rec["utf8_incremental_ok"] = False
                recs.append(rec)
    result = {
        "mode": mode,
        "http_status": status,
        "content_type": ctype,
        "content_encoding": content_encoding,
        "chunk_count": seq,
        "records": recs,
        "final_incomplete_event_bytes": len(pending),
        "final_incomplete_repr": repr(pending[:60]) if pending else "",
    }
    if mode == "lines":
        result["lines_summary"] = lines_summary
        result["tool_call_fragments"] = tool_frags
    else:
        multi = [r["seq"] for r in recs if r["events_completed_here"] > 1]
        contd = [r["seq"] for r in recs if r["continued_from_prev_chunk"]]
        splitmid = [r["seq"] for r in recs if r["partial_tail_after"]]
        result["chunks_containing_multiple_events"] = multi
        result["chunks_continuing_split_event"] = contd
        result["chunks_ending_mid_event"] = splitmid
    (SAMPLES / out_name).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    slim = {k: v for k, v in result.items() if k != "records"}
    if mode != "lines":
        slim["per_chunk"] = [{"seq": r["seq"], "len": r["len"],
                              "ev": r["events_completed_here"],
                              "contd": r["continued_from_prev_chunk"],
                              "tail": r["partial_tail_after"]} for r in recs]
    else:
        slim["tool_call_fragments"] = tool_frags
    return slim


async def main():
    global API_KEY
    API_KEY = load_api_key()
    timeout = httpx.Timeout(connect=5.0, write=30.0, read=180.0, pool=10.0)
    summary = {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        plain_payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": "Reply with exactly: hello"}],
            "max_tokens": 32,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        for mode, fname in [("raw", "plain-raw-chunks.json"),
                            ("bytes", "plain-bytes-chunks.json"),
                            ("lines", "plain-lines-obs.json")]:
            summary[f"plain_{mode}"] = await capture_mode(client, mode, plain_payload, fname)
            await asyncio.sleep(0.2)

        tool_payload = {
            "model": MODEL,
            "messages": [{"role": "user",
                          "content": "What is the weather in Paris right now? Use the get_weather tool."}],
            "tools": TOOLS,
            "tool_choice": "auto",
            "max_tokens": 200,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        for mode, fname in [("raw", "toolcall-raw-chunks.json"),
                            ("bytes", "toolcall-bytes-chunks.json"),
                            ("lines", "toolcall-lines-obs.json")]:
            summary[f"tool_{mode}"] = await capture_mode(client, mode, tool_payload, fname)
            await asyncio.sleep(0.2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
