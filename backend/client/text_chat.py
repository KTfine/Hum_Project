#!/usr/bin/env python3
"""Minimal client for the official MiniCPM-o Realtime chat protocol."""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import sys
import time
from typing import Any
from urllib.parse import urlparse


DEFAULT_URL = "wss://localhost:8006/v1/realtime?mode=chat"


def normalize_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"ws", "wss"} and parsed.path not in {"", "/"}:
        return value
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        raise ValueError(f"unsupported URL scheme: {parsed.scheme!r}")
    scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    host = parsed.netloc or parsed.path
    return f"{scheme}://{host.rstrip('/')}/v1/realtime?mode=chat"


async def run_chat(args: argparse.Namespace) -> dict[str, Any]:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("install the client dependency with: python -m pip install 'websockets>=16'") from exc

    url = normalize_url(args.url)
    ssl_context = None
    if url.startswith("wss://"):
        ssl_context = ssl._create_unverified_context() if args.insecure else ssl.create_default_context()

    started = time.perf_counter()
    request_started: float | None = None
    first_text_at: float | None = None
    chunks: list[str] = []
    session_id = ""
    response_done: dict[str, Any] | None = None

    async with websockets.connect(
        url,
        ssl=ssl_context,
        open_timeout=args.open_timeout,
        max_size=128 * 1024 * 1024,
    ) as websocket:
        while response_done is None:
            message = json.loads(await websocket.recv())
            message_type = message.get("type")

            if message_type == "session.queue_done":
                await websocket.send(json.dumps({"type": "session.init", "payload": {}}))
            elif message_type in {"session.queued", "session.queue_update"}:
                continue
            elif message_type == "session.created":
                session_id = message.get("session_id", "")
                request_started = time.perf_counter()
                await websocket.send(json.dumps({
                    "type": "input.append",
                    "input": {
                        "messages": [{"role": "user", "content": args.prompt}],
                        "streaming": True,
                        "generation": {
                            "max_new_tokens": args.max_new_tokens,
                            "length_penalty": 1.1,
                        },
                        "image": {"max_slice_nums": 1},
                        "omni_mode": False,
                        "tts": {"enabled": False},
                        "use_tts_template": False,
                        "enable_thinking": False,
                    },
                }))
            elif message_type == "response.output.delta" and message.get("kind") == "text":
                if first_text_at is None:
                    first_text_at = time.perf_counter()
                chunks.append(message.get("text") or "")
            elif message_type == "response.done":
                response_done = message
            elif message_type == "error":
                raise RuntimeError(f"server error: {message.get('error')}")

        await websocket.send(json.dumps({"type": "session.close", "reason": "turn_done"}))

    finished = time.perf_counter()
    text = response_done.get("text") or "".join(chunks)
    return {
        "type": "text_chat_validation",
        "ok": bool(text.strip()),
        "url": url,
        "session_id": session_id,
        "text": text,
        "client_total_ms": round((finished - started) * 1000, 3),
        "client_first_text_ms": (
            round((first_text_at - request_started) * 1000, 3)
            if first_text_at is not None and request_started is not None
            else None
        ),
        "server_reason": response_done.get("reason"),
        "server_metrics": response_done.get("metrics", {}),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Gateway base URL or full Realtime WebSocket URL")
    parser.add_argument("--prompt", default="Reply with exactly: MiniCPM service OK")
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--open-timeout", type=float, default=15.0)
    parser.add_argument("--timeout", type=float, default=90.0, help="Overall request timeout in seconds")
    parser.add_argument("--insecure", action="store_true", help="Accept the service's self-signed localhost certificate")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = asyncio.run(asyncio.wait_for(run_chat(args), timeout=args.timeout))
    except Exception as exc:
        print(json.dumps({"type": "text_chat_validation", "ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
