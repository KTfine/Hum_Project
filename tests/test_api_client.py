import asyncio
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from experiments.scripts.hum_api import ApiError, DeepSeekClient, Image, PhotoSession, build_prompt
from experiments.scripts.hum_api.__main__ import parse_args, run


def event(text='', finish=None, **extra):
    obj = {'model': 'test-model', 'system_fingerprint': 'test-fingerprint',
           'choices': [{'delta': {'content': text}, 'finish_reason': finish}], **extra}
    return ('data: ' + json.dumps(obj, ensure_ascii=False) + '\n\n').encode()


class Stream(httpx.AsyncByteStream):
    def __init__(self, pieces, before=None, delay=0):
        self.pieces, self.before, self.delay = pieces, before, delay
        self.closed = False

    async def __aiter__(self):
        for i, piece in enumerate(self.pieces):
            if self.before:
                self.before(i)
            await asyncio.sleep(self.delay)
            yield piece

    async def aclose(self):
        self.closed = True


def response(*parts, done=True, finish='stop'):
    pieces = [event(p) for p in parts] + [event(finish=finish)]
    if done:
        pieces += [b'data: [DONE]\n\n']
    return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Stream(pieces))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_commands_execute_on_closure_across_utf8_chunks_before_done(self):
        seen = []
        first = event('<speak:你好')
        second = event('。><move:by,dx=0.1><tachie:smile>')
        def before(i):
            if i == 3:
                self.assertEqual([c.kind for c in seen], ['speak', 'move', 'tachie'])
        split = first.index('你'.encode()) + 1
        stream = Stream([first[:split], first[split:], second, event(finish='stop'), b'data: [DONE]\n\n'], before)
        async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(lambda r: httpx.Response(
                200, headers={'content-type': 'text/event-stream'}, stream=stream))) as client:
            session = PhotoSession(client)
            result = await session.ask('hello', on_command=seen.append)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(result.commands[0].params['text'], '你好。')
        self.assertTrue(stream.closed)

    async def test_images_observations_and_successful_history_are_sent(self):
        requests = []
        def handle(r):
            requests.append(json.loads(r.content))
            return response('<speak:好>')
        async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(handle)) as client:
            session = PhotoSession(client)
            await session.ask('first', images=[Image(b'\x89PNG\r\n\x1a\nmock')], observations={'mirrored': False})
            await session.ask('next')
        first, second = requests
        self.assertEqual(first['thinking'], {'type': 'enabled'})
        self.assertEqual(first['reasoning_effort'], 'low')
        self.assertTrue(first['messages'][1]['content'][0]['image_url']['url'].startswith('data:image/png;base64,'))
        self.assertIn('false', first['messages'][1]['content'][2]['text'])
        self.assertEqual([m['role'] for m in second['messages']], ['system', 'user', 'assistant', 'user'])
        copy = session.history
        copy.clear()
        self.assertEqual(len(session.history), 4)

    async def test_modes_reset_history_only_after_success(self):
        replies = iter(['<mode:co-photo>', '<speak:继续><mode:co-photo>', '<mode:guidance>'])
        async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(lambda r: response(next(replies)))) as client:
            session = PhotoSession(client, sprite_ids=['normal'], character_state={'x': .4})
            await session.ask('一起拍')
            self.assertEqual(session.mode, 'co-photo')
            self.assertEqual(session.history, [])
            self.assertIn('可用立绘 ID', session.system_prompt)
            await session.ask('继续')
            self.assertEqual(len(session.history), 2)
            await session.ask('恢复指导')
            self.assertNotIn('可用立绘 ID', session.system_prompt)
            self.assertEqual(session.history, [])

    async def test_failed_turn_keeps_previous_history_and_mode(self):
        count = 0
        def handle(r):
            nonlocal count
            count += 1
            return response('<speak:好>') if count == 1 else response('<mode:co-photo>', done=False)
        async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(handle)) as client:
            session = PhotoSession(client)
            await session.ask('first')
            with self.assertRaises(ApiError) as ctx:
                await session.ask('second')
            self.assertEqual(session.mode, 'guidance')
            self.assertEqual(len(session.history), 2)
            self.assertEqual(ctx.exception.result.commands[0].kind, 'mode')
        self.assertEqual(count, 2)  # No automatic retry, even if commands already emitted.

    async def test_length_and_malformed_stream_are_failures(self):
        for reply in [response('<speak:cut', finish='length'), httpx.Response(200,
                     headers={'content-type': 'text/event-stream'}, content=b'data: {broken}\n\n')]:
            async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(lambda r: reply)) as client:
                session = PhotoSession(client)
                with self.assertRaises(ApiError):
                    await session.ask('x')
                self.assertEqual(session.history, [])

    async def test_auth_and_redirect_fail_without_echoing_body_or_retry(self):
        for status in (401, 429, 302):
            calls = []
            def handle(r):
                calls.append(r)
                return httpx.Response(status, headers={'location': 'https://example.org'}, text='unit-secret')
            async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(handle)) as client:
                with self.assertRaises(ApiError) as ctx:
                    await PhotoSession(client).ask('x')
                self.assertNotIn('unit-secret', str(ctx.exception))
                self.assertNotIn('unit-secret', json.dumps(ctx.exception.result.metadata))
            self.assertEqual(len(calls), 1)

    async def test_total_deadline_covers_waiting_for_headers_and_stream(self):
        async def slow_headers(r):
            await asyncio.sleep(1)
            return response('<speak:late>')
        stream = Stream([event('<speak:late>')], delay=1)
        def slow_stream(r):
            return httpx.Response(200, headers={'content-type':'text/event-stream'}, stream=stream)
        for handler in (slow_headers, slow_stream):
            async with DeepSeekClient('unit-secret', timeout=.03, transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(ApiError) as ctx:
                    await PhotoSession(client).ask('x')
                self.assertEqual(ctx.exception.result.metadata['error'], 'TimeoutError')
        self.assertTrue(stream.closed)

    async def test_custom_prompt_is_literal_and_does_not_switch(self):
        async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(lambda r: response('<mode:co-photo>'))) as client:
            session = PhotoSession(client, system_prompt='literal {my_json}', max_turns=1)
            await session.ask('x')
            self.assertEqual(session.system_prompt, 'literal {my_json}')
            self.assertEqual(session.mode, 'guidance')
            with self.assertRaises(ValueError):
                await session.ask('too many')
            session.reset()
            self.assertEqual(session.history, [])

    async def test_cancellation_and_overlapping_turn_do_not_commit_history(self):
        entered = asyncio.Event()
        async def handler(r):
            entered.set()
            await asyncio.sleep(10)
            return response('<speak:late>')
        async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(handler)) as client:
            session = PhotoSession(client)
            task = asyncio.create_task(session.ask('first'))
            await entered.wait()
            with self.assertRaises(RuntimeError):
                await session.ask('overlap')
            task.cancel()
            with self.assertRaises(asyncio.CancelledError) as ctx:
                await task
            self.assertEqual(ctx.exception.result.metadata['status'], 'cancelled')
            self.assertEqual(session.history, [])
            session.reset()

    async def test_reasoning_does_not_reach_callbacks_or_history(self):
        raw = event('', choices=[{'delta':{'reasoning_content':'private reasoning'},'finish_reason':None}])
        raw += event('<speak:final>', finish='stop') + b'data: [DONE]\n\n'
        async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(lambda r: httpx.Response(
                200, headers={'content-type': 'text/event-stream'}, content=raw))) as client:
            session = PhotoSession(client)
            result = await session.ask('x')
        self.assertEqual(result.metadata['reasoning_chars'], len('private reasoning'))
        self.assertNotIn('private reasoning', json.dumps(session.history))

    async def test_plain_text_adaptation_is_explicit_and_measured(self):
        async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(lambda r: response('普通文字'))) as client:
            strict = await PhotoSession(client).ask('x')
            adapted = await PhotoSession(client, allow_plain_speech=True).ask('x')
        self.assertEqual(strict.commands, [])
        self.assertEqual(adapted.commands[0].kind, 'speak')
        self.assertGreater(adapted.metadata['plain_speech_fragments'], 0)

    async def test_cli_logs_system_hash_status_but_not_image_bytes_or_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'run.jsonl'
            real = DeepSeekClient
            factory = lambda **kw: real('unit-secret', transport=httpx.MockTransport(lambda r: response('<speak:好>')), **kw)
            with patch('experiments.scripts.hum_api.__main__.DeepSeekClient', factory), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                code = await run(parse_args(['--text','hello','--log-file',str(log)]))
            data = log.read_text(encoding='utf-8')
            self.assertEqual(code, 0)
            self.assertNotIn('unit-secret', data)
            last = json.loads(data.splitlines()[-1])
            self.assertEqual(last['status'], 'ok')
            self.assertEqual(len(last['system_sha256']), 64)


class PromptTests(unittest.TestCase):
    def test_guidance_stays_free_of_sprite_context_and_audio_claims(self):
        text = build_prompt(sprite_ids=['secret-sprite'], character_state={'x':.1})
        self.assertNotIn('secret-sprite', text)
        self.assertNotIn('麦克风', text)
        self.assertNotIn('初始角色状态', text)
        self.assertIn('<mode:co-photo>', text)

    def test_co_photo_accepts_module_supplied_state_and_catalog(self):
        text = build_prompt('co-photo', sprite_ids=['smile','normal'], character_state={'x':.4})
        self.assertIn('normal, smile', text)
        self.assertIn('"x": 0.4', text)
        self.assertIn('<move:', text)

    def test_missing_key_and_bad_image_fail_locally(self):
        with patch.dict('os.environ', {}, clear=True), self.assertRaises(ValueError):
            DeepSeekClient()
        with self.assertRaises(ValueError):
            Image(b'not an image').block()


if __name__ == '__main__':
    unittest.main()
