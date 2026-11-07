"""Mode metadata must never gate the upstream sprite frontend."""
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


class Log:
    def __init__(self):
        self.rows = []
    def record(self, event, **fields):
        self.rows.append(dict(event=event, **fields))
    def record_message(self, event, message):
        self.record(event, message=message)


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        sprite = np.full((10, 10, 4), (100, 200, 250, 128), dtype=np.uint8)
        for name in ('normal', 'smile'):
            cv2.imwrite(str(Path(self.directory.name) / f'{name}.png'), sprite)
        self.stop = threading.Event()
        self.canvas = client.CanvasSource(Path(self.directory.name), 'normal', 200, 100, 95,
                                          self.stop, preview=False)
        self.canvas.start()
        self.selection = client.ModeSelection()
        self.log = Log()

    def tearDown(self):
        self.canvas.close()
        self.directory.cleanup()

    def dispatch(self, text):
        commands = StreamingCommandParser(allow_plain_speech=True).feed('r', text)
        with contextlib.redirect_stdout(io.StringIO()):
            client.dispatch_model_commands(commands, self.canvas, client.SpeechQueue(), self.log,
                                           mode_selection=self.selection)

    def test_all_actions_execute_in_both_modes(self):
        for mode in client.MODES:
            self.selection.select(mode)
            self.selection.mark_loaded(*self.selection.snapshot())
            self.dispatch('<move:to,x=0.2,ms=0><scale:to,value=0.5,ms=0>'
                          '<rotate:to,value=10,ms=0><tachie:smile><speak:保持。>')
            self.assertEqual(self.canvas.controller.state_at(),
                             client.SpriteState('smile', 0.2, 0.95, 0.5, 10.0))
        self.assertEqual(sum(r['event'] == 'command.applied' for r in self.log.rows), 8)
        self.assertFalse(any(r['event'] == 'command.blocked' for r in self.log.rows))

    def test_requested_mode_is_not_reported_as_loaded(self):
        self.assertIsNone(self.selection.co_photo_active)
        self.selection.mark_loaded(*self.selection.snapshot())
        self.dispatch('<mode:co-photo><move:by,dx=-0.1,ms=0>')
        self.assertFalse(self.selection.co_photo_active)
        self.assertEqual(self.selection.mode, 'co-photo')
        self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.4)
        self.selection.mark_loaded(*self.selection.snapshot())
        self.assertTrue(self.selection.co_photo_active)
        self.dispatch('<mode:guidance>')
        self.assertTrue(self.selection.co_photo_active)
        self.selection.mark_loaded(*self.selection.snapshot())
        self.assertFalse(self.selection.co_photo_active)

    def test_duplicate_requests_are_idempotent_and_stale_confirmation_is_rejected(self):
        self.dispatch('<mode:co-photo>')
        first = self.selection.snapshot()
        self.dispatch('<mode:co-photo>')
        self.assertEqual(self.selection.snapshot(), first)
        self.dispatch('<mode:guidance>')
        self.assertFalse(self.selection.mark_loaded(*first))
        self.assertIsNone(self.selection.co_photo_active)

    def test_plain_words_legacy_tags_and_invalid_commands_do_not_switch(self):
        self.dispatch('和我合照。恢复指导模式。<photo:enter><mode:invalid><mode:co-photo,x=1>'
                      '<move:to,x=nan><scale:to,value=9><tachie:missing><rotate:to,value=999>')
        self.assertEqual(self.selection.snapshot(), ('guidance', 0))
        self.assertEqual(self.canvas.controller.state_at(),
                         client.SpriteState('normal', 0.5, 0.95, 1.0, 0.0))

    def test_split_mode_and_action_tags_execute_before_turn_end(self):
        parser = StreamingCommandParser()
        self.assertEqual(parser.feed('r', '<mo'), [])
        self.assertEqual(parser.feed('r', 'de:co-photo'), [])
        commands = parser.feed('r', '><move:by,dx=-0.1,ms=0><speak:好。>')
        self.assertEqual([c.kind for c in commands], ['mode', 'move', 'speak'])
        with contextlib.redirect_stdout(io.StringIO()):
            client.dispatch_model_commands(commands, self.canvas, client.SpeechQueue(), self.log,
                                           mode_selection=self.selection)
        self.assertEqual(self.selection.mode, 'co-photo')
        self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.4)

    def test_co_photo_keeps_white_preview_and_camera_plus_inset(self):
        camera = np.full((100, 200, 3), (10, 20, 30), dtype=np.uint8)
        before = self.canvas.render_frame()
        self.canvas.configure_view(None, show_character=True)
        self.dispatch('<mode:co-photo>')
        np.testing.assert_array_equal(self.canvas.render_preview_frame(), before)
        self.assertEqual(before[0, 0].tolist(), [255, 255, 255])
        decoded = cv2.imdecode(np.frombuffer(self.canvas.latest_jpeg(camera), dtype=np.uint8),
                               cv2.IMREAD_COLOR)
        np.testing.assert_allclose(decoded[0, 0], camera[0, 0], atol=4)
        # Sprite stays in the upstream inset rather than being overlaid on the person.
        np.testing.assert_allclose(decoded[85, 100], camera[85, 100], atol=4)
        np.testing.assert_array_equal(camera, np.full_like(camera, (10, 20, 30)))

    def test_guidance_preview_and_model_frame_contain_only_the_camera(self):
        camera = np.full((100, 200, 3), (10, 20, 30), dtype=np.uint8)
        source = type('Camera', (), {'latest_frame': lambda _: camera})()
        self.canvas.configure_view(source, show_character=False)
        preview = self.canvas.render_preview_frame()
        np.testing.assert_array_equal(preview, camera)
        self.assertIsNot(preview, camera)
        jpeg = self.canvas.latest_jpeg(camera, include_character=False)
        ok, expected = cv2.imencode('.jpg', camera, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        self.assertTrue(ok)
        self.assertEqual(jpeg, expected.tobytes())
        # A valid model action remains executable while its character is hidden.
        self.dispatch('<move:to,x=0.2,ms=0><tachie:smile>')
        np.testing.assert_array_equal(self.canvas.render_preview_frame(), camera)
        self.assertEqual(self.canvas.controller.state_at().sprite_id, 'smile')
        self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.2)
        self.canvas.configure_view(source, show_character=True)
        self.assertFalse(np.array_equal(self.canvas.render_preview_frame(), camera))
        self.assertAlmostEqual(self.canvas.controller.state_at().x, 0.2)

    def test_guidance_without_camera_does_not_fall_back_to_a_character(self):
        self.canvas.configure_view(None, show_character=False)
        np.testing.assert_array_equal(self.canvas.render_preview_frame(),
                                      np.full((100, 200, 3), 255, dtype=np.uint8))
        jpeg = self.canvas.latest_jpeg(None, include_character=False)
        decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertTrue(np.all(decoded == 255))

    def test_removed_diagnostic_and_manual_mode_cli_are_rejected(self):
        for args in [['--action-only-test'], ['--mode', 'co-photo']]:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    client.parse_args(args)


if __name__ == '__main__':
    unittest.main()
