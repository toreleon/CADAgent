"""Probe whether ANTHROPIC_BASE_URL actually streams /v1/messages.

Bypasses claude_agent_sdk and the Claude CLI entirely — speaks raw SSE to
the proxy. Each line of output is timestamped relative to request start,
so "burst at the end" vs "spread across the turn" is obvious by eye.

Usage:

    ANTHROPIC_BASE_URL=http://localhost:4000 \
    ANTHROPIC_API_KEY=sk-... \
    ANTHROPIC_MODEL=claude-opus-4-7 \
    python scripts/probe_stream.py
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx


def main() -> int:
    base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    if not base or not key:
        print("Set ANTHROPIC_BASE_URL and ANTHROPIC_API_KEY.", file=sys.stderr)
        return 2

    url = f"{base}/v1/messages"
    headers = {
        "x-api-key": key,
        "authorization": f"Bearer {key}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "fine-grained-tool-streaming-2025-05-14",
        "content-type": "application/json",
        "accept": "text/event-stream",
    }
    body = {
        "model": model,
        "max_tokens": 512,
        "stream": True,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Count from 1 to 30, one number per line, with a short "
                    "phrase after each. Keep going until you reach 30."
                ),
            }
        ],
    }

    print(f"POST {url}  model={model}")
    t0 = time.monotonic()
    event_count = 0
    delta_count = 0
    first_delta_at: float | None = None
    last_delta_at: float | None = None

    with httpx.Client(timeout=httpx.Timeout(60.0, read=60.0)) as client:
        with client.stream("POST", url, headers=headers, json=body) as r:
            print(
                f"+{time.monotonic() - t0:6.3f}s  status={r.status_code} "
                f"content-type={r.headers.get('content-type')!r}"
            )
            if r.status_code != 200:
                print(r.read().decode("utf-8", "replace"))
                return 1
            for raw in r.iter_lines():
                now = time.monotonic() - t0
                if not raw:
                    continue
                event_count += 1
                line = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
                tag = line[:140]
                print(f"+{now:6.3f}s  {tag}")
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    try:
                        obj = json.loads(payload)
                    except Exception:
                        continue
                    if obj.get("type") == "content_block_delta":
                        delta = obj.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            delta_count += 1
                            if first_delta_at is None:
                                first_delta_at = now
                            last_delta_at = now

    print()
    print(f"total events: {event_count}  text_deltas: {delta_count}")
    if first_delta_at is not None and last_delta_at is not None:
        span = last_delta_at - first_delta_at
        print(
            f"first text_delta at +{first_delta_at:.3f}s, "
            f"last at +{last_delta_at:.3f}s, "
            f"span={span:.3f}s"
        )
        if span < 0.2:
            print("VERDICT: deltas arrived in a burst — proxy is NOT streaming.")
        else:
            print("VERDICT: deltas spread across the response — proxy IS streaming.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
