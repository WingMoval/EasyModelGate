#!/usr/bin/env python
"""EXP-03: Qwen + llama.cpp real Tool Calling wire format (non-stream + stream)."""
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

MESSAGES = [
    {"role": "user",
     "content": "What is the weather in Paris right now? Use the get_weather tool."},
]


def load_api_key() -> str:
    text = OPENCODE_CONFIG.read_text()
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    return json.loads(text)["provider"]["local-qwen"]["options"]["apiKey"]


def main():
    global API_KEY
    API_KEY = load_api_key()
    out = {}
    headers = {"Authorization": f"Bearer {API_KEY}"}
    timeout = httpx.Timeout(connect=5.0, write=30.0, read=300.0, pool=10.0)

    with httpx.Client(timeout=timeout) as client:
        # A: non-stream
        payload = {
            "model": MODEL, "messages": MESSAGES, "tools": TOOLS,
            "tool_choice": "auto", "max_tokens": 200, "stream": False,
        }
        r = client.post(f"{BASE_URL}/v1/chat/completions", json=payload, headers=headers)
        (SAMPLES / "tool-call-nonstream.json").write_text(r.text + "\n", encoding="utf-8")
        try:
            obj = json.loads(r.text)
        except json.JSONDecodeError:
            obj = {}
        choice = (obj.get("choices") or [{}])[0]
        tcs = choice.get("message", {}).get("tool_calls") or []
        out["A_nonstream"] = {
            "http_status": r.status_code,
            "finish_reason": choice.get("finish_reason"),
            "tool_calls_count": len(tcs),
            "tool_calls": [
                {
                    "id_present": bool(tc.get("id")),
                    "id_prefix": (tc.get("id") or "")[:8],
                    "type": tc.get("type"),
                    "function_name": tc.get("function", {}).get("name"),
                    "arguments_raw": tc.get("function", {}).get("arguments"),
                    "arguments_is_single_string": isinstance(
                        tc.get("function", {}).get("arguments"), str),
                }
                for tc in tcs
            ],
            "has_usage": isinstance(obj.get("usage"), dict),
        }

        # B: stream
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        lines = []
        events = []
        with client.stream("POST", f"{BASE_URL}/v1/chat/completions",
                           json=payload, headers=headers) as resp:
            status = resp.status_code
            ctype = resp.headers.get("content-type", "")
            for line in resp.iter_lines():
                lines.append(line)
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if not body or body == "[DONE]":
                    if body == "[DONE]":
                        events.append({"type": "done"})
                    continue
                try:
                    o = json.loads(body)
                except json.JSONDecodeError:
                    continue
                delta = ((o.get("choices") or [{}])[0].get("delta") or {})
                ev = {"type": "chunk", "finish_reason": (o.get("choices") or [{}])[0].get("finish_reason")}
                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        ev["tool_call"] = {
                            "index": tc.get("index"),
                            "id": tc.get("id"),
                            "type": tc.get("type"),
                            "name": tc.get("function", {}).get("name"),
                            "args_fragment": tc.get("function", {}).get("arguments"),
                        }
                if delta.get("content"):
                    ev["content_len"] = len(delta["content"])
                if delta.get("reasoning_content"):
                    ev["reasoning_len"] = len(delta["reasoning_content"])
                if isinstance(o.get("usage"), dict):
                    ev["usage"] = o["usage"]
                events.append(ev)
        (SAMPLES / "tool-call-stream.sse").write_text("\n".join(lines) + "\n", encoding="utf-8")
        frags = [e["tool_call"] for e in events if "tool_call" in e]
        joined = "".join(f["args_fragment"] or "" for f in frags)
        finish = next((e["finish_reason"] for e in events if e.get("finish_reason")), None)
        usage = next((e["usage"] for e in events if "usage" in e), None)
        out["B_stream"] = {
            "http_status": status,
            "content_type": ctype,
            "event_count": len(events),
            "fragments": frags,
            "arguments_reassembled": joined,
            "json_args_valid": _try_json(joined),
            "first_frag_has_id_and_name": bool(frags and frags[0]["id"] and frags[0]["name"]),
            "later_frags_carry_id_or_name": any(f["id"] or f["name"] for f in frags[1:]),
            "all_frags_have_index": all(f["index"] == 0 for f in frags),
            "finish_reason": finish,
            "usage_in_stream": usage,
        }

    print(json.dumps(out, ensure_ascii=False, indent=2))


def _try_json(s):
    try:
        json.loads(s)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
