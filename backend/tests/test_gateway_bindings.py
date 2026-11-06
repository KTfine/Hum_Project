#!/usr/bin/env python3
"""Regression test: public and internal Gateway servers use different hosts."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "upstream"))

import gateway  # noqa: E402


configs = []


class FakeConfig:
    def __init__(self, app, **kwargs):
        self.app = app
        self.kwargs = kwargs
        configs.append(self)


class FakeServer:
    def __init__(self, config):
        self.config = config

    async def serve(self):
        await asyncio.sleep(0)


argv = [
    "gateway.py",
    "--host",
    "0.0.0.0",
    "--port",
    "8006",
    "--internal-host",
    "127.0.0.1",
    "--internal-port",
    "8007",
    "--http",
]

with (
    patch.object(sys, "argv", argv),
    patch.object(gateway.uvicorn, "Config", FakeConfig),
    patch.object(gateway.uvicorn, "Server", FakeServer),
):
    gateway.main()

assert len(configs) == 2, configs
assert configs[0].kwargs["host"] == "0.0.0.0", configs[0].kwargs
assert configs[0].kwargs["port"] == 8006, configs[0].kwargs
assert configs[1].kwargs["host"] == "127.0.0.1", configs[1].kwargs
assert configs[1].kwargs["port"] == 8007, configs[1].kwargs
