import unittest


class StreamingCommandPromptTests(unittest.TestCase):
    def render_prompt(self):
        import prompt

        return prompt.STREAMING_COMMAND_PROMPT.format(
            character_name="小航",
            character_persona="活泼但不打扰用户",
            response_language="中文",
            sprite_catalog="normal, smile, thinking",
            current_character_state=(
                "sprite_id=normal,x=0.5,y=0.95,scale=1.0,rotation=0"
            ),
            recent_context="用户希望拍一张严肃的证件照。",
            extra_instructions="保持简短。",
        )

    def test_formats_runtime_context_and_documents_every_command(self):
        rendered = self.render_prompt()

        self.assertIn("小航", rendered)
        self.assertIn("normal, smile, thinking", rendered)
        self.assertIn("<speak:", rendered)
        self.assertIn("<move:to,", rendered)
        self.assertIn("<move:by,", rendered)
        self.assertIn("<scale:to,", rendered)
        self.assertIn("<scale:by,", rendered)
        self.assertIn("<tachie:", rendered)
        self.assertIn("<rotate:to,", rendered)
        self.assertIn("<blank>", rendered)

    def test_photography_guidance_is_derived_from_user_instruction(self):
        rendered = self.render_prompt()

        self.assertIn("只根据用户当前的拍摄目标和指示", rendered)
        self.assertIn("主画面是真人摄像头", rendered)
        self.assertIn("右上角白底小窗", rendered)
        self.assertNotIn("下巴", rendered)
        self.assertNotIn("侧脸", rendered)
        self.assertNotIn("微笑更好", rendered)

    def test_requires_tag_only_streaming_output_and_no_json(self):
        rendered = self.render_prompt()

        self.assertIn("只能输出指令码", rendered)
        self.assertIn("完整的 `>`", rendered)
        self.assertNotIn("JSON Lines", rendered)
        self.assertNotIn('{"type"', rendered)
        self.assertNotIn("{character_name}", rendered)


if __name__ == "__main__":
    unittest.main()
