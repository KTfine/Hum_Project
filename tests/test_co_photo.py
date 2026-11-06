"""Co-photo entry, streaming permissions and actual camera compositing."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest

import cv2
import numpy as np

from command_protocol import StreamingCommandParser
import realtime_av_test as client


class Camera:
    def __init__(self, frame):
        self.frame = frame

    def latest_frame(self):
        return None if self.frame is None else self.frame.copy()


class EventLog:
    def __init__(self):
        self.rows = []

    def record(self, event, **fields):
        self.rows.append({'event': event, **fields})

    def record_message(self, event, message):
        self.record(event, message=message)


class CoPhotoTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        sprite = np.full((10, 10, 4), (100, 200, 250, 128), dtype=np.uint8)
        sprite_dir = Path(self.directory.name)
        self.assertTrue(cv2.imwrite(str(sprite_dir / 'normal.png'), sprite))
        self.frame = np.full((100, 200, 3), (10, 20, 30), dtype=np.uint8)
        self.stop = threading.Event()
        self.canvas = client.CanvasSource(sprite_dir, 'normal', 200, 100, 95, self.stop, preview=False)
        self.canvas.set_camera(Camera(self.frame))
        self.canvas.start()
        self.log = EventLog()

    def tearDown(self):
        self.canvas.close()
        self.directory.cleanup()

    def dispatch(self, text):
        commands = StreamingCommandParser(allow_plain_speech=True).feed('test', text)
        with contextlib.redirect_stdout(io.StringIO()):
            client.dispatch_model_commands(commands, self.canvas, client.SpeechQueue(), self.log,
                                           co_photo=self.canvas.co_photo)

    def test_default_inactive_blocks_all_avatar_actions_and_keeps_speech(self):
        before = self.canvas.controller.state_at()
        self.dispatch('<move:to,x=0.2><scale:to,value=0.5><rotate:to,value=10><tachie:normal><speak:保持。>')
        self.assertFalse(self.canvas.co_photo.active)
        self.assertEqual(self.canvas.controller.state_at(), before)
        self.assertEqual(sum(r['event'] == 'command.blocked' for r in self.log.rows), 4)
        self.assertEqual([r['text'] for r in self.log.rows if r['event'] == 'speak'], ['保持。'])

    def test_entry_then_moves_on_one_line_obey_command_order(self):
        self.dispatch('<move:to,x=0.9,ms=0><photo:enter><move:to,x=0.35,y=0.9,ms=0><move:by,dx=-0.1,ms=0>')
        self.assertTrue(self.canvas.co_photo.active)
        self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.25)
        self.assertEqual(sum(r['event'] == 'command.blocked' for r in self.log.rows), 1)
        self.assertEqual(sum(r['event'] == 'co_photo.activated' for r in self.log.rows), 1)

    def test_entry_enables_only_move_and_preserves_photography_speech(self):
        self.dispatch('<photo:enter><move:to,x=0.3,ms=0><scale:to,value=0.5><rotate:to,value=15><tachie:normal><speak:请保持。>')
        state = self.canvas.controller.state_at()
        self.assertAlmostEqual(state.x, 0.3)
        self.assertEqual((state.scale, state.rotation), (1.0, 0.0))
        self.assertEqual(sum(r['event'] == 'command.blocked' for r in self.log.rows), 3)
        self.assertEqual([r['text'] for r in self.log.rows if r['event'] == 'speak'],
                         [client.CO_PHOTO_GOAL_QUESTION, '请保持。'])

    def test_plain_acknowledgement_or_spoken_invitation_cannot_activate(self):
        self.dispatch('我们来合照吧，我已经进来了。<speak:我们一起来拍照。>')
        self.assertFalse(self.canvas.co_photo.active)

    def test_unknown_entry_values_and_incomplete_tags_cannot_activate(self):
        self.dispatch('<photo:exit><photo:enter,x=0.3><photo:ent')
        self.assertFalse(self.canvas.co_photo.active)

    def test_entry_requires_a_fresh_camera_frame(self):
        self.canvas.set_camera(Camera(None))
        self.dispatch('<photo:enter><move:to,x=0.2,ms=0>')
        self.assertFalse(self.canvas.co_photo.active)
        self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.5)
        self.assertEqual(self.log.rows[0]['reason'], 'co_photo_camera_unavailable')

    def test_no_camera_mode_cannot_enter(self):
        self.canvas.set_camera(None)
        self.dispatch('<photo:enter>')
        self.assertFalse(self.canvas.co_photo.active)

    def test_repeated_entry_is_idempotent_and_does_not_reset_geometry(self):
        self.dispatch('<photo:enter><move:to,x=0.2,y=0.8,ms=0><photo:enter>')
        self.assertEqual(self.canvas.controller.state_at(), client.SpriteState('normal', 0.2, 0.8, 1.0, 0.0))
        self.assertEqual(sum(r['event'] == 'co_photo.activated' for r in self.log.rows), 1)
        self.assertEqual([r['text'] for r in self.log.rows if r['event'] == 'speak'],
                         [client.CO_PHOTO_GOAL_QUESTION])
        self.assertFalse(client.CoPhotoSession().active)

    def test_first_entry_always_asks_for_a_photo_goal_without_model_speech(self):
        self.dispatch('<photo:enter>')
        self.assertTrue(self.canvas.co_photo.active)
        self.assertEqual([r['text'] for r in self.log.rows if r['event'] == 'speak'],
                         [client.CO_PHOTO_GOAL_QUESTION])
        self.assertEqual(sum(r['event'] == 'co_photo.goal_requested' for r in self.log.rows), 1)

    def test_prompt_initial_state_comes_from_client_activation(self):
        args = client.parse_args([])
        self.assertIn('"co_photo_active": false', client.build_control_prompt(self.canvas, args))
        self.dispatch('<photo:enter>')
        self.assertIn('"co_photo_active": true', client.build_control_prompt(self.canvas, args))

    def test_action_diagnostic_is_explicit_and_requires_activation(self):
        args = client.parse_args([])
        with self.assertRaises(ValueError):
            client.build_control_prompt(self.canvas, args, action_only=True)
        self.dispatch('<photo:enter>')
        normal = client.build_control_prompt(self.canvas, args)
        diagnostic = client.build_control_prompt(self.canvas, args, action_only=True)
        self.assertIn('<speak:', normal)
        self.assertNotIn('<speak:', diagnostic)
        self.assertIn('"co_photo_active": true', diagnostic)

    def test_active_overlay_is_transparent_moves_and_does_not_mutate_camera(self):
        inactive = self.canvas.render_scene(self.frame)
        self.assertEqual(inactive[85, 50].tolist(), [10, 20, 30])
        self.dispatch('<photo:enter><move:to,x=0.25,y=0.9,ms=0>')
        active = self.canvas.render_scene(self.frame)
        alpha = 128 / 255
        expected = np.rint(np.array([100, 200, 250])*alpha + np.array([10, 20, 30])*(1-alpha)).astype(np.uint8)
        np.testing.assert_array_equal(active[85, 50], expected)
        np.testing.assert_array_equal(self.frame, np.full_like(self.frame, (10, 20, 30)))
        self.assertEqual(active[40, 180].tolist(), [10, 20, 30])
        self.dispatch('<move:to,x=0.75,ms=0>')
        moved = self.canvas.render_scene(self.frame)
        self.assertEqual(moved[85, 50].tolist(), [10, 20, 30])
        np.testing.assert_array_equal(moved[85, 150], expected)

    def test_streamed_entry_closes_before_next_fragment_and_move_executes_before_turn_end(self):
        canvas, log, stop = self.canvas, self.log, self.stop
        class Socket:
            def __init__(self):
                self.index = 0

            async def recv(self):
                if self.index == 1:
                    self_outer.assertFalse(canvas.co_photo.active)
                if self.index == 2:
                    self_outer.assertTrue(canvas.co_photo.active)
                    self_outer.assertAlmostEqual(canvas.controller.state_at().x, 0.3)
                events = [
                    {'type':'response.output.delta', 'kind':'text', 'text':'<photo:en', 'response_id':'r'},
                    {'type':'response.output.delta', 'kind':'text', 'text':'ter><move:to,x=0.3,ms=0>', 'response_id':'r'},
                    {'type':'session.closed', 'reason':'test'},
                ]
                event = events[self.index]
                self.index += 1
                return json.dumps(event)

        self_outer = self
        with contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(client.receive_realtime_outputs(Socket(), stop, canvas, client.SpeechQueue(),
                        verbose=False, event_log=log, co_photo=canvas.co_photo))


class ActionDiagnosticCliTests(unittest.TestCase):
    def test_action_only_live_test_requires_explicit_opt_in(self):
        self.assertFalse(client.parse_args([]).action_only_test)
        self.assertTrue(client.parse_args(['--action-only-test']).action_only_test)

    def test_action_only_live_test_rejects_missing_camera_and_prompt_override(self):
        for args in [
            ['--action-only-test', '--no-camera'],
            ['--action-only-test', '--prompt', 'custom'],
        ]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    client.parse_args(args)


if __name__ == '__main__':
    unittest.main()
