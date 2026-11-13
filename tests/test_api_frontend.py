"""API frontend checks without opening a camera, microphone, or remote API."""
import asyncio
import base64
import contextlib
import io
import json
import os
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import realtime_av_test as client


class Log:
    def __init__(self):
        self.rows = []

    def record(self, event, **fields):
        self.rows.append(dict(event=event, **fields))

    def record_message(self, event, message):
        self.record(event, message=message)


class BackendSelectionTests(unittest.TestCase):
    def test_defaults_keep_minicpm_behavior_and_api_does_not_open_mic(self):
        original = client.parse_args([])
        api = client.parse_args(["--backend", "api"])
        self.assertEqual((original.backend, original.url, original.no_mic),
                         ("minicpm", "https://localhost:8006", False))
        self.assertEqual((api.url, api.no_mic, api.no_camera),
                         ("http://127.0.0.1:8006", True, False))
        self.assertEqual(client.normalize_video_ws_url(api.url),
                         "ws://127.0.0.1:8006/v1/realtime?mode=video")
        self.assertEqual(client.parse_args(["--backend", "api", "--url", "https://custom:9"]).url,
                         "https://custom:9")

    def test_api_prompt_adapts_transport_but_retains_task_and_tag_rules(self):
        canvas = SimpleNamespace(
            sprite_ids=["normal"],
            controller=SimpleNamespace(state_at=lambda: client.SpriteState("normal", .5, .95, 1, 0)),
        )
        for mode in client.MODES:
            original = client.build_control_prompt(canvas, client.parse_args([]), mode=mode)
            api = client.build_control_prompt(canvas, client.parse_args(["--backend", "api"]), mode=mode)
            expected = original.replace("你持续接收用户麦克风音频和摄像头画面。",
                                        "你持续接收用户文字输入和摄像头画面。")
            expected = expected.replace("用户通过麦克风与你说话；保持回复简短。",
                                        "用户通过文字输入与你交流；你会持续收到摄像头画面；保持回复简短。")
            self.assertEqual(api, expected)
            self.assertNotIn("麦克风", api)


class ConsoleInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_pipe_poll_does_not_block_and_preserves_split_utf8_and_eof(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(read_fd, "r", encoding="utf-8")
        source = client.ConsoleTextInput(stream)
        stop = threading.Event()
        try:
            source.poll()  # no data available: must return without waiting
            self.assertIsNone(source.peek())
            encoded = "向左移动\n我想站着".encode("utf-8")
            os.write(write_fd, encoded[:2])
            source.poll()
            self.assertIsNone(source.peek())
            os.write(write_fd, encoded[2:])
            source.poll()
            self.assertEqual(source.peek(), "向左移动")
            os.close(write_fd)
            write_fd = None
            with contextlib.redirect_stdout(io.StringIO()):
                await asyncio.wait_for(source.run(stop), .5)
            self.assertTrue(source.eof)
            self.assertFalse(stop.is_set())
            self.assertEqual(list(source.pending), ["向左移动", "我想站着"])
        finally:
            stream.close()
            if write_fd is not None:
                os.close(write_fd)

    async def test_cancelled_reader_does_not_create_blocking_input_threads(self):
        source = client.ConsoleTextInput()
        before = set(threading.enumerate())
        with patch.object(source, "poll"):
            task = asyncio.create_task(source.run(threading.Event()))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(set(threading.enumerate()), before)


class ApiInputSenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_send_retains_text_for_the_next_model_session(self):
        source = client.ConsoleTextInput()
        source.put("和我合照")
        source.put("我想站着")
        canvas = MagicMock()
        canvas.latest_jpeg.return_value = b"camera-jpeg"
        first_started = asyncio.Event()

        async def blocked_send(_payload):
            first_started.set()
            await asyncio.Future()

        old = SimpleNamespace(send=blocked_send)
        task = asyncio.create_task(client.send_realtime_inputs(
            old, canvas, None, client.AudioInputBuffer(), threading.Event(),
            include_character=False, text_input=source,
        ))
        await first_started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(source.peek(), "和我合照")

        sent = []
        stop = threading.Event()

        async def send(payload):
            sent.append(json.loads(payload))
            stop.set()

        await client.send_realtime_inputs(
            SimpleNamespace(send=send), canvas, None, client.AudioInputBuffer(), stop,
            include_character=True, text_input=source,
        )
        self.assertEqual(sent[0]["input"]["text"], "和我合照")
        self.assertEqual(base64.b64decode(sent[0]["input"]["video_frames"][0]), b"camera-jpeg")
        self.assertEqual(len(base64.b64decode(sent[0]["input"]["audio"])), client.AUDIO_CHUNK_BYTES)
        self.assertEqual(source.peek(), "我想站着")

    async def test_api_probe_never_constructs_microphone_and_keeps_tts_off(self):
        args = client.parse_args(["--backend", "api", "--no-camera", "--no-preview"])
        canvas = MagicMock(error=None, sprite_ids=["normal"])
        with patch.object(client, "CanvasSource", return_value=canvas), \
             patch.object(client, "MicrophoneSource") as microphone, \
             patch.object(client, "ConsoleTextInput") as console, \
             patch.object(client, "run_realtime_sessions", new=AsyncMock()) as sessions, \
             contextlib.redirect_stdout(io.StringIO()):
            console.return_value.run = AsyncMock()
            await client.run_probe(args)
        microphone.assert_not_called()
        self.assertIs(sessions.call_args.kwargs["text_input"], console.return_value)
        init = client.build_session_init("test", use_tts=False)
        self.assertFalse(init["payload"]["use_tts"])
        self.assertFalse(init["payload"]["config"]["generate_audio"])


class InterruptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_interruption_discards_partial_tag_and_all_late_old_output(self):
        def text(response, value):
            return dict(type="response.output.delta", kind="text", response_id=response, text=value)

        incoming = iter([
            text("old", "<move:to,x="),
            dict(type="response.interrupted", response_id="old", reason="new_input"),
            text("new", "<speak:现在站好><move:to,x="),
            text("old", "0.1><mode:co-photo><speak:过时指令>"),
            dict(type="response.done", response_id="old"),
            text("new", "0.7,ms=0><rotate:to,value=20,ms=0>"),
            dict(type="response.done", response_id="new"),
            dict(type="session.closed"),
        ])

        async def receive():
            return json.dumps(next(incoming), ensure_ascii=False)

        canvas = MagicMock()
        canvas.apply_command.return_value = None
        selection = client.ModeSelection()
        log = Log()
        with contextlib.redirect_stdout(io.StringIO()):
            await client.receive_realtime_outputs(
                SimpleNamespace(recv=receive), threading.Event(), canvas, client.SpeechQueue(),
                verbose=False, event_log=log, mode_selection=selection,
            )
        applied = [call.args[0] for call in canvas.apply_command.call_args_list]
        self.assertEqual([command.kind for command in applied], ["move", "rotate"])
        self.assertEqual(applied[0].params["x"], .7)
        self.assertEqual(selection.mode, "guidance")
        self.assertEqual([r["text"] for r in log.rows if r["event"] == "speak"], ["现在站好"])
        self.assertEqual(sum(r["event"] == "parser.stale_output_ignored" for r in log.rows), 2)


if __name__ == "__main__":
    unittest.main()
