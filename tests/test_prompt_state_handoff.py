"""Exercise state handoff through real parsing and dispatch, without a GPU."""
import asyncio
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
        sprite = np.full((10, 10, 4), 255, dtype=np.uint8)
        cv2.imwrite(str(Path(self.folder.name)/'normal.png'), sprite)
        self.stop = threading.Event()
        self.canvas = client.CanvasSource(Path(self.folder.name), 'normal', 200, 100, 80, self.stop, preview=False)
        self.camera = type('Camera', (), {'latest_frame': lambda _: np.zeros((100, 200, 3), dtype=np.uint8)})()
        self.canvas.set_camera(self.camera)
        self.canvas.start()
        self.args = client.parse_args(['--no-preview'])
        self.log = Log()
        self.prompts = []

    async def asyncTearDown(self):
        self.canvas.close()
        self.folder.cleanup()

    async def run_sessions(self, opener):
        with patch.object(client, 'connect_and_open_session_with_retry', side_effect=opener), contextlib.redirect_stdout(io.StringIO()):
            await asyncio.wait_for(client.run_realtime_sessions(
                None, 'wss://unused', None, self.canvas, self.camera,
                client.AudioInputBuffer(), client.SpeechQueue(), self.stop,
                self.args, event_log=self.log,
            ), timeout=1)

    async def test_activation_refreshes_prompt_before_goal_question_and_preserves_geometry(self):
        self.canvas.controller.apply_command(client.Command('move', {'mode':'to', 'x':0.4, 'y':0.8, 'ms':0}))
        first = Socket([text('<move:to,x=0.9,ms=0><photo:enter>')])
        second = Socket([text('<photo:enter><move:to,x=0.3,ms=0>'), {'type': 'session.closed'}])
        async def open_session(*args, **kwargs):
            self.prompts.append(args[3]['payload']['system_prompt'])
            if len(self.prompts) == 1:
                return first, {'session_id': 'off'}
            self.assertTrue(first.closed)
            self.assertFalse(self.stop.is_set())
            self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.4)
            self.assertAlmostEqual(self.canvas.controller.state_at().y, 0.8)
            self.assertEqual([r for r in self.log.rows if r['event']=='co_photo.goal_requested'], [])
            return second, {'session_id': 'on'}
        await self.run_sessions(open_session)
        self.assertEqual(len(self.prompts), 2)
        self.assertIn('当前合照状态：OFF', self.prompts[0])
        self.assertIn('"co_photo_active": false', self.prompts[0])
        self.assertIn('当前合照状态：ON', self.prompts[1])
        self.assertIn('"co_photo_active": true', self.prompts[1])
        self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.3)
        self.assertEqual(first.sent[-1]['reason'], 'co_photo_state_changed')
        self.assertEqual(sum(r['event']=='co_photo.goal_requested' for r in self.log.rows), 1)
        self.assertEqual(sum(r['event']=='session.prompt_refresh' for r in self.log.rows), 1)
        self.assertTrue(second.closed)

    async def test_no_invitation_does_not_reconnect_or_ask(self):
        socket = Socket([text('<speak:保持。>'), {'type': 'session.closed'}])
        async def open_session(*args, **kwargs):
            self.prompts.append(args[3]['payload']['system_prompt'])
            return socket, {'session_id': 'off'}
        await self.run_sessions(open_session)
        self.assertEqual(len(self.prompts), 1)
        self.assertFalse(self.canvas.co_photo.active)
        self.assertFalse(any(r['event']=='co_photo.goal_requested' for r in self.log.rows))

    async def test_custom_prompt_is_not_silently_replaced(self):
        self.args.prompt = 'custom instructions'
        socket = Socket([text('<photo:enter>'), {'type': 'session.closed'}])
        async def open_session(*args, **kwargs):
            self.prompts.append(args[3]['payload']['system_prompt'])
            return socket, {'session_id': 'custom'}
        await self.run_sessions(open_session)
        self.assertEqual(self.prompts, ['custom instructions'])
        self.assertEqual(sum(r['event']=='co_photo.goal_requested' for r in self.log.rows), 1)

    async def test_failed_refresh_closes_old_socket_without_asking_early(self):
        socket = Socket([text('<photo:enter>')])
        async def open_session(*args, **kwargs):
            self.prompts.append(args[3]['payload']['system_prompt'])
            if len(self.prompts) == 2:
                raise RuntimeError('refresh failed')
            return socket, {'session_id': 'off'}
        with self.assertRaisesRegex(RuntimeError, 'refresh failed'):
            await self.run_sessions(open_session)
        self.assertTrue(socket.closed)
        self.assertFalse(any(r['event']=='co_photo.goal_requested' for r in self.log.rows))

    async def test_user_stop_while_waiting_does_not_reconnect(self):
        socket = Socket([])
        async def open_session(*args, **kwargs):
            self.prompts.append(args[3]['payload']['system_prompt'])
            asyncio.get_running_loop().call_later(0.01, self.stop.set)
            return socket, {'session_id': 'off'}
        await self.run_sessions(open_session)
        self.assertEqual(len(self.prompts), 1)
        self.assertTrue(socket.closed)

    async def test_app_releases_devices_if_model_session_refresh_fails(self):
        camera = MagicMock()
        camera.latest_frame.return_value = np.zeros((100, 200, 3), dtype=np.uint8)
        microphone = MagicMock()
        with patch.object(client, 'CanvasSource', return_value=self.canvas), \
             patch.object(client, 'CameraSource', return_value=camera), \
             patch.object(client, 'MicrophoneSource', return_value=microphone), \
             patch.object(client, 'run_realtime_sessions', new=AsyncMock(side_effect=RuntimeError('refresh failed'))), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'refresh failed'):
                await client.run_probe(self.args, self.log)
        microphone.start.assert_called_once()
        microphone.close.assert_called_once()
        camera.close.assert_called_once()

    async def test_managed_replay_also_refreshes_state_and_executes_move(self):
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
        first = ResponsiveSocket('<photo:enter>')
        second = ResponsiveSocket('<move:to,x=0.3,ms=0>')
        async def open_session(*args, **kwargs):
            self.prompts.append(args[3]['payload']['system_prompt'])
            if len(self.prompts) == 1:
                return first, {'session_id': 'off'}
            self.assertTrue(first.closed)
            return second, {'session_id': 'on'}
        camera = MagicMock()
        camera.latest_frame.return_value = np.zeros((100, 200, 3), dtype=np.uint8)
        args = SimpleNamespace(output_subdir='replay', preview=False, no_camera=False,
            start_co_photo=False, co_photo=True, action_only=False, prompt_file=None,
            generation_config=None, instructions_file=str(schedule), visual_check=False,
            url='https://unused', seconds=2)
        with patch.object(probe, 'ROOT', root), \
             patch.object(client, 'CanvasSource', return_value=self.canvas), \
             patch.object(client, 'CameraSource', return_value=camera), \
             patch.object(client, 'connect_and_open_session_with_retry', side_effect=open_session), \
             contextlib.redirect_stdout(io.StringIO()):
            await asyncio.wait_for(probe.run(args), timeout=4)
        self.assertEqual(len(self.prompts), 2)
        self.assertIn('当前合照状态：OFF', self.prompts[0])
        self.assertIn('当前合照状态：ON', self.prompts[1])
        self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.3)
        rows = [json.loads(line) for line in (media/'replay/effect-probe.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(sum(r['event']=='co_photo.goal_requested' for r in rows), 1)


if __name__ == '__main__':
    unittest.main()
