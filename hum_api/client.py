"""DeepSeek Chat Completions transport. No devices, credentials or logs on disk."""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Callable

import httpx

ENDPOINT = 'https://api.deepseek.com/chat/completions'


@dataclass(frozen=True)
class Image:
    data: bytes = field(repr=False)

    @classmethod
    def from_path(cls, path: str | Path) -> Image:
        return cls(Path(path).read_bytes())

    def block(self) -> dict:
        data = self.data
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        elif data.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        elif data[:6] in (b'GIF87a', b'GIF89a'):
            mime = 'image/gif'
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            mime = 'image/webp'
        else:
            raise ValueError('Expected PNG, JPEG, GIF or WebP bytes')
        return {'type': 'image_url', 'image_url': {
            'url': f'data:{mime};base64,' + base64.b64encode(data).decode('ascii'),
            'detail': 'original',
        }}


@dataclass
class ApiResult:
    text: str = ''
    commands: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class ApiError(RuntimeError):
    """Includes partial output for auditing; failed turns are not committed."""
    def __init__(self, message: str, result: ApiResult):
        super().__init__(message)
        self.result = result


async def _sse_data(response):
    lines = []
    async for line in response.aiter_lines():
        if not line:
            if lines:
                yield '\n'.join(lines)
                lines.clear()
        elif line.startswith('data:'):
            lines.append(line[5:].lstrip(' '))
    if lines:
        yield '\n'.join(lines)


class DeepSeekClient:
    def __init__(self, api_key: str | None = None, *, model='deepseek-flash',
                 thinking='low', timeout=90.0, max_tokens=4096, transport=None):
        self._key = api_key if api_key is not None else os.environ.get('DEEPSEEK_API_KEY', '')
        if not self._key.strip():
            raise ValueError('Set DEEPSEEK_API_KEY in this process before connecting')
        if thinking not in ('off', 'low', 'high', 'max'):
            raise ValueError('thinking must be off, low, high or max')
        if not math.isfinite(timeout) or timeout <= 0 or max_tokens <= 0:
            raise ValueError('timeout and max_tokens must be positive')
        self.model, self.thinking = model, thinking
        self.timeout, self.max_tokens = timeout, max_tokens
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(min(timeout, 30), connect=min(timeout, 10)),
            follow_redirects=False, transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._http.aclose()

    async def complete(self, messages: list[dict], *, on_delta: Callable[[str], None] | None = None) -> ApiResult:
        if not messages or messages[0].get('role') != 'system' or not isinstance(messages[0].get('content'), str):
            raise ValueError('messages must begin with a text system prompt')
        payload = dict(model=self.model, messages=messages, stream=True,
                       stream_options={'include_usage': True}, max_tokens=self.max_tokens,
                       thinking={'type': 'disabled' if self.thinking == 'off' else 'enabled'})
        if self.thinking != 'off':
            payload['reasoning_effort'] = self.thinking
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        if len(body) > 48 * 1024 * 1024:
            raise ValueError('Request exceeds 48 MiB; reduce images or explicitly reset history')
        result = ApiResult(metadata={
            'started_utc': datetime.now(timezone.utc).isoformat(),
            'requested_model': self.model, 'thinking': self.thinking,
            'max_tokens': self.max_tokens, 'timeout_s': self.timeout,
            'request_sha256': hashlib.sha256(body).hexdigest(),
            'system_sha256': hashlib.sha256(messages[0]['content'].encode()).hexdigest(),
            'status': 'pending', 'reasoning_chars': 0,
        })
        started = time.monotonic()
        done = False
        try:
            # Includes connection, upload and the entire stream, unlike a per-read timeout.
            async with asyncio.timeout(self.timeout):
                async with self._http.stream('POST', ENDPOINT, content=body, headers={
                    'Authorization': 'Bearer ' + self._key,
                    'Content-Type': 'application/json', 'Accept': 'text/event-stream',
                }) as response:
                    result.metadata['http_status'] = response.status_code
                    if response.status_code != 200:
                        raise RuntimeError(f'HTTP {response.status_code}; no automatic retry')
                    if 'text/event-stream' not in response.headers.get('content-type', ''):
                        raise RuntimeError('Expected an SSE response')
                    async for data in _sse_data(response):
                        if data.strip() == '[DONE]':
                            done = True
                            break
                        event = json.loads(data)
                        if 'error' in event:
                            raise RuntimeError('Provider returned an error event')
                        for key in ('model', 'system_fingerprint', 'id', 'usage'):
                            if event.get(key) is not None:
                                result.metadata[key] = event[key]
                        for choice in event.get('choices', []):
                            if choice.get('finish_reason'):
                                result.metadata['finish_reason'] = choice['finish_reason']
                            delta = choice.get('delta') or {}
                            result.metadata['reasoning_chars'] += len(delta.get('reasoning_content') or '')
                            chunk = delta.get('content') or ''
                            if chunk:
                                result.metadata.setdefault('first_text_s', time.monotonic() - started)
                                result.text += chunk
                                if on_delta:
                                    on_delta(chunk)
            if not done or result.metadata.get('finish_reason') != 'stop' or not result.text:
                raise RuntimeError('Incomplete response; history unchanged, no automatic retry')
            result.metadata['status'] = 'ok'
            return result
        except asyncio.CancelledError as exc:
            result.metadata.update(status='cancelled', error='CancelledError')
            exc.result = result
            raise
        except Exception as exc:
            # Do not expose raw HTTP exception bodies, headers or credentials.
            message = str(exc) if type(exc) is RuntimeError else type(exc).__name__
            result.metadata.update(status='error', error=message.replace(self._key, '[REDACTED]'))
            raise ApiError(result.metadata['error'], result) from None
        finally:
            result.metadata['elapsed_s'] = time.monotonic() - started
