"""Regression coverage for mixed native speech and streamed tag commands."""
import asyncio
import contextlib
import io
import json
import threading
import unittest

from command_protocol import StreamingCommandParser
import realtime_av_test as client


class OutputParserTests(unittest.TestCase):
    def parser(self, **kwargs):
        return StreamingCommandParser(allow_plain_speech=True, **kwargs)

    def test_strict_parser_still_ignores_untagged_text(self):
        self.assertEqual(StreamingCommandParser().feed('r', '请向你自己的左边挪。'), [])

    def test_native_speech_is_available_on_each_fragment(self):
        parser = self.parser()
        first = parser.feed('r', '请向你自己的')
        self.assertEqual(first[0].params['text'], '请向你自己的')
        second = parser.feed('r', '左边挪一点。')
        self.assertEqual(second[0].params['text'], '左边挪一点。')
        self.assertEqual(parser.plain_speech_count, 2)

    def test_mixed_text_and_split_tags_keep_order_without_speaking_parameters(self):
        parser = self.parser()
        commands = parser.feed('r', '先保持。<mo')
        self.assertEqual([c.params['text'] for c in commands], ['先保持。'])
        commands += parser.feed('r', 've:to,x=0.2,ms=0><speak:好的。>再调整。')
        self.assertEqual([c.kind for c in commands], ['speak', 'move', 'speak', 'speak'])
        self.assertEqual(commands[1].params['x'], 0.2)
        self.assertEqual([c.params['text'] for c in commands if c.kind == 'speak'],
                         ['先保持。', '好的。', '再调整。'])

    def test_unknown_and_invalid_commands_are_not_spoken_or_executed(self):
        commands = self.parser().feed('r', '<unknown:secret><move:to,x=nan>继续。')
        self.assertEqual([(c.kind, c.params) for c in commands], [('speak', {'text': '继续。'})])

    def test_unknown_tag_can_span_fragments_without_leaking_body(self):
        parser = self.parser()
        self.assertEqual(parser.feed('r', '<unk'), [])
        self.assertEqual(parser.feed('r', 'nown:secret'), [])
        commands = parser.feed('r', '>完成。')
        self.assertEqual([c.params['text'] for c in commands], ['完成。'])

    def test_broken_unknown_prefix_does_not_swallow_later_valid_tag(self):
        commands = self.parser().feed('r', '提示。<unknown:secret<speak:继续。>')
        self.assertEqual([c.params['text'] for c in commands], ['提示。', '继续。'])

    def test_oversized_tag_discards_its_tail_until_recovery(self):
        parser = self.parser(max_buffer=32)
        self.assertEqual(parser.feed('r', '<move:to,' + 'x' * 40), [])
        self.assertEqual(parser.feed('r', 'x=0.9,ms=300'), [])
        commands = parser.feed('r', '><speak:继续。>')
        self.assertEqual([(c.kind, c.params) for c in commands], [('speak', {'text': '继续。'})])

    def test_new_response_and_flush_discard_unfinished_tags(self):
        parser = self.parser()
        self.assertEqual(parser.feed('r1', '<move:to,x=0.'), [])
        self.assertEqual(parser.feed('r2', '你好。')[0].params['text'], '你好。')
        self.assertEqual(parser.feed('r2', '<unknown:secret'), [])
        parser.flush('r2')
        self.assertEqual(parser.feed('r2', '继续。')[0].params['text'], '继续。')

    def test_all_legacy_commands_can_share_one_line(self):
        text = ('<speak:好。><move:to,x=0.35,y=0.95,ms=400>'
                '<move:by,dx=-0.10,dy=0,ms=300><scale:to,value=0.8,ms=400>'
                '<scale:by,factor=1.1,ms=300><tachie:smile>'
                '<rotate:to,value=10,ms=300><rotate:by,value=-5,ms=300><blank>')
        parser = self.parser()
        commands = parser.feed('r', text)
        self.assertEqual([c.kind for c in commands],
                         ['speak', 'move', 'move', 'scale', 'scale', 'tachie', 'rotate', 'rotate', 'blank'])
        self.assertEqual(parser.plain_speech_count, 0)

    def test_explicit_speech_is_not_duplicated_as_plain_text(self):
        parser = self.parser()
        commands = parser.feed('r', ' \n<speak:保持。>\n')
        self.assertEqual([c.params['text'] for c in commands], ['保持。'])
        self.assertEqual(parser.plain_speech_count, 0)


class EventLog:
    def __init__(self):
        self.rows = []
    def record(self, event, **fields):
        self.rows.append({'event': event, **fields})
    def record_message(self, event, message):
        self.record(event, message=message)


class RecordingCanvas:
    def __init__(self):
        self.commands = []
    def apply_command(self, command):
        self.commands.append(command)
        return client.SpriteState('normal', 0.2, 0.95, 1.0, 0.0)


class Socket:
    def __init__(self, events, before_second=None):
        self.events = iter(events)
        self.count = 0
        self.before_second = before_second
    async def recv(self):
        if self.count == 1 and self.before_second:
            self.before_second()
        self.count += 1
        return json.dumps(next(self.events), ensure_ascii=False)


class ReceiverAdaptationTests(unittest.TestCase):
    def test_native_text_dispatches_before_next_fragment_or_turn_end(self):
        log = EventLog()
        canvas = RecordingCanvas()

        def check_incremental_dispatch():
            self.assertEqual([r['text'] for r in log.rows if r['event'] == 'speak'], ['请向你自己的'])

        socket = Socket([
            {'type': 'response.output.delta', 'kind': 'text', 'text': '请向你自己的', 'response_id': 'r'},
            {'type': 'response.output.delta', 'kind': 'text', 'text': '左边挪。<speak:保持。>', 'response_id': 'r'},
            {'type': 'session.closed', 'reason': 'test'},
        ], before_second=check_incremental_dispatch)
        with contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(client.receive_realtime_outputs(socket, threading.Event(), canvas,
                        client.SpeechQueue(), verbose=False, event_log=log))
        self.assertEqual([r['text'] for r in log.rows if r['event'] == 'speak'],
                         ['请向你自己的', '左边挪。', '保持。'])
        self.assertEqual(canvas.commands, [])

    def test_actions_and_speech_dispatch_without_a_permission_filter(self):
        log = EventLog()
        canvas = RecordingCanvas()
        socket = Socket([
            {'type': 'response.output.delta', 'kind': 'text',
             'text': '<move:to,x=0.2><tachie:smile><speak:保持。>', 'response_id': 'r'},
            {'type': 'session.closed', 'reason': 'test'},
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(client.receive_realtime_outputs(socket, threading.Event(), canvas,
                        client.SpeechQueue(), verbose=False, event_log=log))
        self.assertEqual([c.kind for c in canvas.commands], ['move', 'tachie'])
        self.assertEqual(len([r for r in log.rows if r['event'] == 'command.blocked']), 0)
        self.assertEqual([r['text'] for r in log.rows if r['event'] == 'speak'], ['保持。'])


if __name__ == '__main__':
    unittest.main()
