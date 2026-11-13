#!/usr/bin/env python3
"""Check a tunneled MiniCPM-o Gateway and report client-observed latency."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_URL = "https://localhost:8006"


def health_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    return value if value.endswith("/health") else f"{value}/health"


def fetch_health(base_url: str, timeout: float, insecure: bool) -> dict[str, Any]:
    url = health_url(base_url)
    context = ssl._create_unverified_context() if insecure and url.startswith("https://") else None
    request = Request(url, headers={"accept": "application/json"})
    started = time.perf_counter()
    with urlopen(request, timeout=timeout, context=context) as response:
        payload = json.loads(response.read().decode("utf-8"))
        status_code = response.status
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "type": "health_check",
        "ok": status_code == 200 and payload.get("status") == "healthy",
        "url": url,
        "status_code": status_code,
        "client_latency_ms": round(elapsed_ms, 3),
        "response": payload,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--insecure", action="store_true", help="Accept the service's self-signed localhost certificate")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = fetch_health(args.url, args.timeout, args.insecure)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"type": "health_check", "ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
