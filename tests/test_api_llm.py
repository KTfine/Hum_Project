"""Transport checks without devices, external requests or model credentials."""
import asyncio
import json
import unittest

import httpx

from api_mode.llm import ApiError, DeepSeekClient, Image


MESSAGES = [{'role': 'system', 'content': 'test system'}, {'role': 'user', 'content': 'hello'}]


def event(text='', finish=None, **delta):
    return ('data: ' + json.dumps({'choices': [{'delta': {'content': text, **delta},
                                              'finish_reason': finish}]}, ensure_ascii=False)
            + '\n\n').encode()


class Stream(httpx.AsyncByteStream):
    def __init__(self, pieces, delay=0):
        self.pieces, self.delay, self.closed = pieces, delay, False

    async def __aiter__(self):
        for piece in self.pieces:
            await asyncio.sleep(self.delay)
            yield piece

    async def aclose(self):
        self.closed = True


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_utf8_split_stream_and_reasoning_isolation(self):
        raw = event('<speak:你好')
        index = raw.index('你'.encode()) + 1
        stream = Stream([event(reasoning_content='private reasoning'), raw[:index], raw[index:],
                         event('。><move:by,dx=0.1>'), event(finish='stop'), b'data: [DONE]\n\n'])
        captured, seen = [], []

        def handler(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)

        async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(handler)) as client:
            result = await client.complete(MESSAGES, on_delta=seen.append)
        self.assertEqual(result.text, '<speak:你好。><move:by,dx=0.1>')
        self.assertEqual(''.join(seen), result.text)
        self.assertNotIn('private reasoning', ''.join(seen))
        self.assertEqual(captured[0]['messages'], MESSAGES)
        self.assertTrue(stream.closed)

    async def test_status_errors_do_not_echo_key_or_follow_redirects(self):
        for status in (401, 429, 302):
            calls = []

            def handler(request):
                calls.append(request)
                return httpx.Response(status, text='unit-secret', headers={'location': 'https://example.org'})

            async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(ApiError) as raised:
                    await client.complete(MESSAGES)
            self.assertEqual(len(calls), 1)
            self.assertNotIn('unit-secret', str(raised.exception))
            self.assertNotIn('unit-secret', json.dumps(raised.exception.result.metadata))

    async def test_incomplete_length_and_malformed_streams_fail(self):
        for raw in (event('<speak:partial'), event('cut', finish='length') + b'data: [DONE]\n\n',
                    b'data: {broken}\n\n'):
            async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(lambda request: httpx.Response(
                    200, headers={'content-type': 'text/event-stream'}, content=raw))) as client:
                with self.assertRaises(ApiError):
                    await client.complete(MESSAGES)

    async def test_deadline_covers_headers_and_stream(self):
        async def slow_headers(request):
            await asyncio.sleep(1)
            return httpx.Response(200)

        stream = Stream([event('late')], delay=1)
        for handler in (slow_headers, lambda request: httpx.Response(
                200, headers={'content-type': 'text/event-stream'}, stream=stream)):
            async with DeepSeekClient('unit-secret', timeout=.03, transport=httpx.MockTransport(handler)) as client:
                with self.assertRaises(ApiError) as raised:
                    await client.complete(MESSAGES)
            self.assertEqual(raised.exception.result.metadata['error'], 'TimeoutError')
        self.assertTrue(stream.closed)

    async def test_cancellation_closes_stream_and_keeps_partial_result(self):
        stream = Stream([event('late')], delay=10)
        async with DeepSeekClient('unit-secret', transport=httpx.MockTransport(lambda request: httpx.Response(
                200, headers={'content-type': 'text/event-stream'}, stream=stream))) as client:
            task = asyncio.create_task(client.complete(MESSAGES))
            await asyncio.sleep(.02)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError) as raised:
                await task
        self.assertEqual(raised.exception.result.metadata['status'], 'cancelled')
        self.assertTrue(stream.closed)

    def test_image_format_validation(self):
        self.assertTrue(Image(b'\x89PNG\r\n\x1a\nmock').block()['image_url']['url'].startswith('data:image/png;base64,'))
        with self.assertRaises(ValueError):
            Image(b'not an image').block()


if __name__ == '__main__':
    unittest.main()
