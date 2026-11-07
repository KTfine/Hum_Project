"""Exercise model-selected prompt reloads, with actual parsing and dispatch."""
import asyncio
import base64
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import realtime_av_test as client


class Log:
    def __init__(self):
        self.rows = []
    def record(self, event, **fields):
        self.rows.append(dict(event=event, **fields))
    def record_message(self, event, message):
        self.record(event, message=message)


class Socket:
    def __init__(self, events):
        self.incoming = asyncio.Queue()
        for event in events:
            self.incoming.put_nowait(event)
        self.sent = []
        self.closed = False
    async def recv(self):
        return json.dumps(await self.incoming.get())
    async def send(self, data):
        event = json.loads(data)
        self.sent.append(event)
        if event['type'] == 'session.close':
            self.incoming.put_nowait({'type': 'session.closed', 'reason': event['reason']})
    async def close(self):
        self.closed = True


def text(value):
    return {'type': 'response.output.delta', 'kind': 'text', 'text': value, 'response_id': 'r'}


class PromptHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        cv2.imwrite(str(Path(self.folder.name)/'normal.png'), np.full((10, 10, 4), 255, dtype=np.uint8))
        self.stop = threading.Event()
        self.canvas = client.CanvasSource(Path(self.folder.name), 'normal', 200, 100, 80,
                                         self.stop, preview=False)
        self.camera = type('Camera', (), {'latest_frame': lambda _: np.zeros((100, 200, 3), dtype=np.uint8)})()
        self.canvas.start()
        self.args = client.parse_args(['--no-preview'])
        self.log = Log()
        self.prompts = []
        self.selection = client.ModeSelection()

    async def asyncTearDown(self):
        self.canvas.close()
        self.folder.cleanup()

    async def run_sessions(self, opener):
        with patch.object(client, 'connect_and_open_session_with_retry', side_effect=opener), contextlib.redirect_stdout(io.StringIO()):
            await asyncio.wait_for(client.run_realtime_sessions(
                None, 'wss://unused', None, self.canvas, self.camera,
                client.AudioInputBuffer(), client.SpeechQueue(), self.stop,
                self.args, event_log=self.log, mode_selection=self.selection,
            ), timeout=2)

    async def test_both_mode_transitions_preserve_geometry_and_confirm_after_open(self):
        sockets = [
            Socket([text('<move:to,x=0.4,y=0.8,ms=0><mode:co-photo>')]),
            Socket([text('<mode:co-photo><move:by,dx=-0.1,ms=0><mode:guidance>')]),
            Socket([text('<scale:to,value=0.8,ms=0><speak:继续。>'), {'type':'session.closed'}]),
        ]
        async def opener(*args, **kwargs):
            index = len(self.prompts)
            self.prompts.append(args[3]['payload']['system_prompt'])
            if index:
                self.assertTrue(sockets[index-1].closed)
                self.assertEqual(self.selection.co_photo_active, index == 2)
                self.assertFalse(self.stop.is_set())
            return sockets[index], {'session_id': str(index)}
        await self.run_sessions(opener)
        self.assertEqual(len(self.prompts), 3)
        for prompt, task in zip(self.prompts, ['真人拍照指导', '合照互动', '真人拍照指导']):
            self.assertIn(f'当前任务：{task}', prompt)
        self.assertIn('"x": 0.4', self.prompts[1])
        self.assertNotIn('"x":', self.prompts[0])
        self.assertNotIn('"x":', self.prompts[2])
        self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.3)
        self.assertAlmostEqual(self.canvas.controller.state_at().y, 0.8)
        self.assertEqual(self.canvas.controller.state_at().scale, 0.8)
        self.assertEqual([r['co_photo_active'] for r in self.log.rows if r['event']=='session.mode_ready'],
                         [False, True, False])
        self.assertEqual([r['text'] for r in self.log.rows if r['event']=='speak'], ['继续。'])
        self.assertTrue(all(s.closed for s in sockets))
        self.assertEqual(sockets[0].sent[-1]['reason'], 'mode_changed')
        self.assertEqual([r['include_character'] for r in self.log.rows if r['event']=='session.mode_ready'],
                         [False, True, False])
        for index, socket in enumerate(sockets):
            messages = [m for m in socket.sent if m['type'] == 'input.append']
            self.assertTrue(messages)
            data = base64.b64decode(messages[0]['input']['video_frames'][0])
            frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            if index == 1:
                self.assertGreater(float(frame.mean()), 1)
            else:
                self.assertTrue(np.all(frame == 0))
        np.testing.assert_array_equal(self.canvas.render_preview_frame(), self.camera.latest_frame())

    async def test_same_mode_and_plain_invitation_do_not_reconnect(self):
        socket = Socket([text('和我合照。<mode:guidance><speak:你好。>'), {'type':'session.closed'}])
        async def opener(*args, **kwargs):
            self.prompts.append(args[3]['payload']['system_prompt'])
            return socket, {}
        await self.run_sessions(opener)
        self.assertEqual(len(self.prompts), 1)
        self.assertFalse(self.selection.co_photo_active)

    async def test_failed_reload_keeps_last_confirmed_mode_and_closes_old_socket(self):
        socket = Socket([text('<mode:co-photo>')])
        async def opener(*args, **kwargs):
            self.prompts.append(args[3]['payload']['system_prompt'])
            if len(self.prompts) == 2:
                raise RuntimeError('reload failed')
            return socket, {}
        with self.assertRaisesRegex(RuntimeError, 'reload failed'):
            await self.run_sessions(opener)
        self.assertTrue(socket.closed)
        self.assertFalse(self.selection.co_photo_active)
        self.assertEqual(self.selection.mode, 'co-photo')
        self.assertEqual(sum(r['event']=='session.mode_ready' for r in self.log.rows), 1)
        np.testing.assert_array_equal(self.canvas.render_preview_frame(), self.camera.latest_frame())

    async def test_custom_override_has_no_builtin_mode_claim_or_reload(self):
        self.args.prompt = 'custom instructions'
        socket = Socket([text('<mode:co-photo><move:to,x=0.2,ms=0>'), {'type':'session.closed'}])
        async def opener(*args, **kwargs):
            self.prompts.append(args[3]['payload']['system_prompt'])
            return socket, {}
        await self.run_sessions(opener)
        self.assertEqual(self.prompts, ['custom instructions'])
        self.assertIsNone(self.selection.co_photo_active)
        self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.2)
        self.assertEqual([r['mode'] for r in self.log.rows if r['event']=='session.mode_ready'], ['custom'])

    async def test_user_stop_closes_session_without_mode_reload(self):
        socket = Socket([])
        async def opener(*args, **kwargs):
            self.prompts.append(args[3]['payload']['system_prompt'])
            asyncio.get_running_loop().call_later(0.01, self.stop.set)
            return socket, {}
        await self.run_sessions(opener)
        self.assertEqual(len(self.prompts), 1)
        self.assertTrue(socket.closed)

    async def test_device_cleanup_on_session_failure(self):
        camera, microphone = MagicMock(), MagicMock()
        with patch.object(client, 'CanvasSource', return_value=self.canvas), \
             patch.object(client, 'CameraSource', return_value=camera), \
             patch.object(client, 'MicrophoneSource', return_value=microphone), \
             patch.object(client, 'run_realtime_sessions', new=AsyncMock(side_effect=RuntimeError('failed'))), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                await client.run_probe(self.args, self.log)
        microphone.close.assert_called_once()
        camera.close.assert_called_once()

    async def test_replay_uses_the_same_two_mode_prompts(self):
        from tools import runtime_effect_probe as probe
        root = Path(self.folder.name)
        media = root/'runtime_results'
        media.mkdir()
        with wave.open(str(media/'cmd.wav'), 'wb') as output:
            output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            output.writeframes(b'\0'*32000)
        schedule = root/'schedule.json'
        schedule.write_text('[[0,"cmd.wav"]]', encoding='utf-8')
        class ResponsiveSocket(Socket):
            def __init__(self, response):
                super().__init__([])
                self.response = response
            async def send(self, data):
                await super().send(data)
                if json.loads(data)['type'] == 'input.append':
                    self.incoming.put_nowait(text(self.response))
        sockets = [ResponsiveSocket('<mode:co-photo>'),
                   ResponsiveSocket('<move:to,x=0.3,ms=0><mode:guidance>'),
                   ResponsiveSocket('<speak:好。>')]
        async def opener(*args, **kwargs):
            index = len(self.prompts)
            self.prompts.append(args[3]['payload']['system_prompt'])
            if index:
                self.assertTrue(sockets[index-1].closed)
            return sockets[index], {}
        camera = MagicMock()
        camera.latest_frame.return_value = np.zeros((100, 200, 3), dtype=np.uint8)
        args = SimpleNamespace(output_subdir='replay', preview=False, no_camera=False, prompt_file=None,
            generation_config=None, instructions_file=str(schedule), visual_check=False,
            url='https://unused', seconds=3)
        with patch.object(probe, 'ROOT', root), patch.object(client, 'CanvasSource', return_value=self.canvas), \
             patch.object(client, 'CameraSource', return_value=camera), \
             patch.object(client, 'connect_and_open_session_with_retry', side_effect=opener), \
             contextlib.redirect_stdout(io.StringIO()):
            await asyncio.wait_for(probe.run(args), timeout=5)
        self.assertEqual(len(self.prompts), 3)
        rows = [json.loads(line) for line in (media/'replay/effect-probe.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([r['co_photo_active'] for r in rows if r['event']=='session.mode_ready'],
                         [False, True, False])
        self.assertEqual([r['include_character'] for r in rows if r['event']=='session.mode_ready'],
                         [False, True, False])
        for index, socket in enumerate(sockets):
            message = next(m for m in socket.sent if m['type']=='input.append')
            data = base64.b64decode(message['input']['video_frames'][0])
            frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(bool(np.any(frame)), index == 1)
        self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.3)


if __name__ == '__main__':
    unittest.main()
