"""Real local WebSocket tests with an injected provider; no API key or media devices."""
import asyncio
import base64
import copy
import struct
import unittest
from unittest.mock import patch

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from api_mode.gateway import GatewayConfig, SESSIONS, create_app
from api_mode.llm import ApiError, ApiResult


IMAGE = base64.b64encode(b'\x89PNG\r\n\x1a\nimage-fixture').decode()


class FakeProvider:
    def __init__(self, behavior=None):
        self.calls = []
        self.behavior = behavior
        self.opened = 0
        self.closed = 0
        self.running = 0
        self.max_running = 0
        self.closed_event = asyncio.Event()

    async def __aenter__(self):
        self.opened += 1
        return self

    async def __aexit__(self, *exc):
        self.closed += 1
        self.closed_event.set()

    async def complete(self, messages, *, on_delta):
        self.calls.append(copy.deepcopy(messages))
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            if self.behavior:
                return await self.behavior(messages, on_delta)
            chunks = ['<spe', 'ak:往左一点>', '<move:x=0.4><speak:可以了>']
            for chunk in chunks:
                on_delta(chunk)
                await asyncio.sleep(0)
            return ApiResult(''.join(chunks), metadata={'status': 'ok'})
        finally:
            self.running -= 1


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clients = []

    async def asyncTearDown(self):
        for client in reversed(self.clients):
            await client.close()

    async def server(self, fake=None, **config):
        fake = fake or FakeProvider()
        client = TestClient(TestServer(create_app(
            config=GatewayConfig(**{'visual_interval': 0, **config}),
            llm_factory=lambda: fake)))
        await client.start_server()
        self.clients.append(client)
        return client, fake

    async def connect(self, client, *, mode='video', prompt='拍照指导'):
        ws = await client.ws_connect('/v1/realtime?mode=' + mode)
        event = await ws.receive_json(timeout=2)
        self.assertEqual(event['type'], 'session.queue_done')
        await ws.send_json({'type': 'session.init', 'payload': {'system_prompt': prompt}})
        event = await ws.receive_json(timeout=2)
        self.assertEqual(event['type'], 'session.created')
        self.assertFalse(event['capabilities']['audio'])
        return ws

    async def until(self, ws, kind):
        events = []
        while True:
            event = await ws.receive_json(timeout=2)
            events.append(event)
            if event['type'] == kind:
                return events

    async def send(self, ws, text, **extra):
        await ws.send_json({'type': 'input.append', 'input': {'text': text, **extra}})

    async def test_health_and_unsupported_mode(self):
        client, fake = await self.server()
        health = await (await client.get('/health')).json()
        self.assertEqual(health['status'], 'healthy')
        status = await (await client.get('/status')).json()
        self.assertFalse(status['provider_verified'])
        self.assertEqual(status['capabilities'], {'text': True, 'image': True, 'audio': False})
        self.assertEqual((await client.get('/v1/realtime?mode=invalid')).status, 400)
        self.assertEqual(fake.opened, 0)

    async def test_raw_tag_stream_and_latest_image(self):
        client, fake = await self.server()
        ws = await self.connect(client)
        await self.send(ws, '我想拍活力照片', video_frames=[IMAGE])
        events = await self.until(ws, 'response.done')
        text = ''.join(e['text'] for e in events if e['type'] == 'response.output.delta')
        self.assertEqual(text, '<speak:往左一点><move:x=0.4><speak:可以了>')
        self.assertEqual(events[-1]['text'], text)
        self.assertEqual(len({e['response_id'] for e in events}), 1)
        self.assertEqual(fake.calls[0][0], {'role': 'system', 'content': '拍照指导'})
        content = fake.calls[0][1]['content']
        self.assertEqual(content[0]['text'], '我想拍活力照片')
        self.assertTrue(content[1]['image_url']['url'].startswith('data:image/png;base64,'))
        await self.send(ws, '我改成背对相机')
        await self.until(ws, 'response.done')
        self.assertEqual(fake.calls[1][1]['content'][0]['text'], '我想拍活力照片')
        self.assertEqual(fake.calls[1][-1]['content'][0]['text'], '我改成背对相机')

    async def test_chat_messages_and_image_blocks(self):
        client, fake = await self.server()
        ws = await self.connect(client, mode='chat', prompt='')
        await ws.send_json({'type': 'input.append', 'input': {'messages': [
            {'role': 'system', 'content': '聊天角色'},
            {'role': 'user', 'content': [{'type': 'text', 'text': '看图'},
                                         {'type': 'image', 'data': IMAGE}]}]}})
        await self.until(ws, 'response.done')
        self.assertEqual(fake.calls[0][0]['content'], '聊天角色')
        self.assertEqual(fake.calls[0][-1]['content'][1]['type'], 'image_url')
        await ws.send_json({'type': 'input.text', 'text': '继续'})
        await self.until(ws, 'response.done')
        self.assertEqual(fake.calls[1][0]['content'], '聊天角色')
        self.assertEqual(fake.calls[1][-1]['content'], '继续')

    async def test_interrupt_discards_late_chunks_and_failed_history(self):
        async def behavior(messages, on_delta):
            text = messages[-1]['content']
            if text == '旧目标':
                on_delta('旧输出')
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    # Model a transport callback racing with cancellation.
                    await asyncio.sleep(0.02)
                    on_delta('不得出现的迟到输出')
                    return ApiResult('旧输出不得出现的迟到输出')
            on_delta('新输出')
            return ApiResult('新输出')
        fake = FakeProvider(behavior)
        client, _ = await self.server(fake)
        ws = await self.connect(client)
        await self.send(ws, '旧目标')
        first = await ws.receive_json(timeout=2)
        self.assertEqual(first['text'], '旧输出')
        await self.send(ws, '新目标')
        events = await self.until(ws, 'response.done')
        self.assertEqual(events[0], {'type': 'response.interrupted',
                                     'response_id': first['response_id'], 'reason': 'new_input'})
        self.assertEqual([e['text'] for e in events if e['type'] == 'response.output.delta'], ['新输出'])
        self.assertNotEqual(events[-1]['response_id'], first['response_id'])
        self.assertEqual(fake.calls[1], [{'role': 'system', 'content': '拍照指导'},
                                         {'role': 'user', 'content': '旧目标'},
                                         {'role': 'user', 'content': '新目标'}])
        self.assertEqual(fake.max_running, 1)

    async def test_failure_is_explicit_and_history_unchanged(self):
        async def behavior(messages, on_delta):
            if messages[-1]['content'] == '失败':
                on_delta('<speak:未结束')
                raise ApiError('secret provider response must not be leaked',
                               ApiResult(metadata={'http_status': 429}))
            on_delta('成功')
            return ApiResult('成功')
        client, fake = await self.server(FakeProvider(behavior))
        ws = await self.connect(client)
        await self.send(ws, '失败')
        events = await self.until(ws, 'error')
        self.assertEqual(events[-1]['error']['code'], 'provider_error')
        self.assertNotIn('secret', str(events[-1]))
        self.assertIn('HTTP 429', events[-1]['error']['message'])
        self.assertFalse(any(e['type'] == 'response.done' for e in events))
        await self.send(ws, '重试')
        await self.until(ws, 'response.done')
        self.assertEqual(fake.calls[-1], [{'role': 'system', 'content': '拍照指导'},
                                          {'role': 'user', 'content': '失败'},
                                          {'role': 'user', 'content': '重试'}])

    async def test_camera_append_during_partial_tag_does_not_emit_listen(self):
        resume = asyncio.Event()
        async def behavior(messages, on_delta):
            on_delta('<speak:')
            await resume.wait()
            on_delta('向左一点>')
            return ApiResult('<speak:向左一点>')
        client, _ = await self.server(FakeProvider(behavior))
        ws = await self.connect(client)
        await self.send(ws, '开始指导')
        first = await ws.receive_json(timeout=2)
        self.assertEqual(first['text'], '<speak:')
        await ws.send_json({'type': 'input.append', 'input': {'video_frames': [IMAGE]}})
        # Force the server to process a second message before releasing generation.
        await ws.send_json({'type': 'unsupported'})
        error = await ws.receive_json(timeout=2)
        self.assertEqual(error['type'], 'error')
        resume.set()
        events = await self.until(ws, 'response.done')
        self.assertFalse(any(e.get('kind') == 'listen' for e in events))
        self.assertEqual(events[-1]['text'], '<speak:向左一点>')

    async def test_history_limit_does_not_drop_user_goal(self):
        client, fake = await self.server(max_turns=1)
        ws = await self.connect(client)
        await self.send(ws, '初始目标')
        await self.until(ws, 'response.done')
        await self.send(ws, '另一个目标')
        error = (await self.until(ws, 'error'))[-1]
        self.assertEqual(error['error']['code'], 'history_limit')
        self.assertEqual(len(fake.calls), 1)

    async def test_audio_warning_is_truthful_limited_and_silence_is_listen(self):
        client, fake = await self.server()
        ws = await self.connect(client, mode='audio')
        silence = base64.b64encode(struct.pack('<ffff', 0, 0, 0, 0)).decode()
        voice = base64.b64encode(struct.pack('<ffff', 0.1, -0.1, 0.2, 0)).decode()
        await ws.send_json({'type': 'input.append', 'input': {'audio': silence}})
        self.assertEqual((await ws.receive_json(timeout=2))['kind'], 'listen')
        await ws.send_json({'type': 'input.append', 'input': {'audio': voice}})
        warning = await ws.receive_json(timeout=2)
        self.assertEqual(warning['code'], 'audio_unsupported')
        self.assertIn('not transcribed', warning['message'])
        self.assertEqual((await ws.receive_json(timeout=2))['kind'], 'listen')
        await ws.send_json({'type': 'input.append', 'input': {'audio': voice}})
        self.assertEqual((await ws.receive_json(timeout=2))['kind'], 'listen')
        self.assertEqual(fake.calls, [])

    async def test_validation_errors_do_not_request_provider(self):
        client, fake = await self.server()
        ws = await self.connect(client)
        invalids = [
            {'type': 'input.append', 'input': {'video_frames': ['garbage']}},
            {'type': 'input.append', 'input': {'audio': base64.b64encode(b'x').decode()}},
            {'type': 'input.append', 'input': {'audio': base64.b64encode(struct.pack('<f', float('nan'))).decode()}},
            {'type': 'input.append', 'input': {'text': 42}},
            {'type': 'input.append', 'input': {'messages': [
                {'role': 'system', 'content': '偷偷替换角色'}, {'role': 'user', 'content': '你好'}]}},
        ]
        for event in invalids:
            await ws.send_json(event)
            self.assertEqual((await ws.receive_json(timeout=2))['error']['code'], 'invalid_request')
        self.assertEqual(fake.calls, [])

    async def test_reconnect_replaces_system_and_clears_old_context(self):
        client, fake = await self.server()
        ws = await self.connect(client, prompt='指导规则')
        await self.send(ws, '指导目标')
        await self.until(ws, 'response.done')
        await ws.send_json({'type': 'session.close', 'reason': 'mode_changed'})
        self.assertEqual((await ws.receive_json(timeout=2))['type'], 'session.closed')
        await ws.close()
        ws2 = await self.connect(client, prompt='合照规则')
        await self.send(ws2, '和我合照')
        await self.until(ws2, 'response.done')
        self.assertEqual(fake.calls[-1], [{'role': 'system', 'content': '合照规则'},
                                           {'role': 'user', 'content': '和我合照'}])
        await asyncio.wait_for(fake.closed_event.wait(), 2)
        self.assertGreaterEqual(fake.closed, 1)

    async def test_messages_snapshot_interruption_retains_pending_system_without_duplication(self):
        async def behavior(messages, on_delta):
            if messages[-1]['content'] == '新目标':
                on_delta('部分输出')
                await asyncio.sleep(10)
            on_delta('完成')
            return ApiResult('完成')
        client, fake = await self.server(FakeProvider(behavior))
        ws = await self.connect(client, mode='chat', prompt='')
        snapshot = [{'role': 'system', 'content': '合照规则'},
                    {'role': 'user', 'content': '早先目标'},
                    {'role': 'assistant', 'content': '早先建议'},
                    {'role': 'user', 'content': '新目标'}]
        await ws.send_json({'type': 'input.append', 'input': {'messages': snapshot}})
        self.assertEqual((await ws.receive_json(timeout=2))['text'], '部分输出')
        await self.send(ws, '补充目标')
        await self.until(ws, 'response.done')
        self.assertEqual(fake.calls[-1], snapshot + [{'role': 'user', 'content': '补充目标'}])

    async def test_writer_failure_closes_connection_and_provider(self):
        client, fake = await self.server()
        ws = await self.connect(client)
        session = next(iter(client.server.app[SESSIONS]))
        async def failed_send(*args, **kwargs):
            raise ConnectionResetError('disconnected client')
        with patch.object(session.ws, 'send_json', side_effect=failed_send):
            await self.send(ws, '开始')
            event = await ws.receive(timeout=2)
            self.assertIn(event.type, (WSMsgType.CLOSE, WSMsgType.CLOSED))
        await asyncio.wait_for(fake.closed_event.wait(), 2)

    async def test_output_backpressure_closes_explicitly_without_committing_history(self):
        async def behavior(messages, on_delta):
            for _ in range(300):
                on_delta('chunk')
            return ApiResult('incomplete')
        client, fake = await self.server(FakeProvider(behavior))
        ws = await self.connect(client)
        session = next(iter(client.server.app[SESSIONS]))
        await self.send(ws, '目标')
        while True:
            event = await ws.receive(timeout=2)
            if event.type in (WSMsgType.CLOSE, WSMsgType.CLOSED):
                break
        self.assertEqual(ws.close_code, 1013)
        self.assertEqual(session.history, [])
        await asyncio.wait_for(fake.closed_event.wait(), 2)

    async def test_observations_are_throttled_preserve_goal_and_replace_previous(self):
        client, fake = await self.server(visual_interval=0.06)
        ws = await self.connect(client)
        await ws.send_json({'type': 'input.append', 'input': {'video_frames': [IMAGE]}})
        await ws.receive_json(timeout=2)
        await asyncio.sleep(0.1)
        self.assertEqual(fake.calls, [])
        await self.send(ws, '想靠在树旁摆姿势')
        await self.until(ws, 'response.done')
        for _ in range(2):
            await ws.send_json({'type': 'input.append', 'input': {'video_frames': [IMAGE]}})
            await self.until(ws, 'response.done')
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(len(fake.calls[-1]), 6)  # system, human pair, previous observation pair, current image
        self.assertEqual(fake.calls[-1][1]['content'][0]['text'], '想靠在树旁摆姿势')
        await asyncio.sleep(0.1)
        self.assertEqual(len(fake.calls), 3)  # a frame version is observed at most once
        await self.send(ws, '我就想站在原地')
        await self.until(ws, 'response.done')
        self.assertEqual(fake.calls[-1][-1]['content'][0]['text'], '我就想站在原地')
        self.assertEqual(fake.max_running, 1)


if __name__ == '__main__':
    unittest.main()
