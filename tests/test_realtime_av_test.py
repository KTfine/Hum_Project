import importlib
import base64
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np


def require_function(test_case, module, name):
    try:
        return getattr(module, name)
    except AttributeError:
        test_case.fail(f"{name} is missing")


class UrlNormalizationTests(unittest.TestCase):
    def test_https_base_url_becomes_video_websocket_url(self):
        try:
            module = importlib.import_module("realtime_av_test")
        except ModuleNotFoundError:
            self.fail("realtime_av_test module is missing")

        self.assertEqual(
            module.normalize_video_ws_url("https://localhost:8006"),
            "wss://localhost:8006/v1/realtime?mode=video",
        )

    def test_camera_is_enabled_by_default_and_can_be_disabled(self):
        module = importlib.import_module("realtime_av_test")

        defaults = module.parse_args([])
        disabled = module.parse_args(["--no-camera", "--camera-device", "2"])

        self.assertFalse(defaults.no_camera)
        self.assertEqual(defaults.camera_device, 0)
        self.assertTrue(disabled.no_camera)
        self.assertEqual(disabled.camera_device, 2)


class ProtocolPayloadTests(unittest.TestCase):
    def test_session_init_requests_streaming_audio_video_without_slicing(self):
        module = importlib.import_module("realtime_av_test")
        build_session_init = require_function(self, module, "build_session_init")

        message = build_session_init("持续观察并描述。", use_tts=True)

        self.assertEqual(message["type"], "session.init")
        self.assertEqual(message["payload"]["system_prompt"], "持续观察并描述。")
        self.assertEqual(message["payload"]["max_slice_nums"], 1)
        self.assertTrue(message["payload"]["use_tts"])
        self.assertEqual(message["payload"]["config"]["length_penalty"], 1.0)

    def test_session_init_can_disable_tts_for_text_only_control(self):
        module = importlib.import_module("realtime_av_test")

        message = module.build_session_init("control the sprite", use_tts=False)

        self.assertFalse(message["payload"]["use_tts"])
        self.assertFalse(message["payload"]["config"]["generate_audio"])
        self.assertEqual(
            message["payload"]["config"]["max_new_speak_tokens_per_chunk"], 96
        )
        self.assertEqual(message["payload"]["config"]["temperature"], 0.2)

    def test_session_init_enables_audio_in_both_legacy_and_duplex_config(self):
        module = importlib.import_module("realtime_av_test")

        message = module.build_session_init("speak", use_tts=True)

        self.assertTrue(message["payload"]["use_tts"])
        self.assertTrue(message["payload"]["config"]["generate_audio"])

    def test_video_input_contains_one_second_audio_and_raw_jpeg_base64(self):
        module = importlib.import_module("realtime_av_test")
        audio = b"\x00" * (16_000 * 4)
        jpeg = b"\xff\xd8frame\xff\xd9"

        build_video_input = require_function(self, module, "build_video_input")
        message = build_video_input(7, audio, jpeg)

        self.assertEqual(message["type"], "input.append")
        self.assertEqual(message["input"]["input_id"], "chunk-000007")
        self.assertEqual(
            message["input"]["audio"], base64.b64encode(audio).decode("ascii")
        )
        self.assertEqual(
            message["input"]["video_frames"],
            [base64.b64encode(jpeg).decode("ascii")],
        )
        self.assertFalse(message["input"]["force_listen"])
        self.assertEqual(message["input"]["max_slice_nums"], 1)

    def test_video_input_rejects_audio_with_wrong_duration(self):
        module = importlib.import_module("realtime_av_test")
        build_video_input = require_function(self, module, "build_video_input")

        with self.assertRaisesRegex(ValueError, "64000"):
            build_video_input(1, b"too short", b"jpeg")


class AudioInputBufferTests(unittest.TestCase):
    def test_underflow_is_padded_with_float32_silence(self):
        module = importlib.import_module("realtime_av_test")
        buffer_type = require_function(self, module, "AudioInputBuffer")
        buffer = buffer_type(chunk_bytes=8)
        buffer.push(b"abcdef")

        self.assertEqual(buffer.pop_chunk(), b"abcdef\x00\x00")

    def test_overflow_drops_old_audio_instead_of_building_latency(self):
        module = importlib.import_module("realtime_av_test")
        buffer_type = require_function(self, module, "AudioInputBuffer")
        buffer = buffer_type(chunk_bytes=8)
        buffer.push(b"123456")
        buffer.push(b"7890")

        self.assertEqual(buffer.pop_chunk(), b"34567890")


class OutputEventTests(unittest.TestCase):
    def test_streaming_text_delta_is_preserved(self):
        module = importlib.import_module("realtime_av_test")
        decode_output_event = require_function(self, module, "decode_output_event")

        decoded = decode_output_event(
            {"type": "response.output.delta", "kind": "text", "text": "有人挥手"}
        )

        self.assertEqual(decoded, ("text", "有人挥手"))

    def test_streaming_audio_delta_is_base64_decoded(self):
        module = importlib.import_module("realtime_av_test")
        decode_output_event = require_function(self, module, "decode_output_event")
        raw_audio = b"\x00\x00\x80?" * 4

        decoded = decode_output_event(
            {
                "type": "response.output.delta",
                "kind": "audio",
                "audio": base64.b64encode(raw_audio).decode("ascii"),
            }
        )

        self.assertEqual(decoded, ("audio", raw_audio))

    def test_gateway_error_becomes_an_exception_with_code_and_message(self):
        module = importlib.import_module("realtime_av_test")
        decode_output_event = require_function(self, module, "decode_output_event")
        error_type = require_function(self, module, "RealtimeServiceError")

        with self.assertRaisesRegex(error_type, "queue_full.*Queue full"):
            decode_output_event(
                {
                    "type": "error",
                    "error": {"code": "queue_full", "message": "Queue full"},
                }
            )


class SpriteControllerTests(unittest.TestCase):
    def test_move_and_scale_commands_animate_on_independent_lanes(self):
        from command_protocol import Command

        module = importlib.import_module("realtime_av_test")
        controller = module.SpriteController(
            {"normal"}, module.SpriteState("normal", 0.5, 0.9, 1.0, 0.0)
        )
        controller.apply_command(
            Command("move", {"mode": "to", "x": 0.8, "ms": 1000}), now=10.0
        )
        controller.apply_command(
            Command("scale", {"mode": "to", "value": 2.0, "ms": 1000}),
            now=10.5,
        )

        state = controller.state_at(11.0)

        self.assertAlmostEqual(state.x, 0.8)
        self.assertAlmostEqual(state.scale, 1.5)

    def test_relative_moves_accumulate_from_latest_target(self):
        from command_protocol import Command

        module = importlib.import_module("realtime_av_test")
        controller = module.SpriteController(
            {"normal"}, module.SpriteState("normal", 0.5, 0.9, 1.0, 0.0)
        )
        controller.apply_command(
            Command("move", {"mode": "by", "dx": 0.1, "ms": 1000}), now=1.0
        )
        target = controller.apply_command(
            Command("move", {"mode": "by", "dx": 0.1, "ms": 1000}), now=1.2
        )

        self.assertAlmostEqual(target.x, 0.7)
        self.assertAlmostEqual(controller.state_at(2.2).x, 0.7)

    def test_tachie_command_preserves_all_geometry(self):
        from command_protocol import Command

        module = importlib.import_module("realtime_av_test")
        controller = module.SpriteController(
            {"normal", "smile"},
            module.SpriteState("normal", 0.3, 0.8, 1.4, -12.0),
        )

        controller.apply_command(Command("tachie", {"sprite_id": "smile"}), now=1.0)

        self.assertEqual(
            controller.state_at(1.0),
            module.SpriteState("smile", 0.3, 0.8, 1.4, -12.0),
        )

    def test_zero_offset_hold_freezes_current_position_without_finishing_move(self):
        from command_protocol import Command

        module = importlib.import_module("realtime_av_test")
        controller = module.SpriteController(
            {"normal"}, module.SpriteState("normal", 0.2, 0.4, 1.0, 0.0)
        )
        controller.apply_command(
            Command("move", {"mode": "to", "x": 0.8, "y": 0.8, "ms": 1000}), now=10.0
        )
        target = controller.apply_command(
            Command("move", {"mode": "by", "dx": 0, "dy": 0, "ms": 0}), now=10.5
        )
        self.assertAlmostEqual(target.x, 0.5)
        self.assertAlmostEqual(target.y, 0.6)
        self.assertEqual(controller.state_at(12.0), target)

    def test_hold_on_one_axis_preserves_other_animation_lanes(self):
        from command_protocol import Command

        module = importlib.import_module("realtime_av_test")
        controller = module.SpriteController(
            {"normal"}, module.SpriteState("normal", 0.2, 0.4, 1.0, 0.0)
        )
        controller.apply_command(
            Command("move", {"mode": "to", "x": 0.8, "y": 0.8, "ms": 1000}), now=10.0
        )
        controller.apply_command(
            Command("scale", {"mode": "to", "value": 2.0, "ms": 1000}), now=10.0
        )
        controller.apply_command(
            Command("move", {"mode": "by", "dx": 0, "ms": 0}), now=10.5
        )
        state = controller.state_at(11.0)
        self.assertAlmostEqual(state.x, 0.5)
        self.assertAlmostEqual(state.y, 0.8)
        self.assertAlmostEqual(state.scale, 2.0)

    def test_blank_command_does_not_change_state(self):
        from command_protocol import Command

        module = importlib.import_module("realtime_av_test")
        initial = module.SpriteState("normal", 0.3, 0.8, 1.4, -12.0)
        controller = module.SpriteController({"normal"}, initial)

        result = controller.apply_command(Command("blank", {}), now=1.0)

        self.assertIsNone(result)
        self.assertEqual(controller.state_at(1.0), initial)


class SpeechQueueTests(unittest.TestCase):
    def test_speech_is_returned_in_fifo_order(self):
        module = importlib.import_module("realtime_av_test")
        queue = module.SpeechQueue()
        queue.enqueue("第一句")
        queue.enqueue("第二句")

        self.assertEqual(queue.pop_next(), "第一句")
        self.assertEqual(queue.pop_next(), "第二句")
        self.assertIsNone(queue.pop_next())


class CommandDispatchTests(unittest.TestCase):
    def test_complete_streamed_command_is_dispatched_before_listen(self):
        from command_protocol import Command

        module = importlib.import_module("realtime_av_test")

        class RecordingCanvas:
            def __init__(self):
                self.commands = []

            def apply_command(self, command):
                self.commands.append(command)
                return module.SpriteState("normal", 0.2, 0.95, 1.0, 0.0)

        canvas = RecordingCanvas()
        stop_event = __import__("threading").Event()
        websocket = FakeWebSocket(
            [
                {
                    "type": "response.output.delta",
                    "kind": "text",
                    "text": "<move:to,x=0.2>",
                    "response_id": "r1",
                },
                {"type": "session.closed", "reason": "test"},
            ]
        )

        with contextlib.redirect_stdout(io.StringIO()):
            __import__("asyncio").run(
                module.receive_realtime_outputs(
                    websocket,
                    stop_event,
                    canvas,
                    module.SpeechQueue(),
                    verbose=False,
                )
            )

        self.assertEqual(
            canvas.commands,
            [Command("move", {"mode": "to", "x": 0.2, "ms": 350})],
        )

    def test_malformed_stream_is_silent_and_later_command_still_dispatches(self):
        module = importlib.import_module("realtime_av_test")

        class RecordingCanvas:
            def __init__(self):
                self.commands = []

            def apply_command(self, command):
                self.commands.append(command)
                return None

        canvas = RecordingCanvas()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            module.dispatch_model_commands(
                module.StreamingCommandParser().feed(
                    "r1", "<move:to,x=>garbage<tachie:normal>"
                ),
                canvas,
                module.SpeechQueue(),
                verbose=False,
            )

        self.assertEqual([command.kind for command in canvas.commands], ["tachie"])
        self.assertEqual(stderr.getvalue(), "")

    def test_listen_event_is_a_quiet_no_op_without_verbose_mode(self):
        module = importlib.import_module("realtime_av_test")

        class RecordingCanvas:
            def apply_command(self, command):
                self.fail("no command expected")

        output = io.StringIO()
        stop_event = __import__("threading").Event()
        websocket = FakeWebSocket(
            [
                {"type": "response.output.delta", "kind": "listen"},
                {"type": "session.closed", "reason": "test"},
            ]
        )
        with contextlib.redirect_stdout(output):
            __import__("asyncio").run(
                module.receive_realtime_outputs(
                    websocket,
                    stop_event,
                    RecordingCanvas(),
                    module.SpeechQueue(),
                    verbose=False,
                )
            )

        self.assertNotIn("listening", output.getvalue())


class FrontendLoggingTests(unittest.TestCase):
    def test_logger_persists_gateway_events_without_audio_base64(self):
        module = importlib.import_module("realtime_av_test")
        logger_type = require_function(self, module, "FrontendEventLogger")
        raw_audio = b"\x00\x01\x02\x03" * 3

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frontend.jsonl"
            logger = logger_type(path)
            logger.record_message(
                "gateway.receive",
                {
                    "type": "response.output.delta",
                    "kind": "audio",
                    "audio": base64.b64encode(raw_audio).decode("ascii"),
                    "response_id": "resp-7",
                },
            )
            logger.close()
            record = json.loads(path.read_text(encoding="utf-8").strip())

        self.assertEqual(record["event"], "gateway.receive")
        self.assertEqual(record["message"]["audio_bytes"], len(raw_audio))
        self.assertNotIn("audio", record["message"])
        self.assertEqual(record["message"]["response_id"], "resp-7")


class CanvasCompositionTests(unittest.TestCase):
    def test_rgba_sprite_is_alpha_composited_and_clipped_on_white_canvas(self):
        module = importlib.import_module("realtime_av_test")
        composite = require_function(self, module, "alpha_composite_at")
        canvas = np.full((3, 3, 3), 255, dtype=np.uint8)
        sprite = np.array(
            [
                [[0, 0, 0, 255], [0, 0, 0, 128]],
                [[0, 0, 0, 0], [0, 0, 0, 255]],
            ],
            dtype=np.uint8,
        )

        composite(canvas, sprite, left=2, top=1)

        self.assertEqual(canvas[1, 2].tolist(), [0, 0, 0])
        self.assertEqual(canvas[2, 2].tolist(), [255, 255, 255])

    def test_model_frame_keeps_camera_and_adds_aspect_preserving_inset(self):
        module = importlib.import_module("realtime_av_test")
        camera = np.zeros((100, 200, 3), dtype=np.uint8)
        camera_before = camera.copy()
        character = np.full((50, 100, 3), 255, dtype=np.uint8)
        character[:, :20] = (10, 20, 30)

        result = module.compose_model_frame(camera, character, inset_ratio=0.25)

        self.assertEqual(result.shape, camera.shape)
        self.assertTrue(np.array_equal(camera, camera_before))
        changed_y, changed_x = np.where(np.any(result != 0, axis=2))
        self.assertEqual(changed_x.max() - changed_x.min() + 1, 50)
        self.assertEqual(changed_y.max() - changed_y.min() + 1, 25)
        self.assertGreater(changed_x.min(), 100)

    def test_model_frame_falls_back_to_character_when_camera_is_unavailable(self):
        module = importlib.import_module("realtime_av_test")
        character = np.full((30, 40, 3), 127, dtype=np.uint8)

        result = module.compose_model_frame(None, character)

        self.assertTrue(np.array_equal(result, character))
        self.assertIsNot(result, character)


class FakeWebSocket:
    def __init__(self, incoming):
        self.incoming = iter(incoming)
        self.sent = []

    async def recv(self):
        return json.dumps(next(self.incoming), ensure_ascii=False)

    async def send(self, payload):
        self.sent.append(json.loads(payload))


class SessionHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_queue_done_then_initializes_session(self):
        module = importlib.import_module("realtime_av_test")
        open_session = require_function(self, module, "open_realtime_session")
        init = {"type": "session.init", "payload": {"use_tts": False}}
        websocket = FakeWebSocket(
            [
                {"type": "session.queued", "position": 1},
                {"type": "session.queue_done"},
                {"type": "session.created", "session_id": "sess_test"},
            ]
        )

        created = await open_session(websocket, init)

        self.assertEqual(created["session_id"], "sess_test")
        self.assertEqual(websocket.sent, [init])

    async def test_initial_connection_retries_after_transient_os_error(self):
        module = importlib.import_module("realtime_av_test")
        open_with_retry = require_function(
            self, module, "connect_and_open_session_with_retry"
        )
        websocket = FakeWebSocket(
            [
                {"type": "session.queue_done"},
                {"type": "session.created", "session_id": "sess_retry"},
            ]
        )
        calls = 0

        async def connect(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError(64, "network name no longer available")
            return websocket

        async def no_sleep(_delay):
            return None

        connected, created = await open_with_retry(
            connect,
            "wss://localhost:8006/v1/realtime?mode=video",
            None,
            {"type": "session.init", "payload": {}},
            connect_timeout=1,
            session_timeout=1,
            attempts=3,
            sleep=no_sleep,
        )

        self.assertIs(connected, websocket)
        self.assertEqual(created["session_id"], "sess_retry")
        self.assertEqual(calls, 2)


class RealtimeInputSenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_tick_sends_camera_with_character_inset(self):
        import cv2
        import threading

        module = importlib.import_module("realtime_av_test")
        stop_event = threading.Event()
        class Camera:
            def latest_frame(self):
                return np.zeros((180, 320, 3), dtype=np.uint8)

        class WebSocket:
            def __init__(self):
                self.sent = []

            async def send(self, payload):
                self.sent.append(json.loads(payload))
                if len(self.sent) == 2:
                    stop_event.set()

        websocket = WebSocket()
        with tempfile.TemporaryDirectory() as directory:
            sprite_dir = Path(directory)
            sprite = np.zeros((50, 100, 4), dtype=np.uint8)
            sprite[:, :, :3] = (20, 80, 180)
            sprite[:, :, 3] = 255
            self.assertTrue(cv2.imwrite(str(sprite_dir / "normal.png"), sprite))
            canvas = module.CanvasSource(
                sprite_dir,
                "normal",
                320,
                180,
                90,
                stop_event,
                preview=False,
            )
            canvas.start()
            try:
                await module.send_realtime_inputs(
                    websocket,
                    canvas,
                    Camera(),
                    module.AudioInputBuffer(),
                    stop_event,
                )
            finally:
                canvas.close()

        self.assertEqual(len(websocket.sent), 2)
        self.assertTrue(all("video_frames" in item["input"] for item in websocket.sent))
        jpeg = base64.b64decode(websocket.sent[1]["input"]["video_frames"][0], validate=True)
        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        # The client-owned status badge occupies the top-left rows.
        self.assertLess(float(frame[30:90, :160].mean()), 10.0)
        self.assertGreater(float(frame[:60, 240:].mean()), 10.0)


if __name__ == "__main__":
    unittest.main()
