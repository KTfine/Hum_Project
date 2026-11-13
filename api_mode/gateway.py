"""Translate the existing realtime protocol into cancellable text/image requests.

Prompts and command interpretation belong to the frontend. This module forwards
the provider's text unchanged, including partial and adjacent command tags.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from contextlib import AsyncExitStack
from dataclasses import dataclass
import json
import math
import struct
import time
from typing import Callable
import uuid

from aiohttp import WSMsgType, web

from .llm import ApiError, DeepSeekClient, Image


@dataclass(frozen=True)
class GatewayConfig:
    model: str = 'deepseek-flash'
    thinking: str = 'low'
    timeout: float = 90.0
    max_tokens: int = 4096
    max_turns: int = 20
    visual_interval: float = 8.0

    def __post_init__(self):
        if self.max_turns < 1 or self.max_tokens < 1:
            raise ValueError('max_turns and max_tokens must be positive')
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError('timeout must be positive')
        if not math.isfinite(self.visual_interval) or self.visual_interval < 0:
            raise ValueError('visual_interval must be nonnegative; 0 disables observation')


CONFIG = web.AppKey('gateway_config', GatewayConfig)
FACTORY = web.AppKey('llm_factory', object)
SESSIONS = web.AppKey('sessions', set)


def _image(encoded: str) -> dict:
    if not isinstance(encoded, str) or len(encoded) > 12 * 1024 * 1024:
        raise ValueError('image must be a base64 string smaller than 12 MiB')
    if encoded.startswith('data:'):
        header, separator, encoded = encoded.partition(',')
        if not separator or ';base64' not in header:
            raise ValueError('image data URL must be base64 encoded')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('invalid base64 image') from None
    return Image(data).block()


def _messages(value: object) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise ValueError('messages must be a nonempty list')
    result = []
    for i, message in enumerate(value):
        if not isinstance(message, dict):
            raise ValueError('each message must be an object')
        role, content = message.get('role'), message.get('content')
        if role not in ('system', 'user', 'assistant') or (role == 'system' and i != 0):
            raise ValueError('only an initial system and user/assistant messages are supported')
        if isinstance(content, list) and role == 'user':
            blocks = []
            for block in content:
                if not isinstance(block, dict):
                    raise ValueError('content blocks must be objects')
                kind = block.get('type')
                if kind == 'text' and isinstance(block.get('text'), str):
                    blocks.append({'type': 'text', 'text': block['text']})
                elif kind == 'image':
                    blocks.append(_image(block.get('data')))
                elif kind == 'image_url' and isinstance(block.get('image_url'), dict):
                    blocks.append(_image(block['image_url'].get('url')))
                else:
                    raise ValueError('API chat accepts text/image blocks; audio is unsupported')
            content = blocks
        elif not isinstance(content, str):
            raise ValueError('system/assistant content must be text; user content must be text or blocks')
        result.append({'role': role, 'content': content})
    if result[-1]['role'] != 'user':
        raise ValueError('messages must end with a user request')
    return result


class GatewaySession:
    def __init__(self, ws: web.WebSocketResponse, mode: str, config: GatewayConfig,
                 factory: Callable):
        self.ws, self.mode, self.config, self.factory = ws, mode, config, factory
        self.session_id = uuid.uuid4().hex
        self.system = ''
        self.initialized = False
        self.closed = False
        self.llm = None
        self.stack = AsyncExitStack()
        self.history: list[dict] = []
        self.pending_history: list[dict] | None = None
        self.pending_system: str | None = None
        # Observations are replaceable; human goals and revisions never are.
        self.observation: list[dict] = []
        self.latest_image: dict | None = None
        self.frame_version = 0
        self.observed_version = 0
        self.last_request = time.monotonic()
        self.monitor_paused = False
        self.revision = 0
        self.response_id: str | None = None
        self.active: asyncio.Task | None = None
        self.tasks: set[asyncio.Task] = set()
        self.inference_lock = asyncio.Lock()
        self.outbox: asyncio.Queue = asyncio.Queue(maxsize=256)
        self.writer: asyncio.Task | None = None
        self.monitor: asyncio.Task | None = None
        self.last_audio_warning = -math.inf

    def emit(self, event: dict, revision: int | None = None):
        if not self.closed:
            try:
                self.outbox.put_nowait((revision, event))
            except asyncio.QueueFull:
                raise RuntimeError('client output queue is full') from None

    def error(self, code: str, message: str, *, revision: int | None = None,
              response_id: str | None = None):
        event = {'type': 'error', 'error': {'code': code, 'message': message}}
        if response_id is not None:
            event['response_id'] = response_id
        self.emit(event, revision)

    async def _writer(self):
        try:
            while True:
                revision, event = await self.outbox.get()
                try:
                    if revision is None or revision == self.revision:
                        await self.ws.send_json(event)
                finally:
                    self.outbox.task_done()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Wake the reader/cleanup if the consumer disconnects mid-stream.
            await self.ws.close()

    def interrupt(self, reason: str):
        self.revision += 1
        if self.active is not None and not self.active.done():
            self.active.cancel()
            self.emit({'type': 'response.interrupted', 'response_id': self.response_id,
                       'reason': reason})

    async def run(self):
        self.writer = asyncio.create_task(self._writer())
        self.monitor = asyncio.create_task(self._observe())
        self.emit({'type': 'session.queue_done', 'session_id': self.session_id})
        try:
            async for message in self.ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        event = json.loads(message.data)
                        if not isinstance(event, dict):
                            raise ValueError('event must be an object')
                        await self.handle(event)
                    except (ValueError, TypeError, KeyError) as exc:
                        self.error('invalid_request', str(exc))
                    if self.closed:
                        break
                elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        finally:
            self.closed = True
            self.revision += 1
            for task in [self.monitor, self.writer, *self.tasks]:
                if task is not None:
                    task.cancel()
            try:
                await asyncio.gather(self.monitor, self.writer, *self.tasks, return_exceptions=True)
            finally:
                # aiohttp may cancel the request when the close frame is sent.
                await self.stack.aclose()

    async def handle(self, event: dict):
        kind = event.get('type')
        if kind == 'session.close':
            self.interrupt('session_closed')
            self.emit({'type': 'session.closed', 'reason': event.get('reason', 'client_request')})
            try:
                await asyncio.wait_for(self.outbox.join(), timeout=2)
            except TimeoutError:
                pass  # disconnected/slow clients must not strand session cleanup
            self.closed = True
            await self.ws.close()
            return
        if kind == 'session.init':
            if self.initialized:
                raise ValueError('session already initialized; reconnect to replace the prompt')
            payload = event.get('payload', {})
            if not isinstance(payload, dict) or not isinstance(payload.get('system_prompt', ''), str):
                raise ValueError('session.init payload.system_prompt must be text')
            try:
                self.llm = await self.stack.enter_async_context(self.factory())
            except Exception as exc:
                # Never forward exception text that might contain an API credential.
                self.error('provider_configuration', f'Cannot initialize API client ({type(exc).__name__}); check server configuration')
                return
            self.system = payload.get('system_prompt', '')
            self.initialized = True
            self.emit({'type': 'session.created', 'session_id': self.session_id,
                       'mode': self.mode, 'backend': 'api',
                       'capabilities': {'text': True, 'image': True, 'audio': False}})
            return
        if not self.initialized:
            raise ValueError('send session.init before input')
        if kind not in ('input.append', 'input.text'):
            raise ValueError(f'unsupported event type: {kind}')
        data = event.get('input', {}) if kind == 'input.append' else {'text': event.get('text')}
        if not isinstance(data, dict):
            raise ValueError('input must be an object')
        frames = data.get('video_frames', [])
        if not isinstance(frames, list):
            raise ValueError('video_frames must be a list')
        if frames:
            self.latest_image = _image(frames[-1])
            self.frame_version += 1
        if data.get('audio'):
            self._audio_warning(data['audio'])
        text = data.get('text')
        if text is not None and not isinstance(text, str):
            raise ValueError('input.text must be text')
        explicit = _messages(data['messages']) if 'messages' in data else None
        if explicit is not None and text is not None:
            raise ValueError('send text or messages, not both')
        if text and text.strip():
            content = text
            if self.latest_image is not None:
                content = [{'type': 'text', 'text': text}, self.latest_image]
            user = [{'role': 'user', 'content': content}]
            self._start(user)
        elif explicit is not None:
            self._start(explicit, replace=True)
        elif self.active is None or self.active.done():
            self.emit({'type': 'response.output.delta', 'kind': 'listen',
                       'input_id': data.get('input_id')})

    def _audio_warning(self, encoded: str):
        if not isinstance(encoded, str) or len(encoded) > 2 * 1024 * 1024:
            raise ValueError('audio must be base64 PCM float32, at most 2 MiB')
        try:
            pcm = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError('invalid base64 audio') from None
        if len(pcm) % 4:
            raise ValueError('audio must contain complete float32 samples')
        audible = False
        for (sample,) in struct.iter_unpack('<f', pcm):
            if not math.isfinite(sample):
                raise ValueError('audio contains nonfinite samples')
            audible |= abs(sample) >= 0.01
        now = time.monotonic()
        if audible and now - self.last_audio_warning >= 10:
            self.last_audio_warning = now
            self.emit({'type': 'warning', 'code': 'audio_unsupported',
                       'message': 'API mode accepts text and images only; use text input. Audio was not transcribed.'})

    def _start(self, user: list[dict], *, replace=False, observation=False):
        system = self.pending_system if self.pending_system is not None else self.system
        if replace and user[0]['role'] == 'system':
            supplied, user = user[0]['content'], user[1:]
            if self.system and supplied != self.system:
                raise ValueError('system prompt differs from session.init; reconnect to change modes')
            system = supplied
        base = self.pending_history if self.pending_history is not None else self.history
        candidate = user if replace else base + user
        if not observation and sum(m['role'] == 'user' for m in candidate) > self.config.max_turns:
            self.error('history_limit', 'Conversation history limit reached; reconnect explicitly to begin a new session')
            return
        self.interrupt('new_input' if not observation else 'new_observation')
        revision = self.revision
        response_id = uuid.uuid4().hex
        self.response_id = response_id
        messages = [{'role': 'system', 'content': system}]
        messages += user if replace else base + self.observation + user
        if not observation:
            # Keep accepted user goals through interruption without committing a
            # partial assistant answer. A later successful request commits them.
            self.pending_history = candidate
            self.pending_system = system
        self.last_request = time.monotonic()
        self.observed_version = self.frame_version
        self.monitor_paused = False
        task = asyncio.create_task(self._complete(messages, candidate, user, system,
                                                  revision, response_id, observation))
        self.active = task
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _complete(self, messages, candidate, user, system, revision, response_id, observation):
        def delta(text):
            if revision == self.revision and not self.closed:
                self.emit({'type': 'response.output.delta', 'kind': 'text',
                           'text': text, 'response_id': response_id}, revision)
        try:
            # A cancelled transport that is still unwinding cannot overlap a new call.
            async with self.inference_lock:
                if revision != self.revision or self.closed:
                    return
                result = await self.llm.complete(messages, on_delta=delta)
            if revision != self.revision or self.closed:
                return
            assistant = {'role': 'assistant', 'content': result.text}
            self.emit({'type': 'response.done', 'response_id': response_id,
                       'text': result.text, 'metadata': result.metadata}, revision)
            if observation:
                self.observation = user + [assistant]
            else:
                self.system = system
                self.history = candidate + [assistant]
                self.pending_history = None
                self.pending_system = None
                self.observation = []
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if revision == self.revision and not self.closed:
                self.monitor_paused = True
                detail = type(exc).__name__
                if isinstance(exc, ApiError):
                    status = exc.result.metadata.get('http_status')
                    if isinstance(status, int):
                        detail += f'; HTTP {status}'
                try:
                    self.error('provider_error', f'API request failed ({detail}); history was not updated. Pending user input is retained for an explicit next request.',
                               revision=revision, response_id=response_id)
                except RuntimeError:
                    await self.ws.close(code=1013, message=b'Client output queue full; reconnect')

    async def _observe(self):
        interval = self.config.visual_interval
        if interval == 0 or self.mode != 'video':
            return
        while True:
            await asyncio.sleep(min(interval, 0.5))
            if (self.initialized and self.history and self.latest_image is not None
                    and not self.monitor_paused and self.frame_version != self.observed_version
                    and (self.active is None or self.active.done())
                    and time.monotonic() - self.last_request >= interval):
                user = [{'role': 'user', 'content': [
                    {'type': 'text', 'text': '这是当前的新画面。请结合我最近的目标和对话，判断是否需要继续指导；如果我改变了要求，以最新要求为准。'},
                    self.latest_image]}]
                self._start(user, observation=True)


def create_app(*, config: GatewayConfig | None = None, llm_factory: Callable | None = None) -> web.Application:
    """Create an injectable app; importing it never opens network connections."""
    config = config or GatewayConfig()
    app = web.Application(client_max_size=16 * 1024 * 1024)
    app[CONFIG] = config
    app[FACTORY] = llm_factory or (lambda: DeepSeekClient(
        model=config.model, thinking=config.thinking, timeout=config.timeout,
        max_tokens=config.max_tokens))
    app[SESSIONS] = set()

    async def health(request):
        return web.json_response({'status': 'healthy', 'backend': 'api'})

    async def status(request):
        return web.json_response({'status': 'running', 'backend': 'api',
                                  'model': config.model, 'sessions': len(app[SESSIONS]),
                                  'capabilities': {'text': True, 'image': True, 'audio': False},
                                  'provider_verified': False, 'visual_interval': config.visual_interval})

    async def realtime(request):
        mode = request.query.get('mode', 'video')
        if mode not in ('chat', 'audio', 'video'):
            raise web.HTTPBadRequest(text='mode must be chat, audio or video')
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)
        session = GatewaySession(ws, mode, config, app[FACTORY])
        app[SESSIONS].add(session)
        try:
            await session.run()
        finally:
            app[SESSIONS].discard(session)
        return ws

    async def shutdown(application):
        await asyncio.gather(*(session.ws.close(code=1001, message=b'server shutdown')
                               for session in list(application[SESSIONS])))

    app.router.add_get('/health', health)
    app.router.add_get('/status', status)
    app.router.add_get('/v1/realtime', realtime)
    app.on_shutdown.append(shutdown)
    return app
