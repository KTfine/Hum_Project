import math
import unittest


class StreamingCommandParserTests(unittest.TestCase):
    def make_parser(self, **kwargs):
        from command_protocol import StreamingCommandParser

        return StreamingCommandParser(**kwargs)

    def test_split_command_emits_only_after_final_delimiter(self):
        parser = self.make_parser()

        self.assertEqual(parser.feed("r1", "<move:to,x=0."), [])
        commands = parser.feed("r1", "35,y=0.9,ms=400>")

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].kind, "move")
        self.assertEqual(
            commands[0].params,
            {"mode": "to", "x": 0.35, "y": 0.9, "ms": 400},
        )

    def test_multiple_commands_are_emitted_in_stream_order(self):
        parser = self.make_parser()

        commands = parser.feed(
            "r1", "noise<speak:向左一点。><tachie:smile><blank>trailing"
        )

        self.assertEqual([command.kind for command in commands], ["speak", "tachie", "blank"])
        self.assertEqual(commands[0].params, {"text": "向左一点。"})
        self.assertEqual(commands[1].params, {"sprite_id": "smile"})

    def test_last_bracket_in_a_run_closes_speak_and_earlier_brackets_are_content(self):
        parser = self.make_parser()

        commands = parser.feed("r1", "<speak: >>")

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].params, {"text": ">"})

    def test_doubled_speak_closer_recovers_when_brackets_cross_chunks(self):
        parser = self.make_parser()

        self.assertEqual(parser.feed("r1", "<speak: >"), [])
        commands = parser.feed("r1", ">")

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].params, {"text": ">"})

    def test_extra_closing_brackets_do_not_invalidate_structured_commands(self):
        parser = self.make_parser()

        commands = parser.feed(
            "r1", "<move:to,x=0.2>><scale:to,value=0.8>><tachie:smile>>"
        )

        self.assertEqual([command.kind for command in commands], ["move", "scale", "tachie"])

    def test_new_known_prefix_resynchronizes_after_unclosed_command(self):
        parser = self.make_parser()

        commands = parser.feed("r1", "<speak:坏掉了 <tachie:happy>")

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].kind, "tachie")
        self.assertEqual(commands[0].params, {"sprite_id": "happy"})

    def test_speak_can_recover_literal_command_like_text_after_empty_prefix(self):
        parser = self.make_parser()

        commands = parser.feed("r1", "<speak: <move:>")

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].kind, "speak")
        self.assertEqual(commands[0].params, {"text": "<move:"})

    def test_invalid_and_unknown_commands_are_silently_skipped(self):
        parser = self.make_parser()

        commands = parser.feed(
            "r1",
            "<unknown:x><move:to,x=nan><move:by,dx=inf><scale:to,value=>"
            "<move:to,x=0.2>",
        )

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].params, {"mode": "to", "x": 0.2, "ms": 350})

    def test_out_of_range_values_are_skipped_instead_of_clamped(self):
        parser = self.make_parser()

        commands = parser.feed(
            "r1", "<move:to,x=-1><scale:to,value=4><rotate:to,value=181><blank>"
        )

        self.assertEqual([command.kind for command in commands], ["blank"])

    def test_overlong_unclosed_candidate_is_discarded_and_parser_recovers(self):
        parser = self.make_parser(max_buffer=32)

        self.assertEqual(parser.feed("r1", "<speak:" + "x" * 40), [])
        commands = parser.feed("r1", "garbage<tachie:normal>")

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].params, {"sprite_id": "normal"})

    def test_response_change_discards_unfinished_previous_response(self):
        parser = self.make_parser()

        self.assertEqual(parser.feed("r1", "<speak:old"), [])
        commands = parser.feed("r2", "<speak:new>")

        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0].params, {"text": "new"})

    def test_flush_silently_discards_incomplete_input(self):
        parser = self.make_parser()
        parser.feed("r1", "<move:to,x=0.4")

        self.assertEqual(parser.flush("r1"), [])


if __name__ == "__main__":
    unittest.main()
