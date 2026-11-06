import unittest


class StreamingCommandPromptTests(unittest.TestCase):
    def render_prompt(self, template=None):
        import prompt

        return (template or prompt.STREAMING_COMMAND_PROMPT).format(
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

    def test_inactive_prompt_contains_context_and_only_inactive_commands(self):
        rendered = self.render_prompt()

        self.assertIn("小航", rendered)
        self.assertIn("用户希望拍一张严肃的证件照", rendered)
        self.assertIn("当前合照状态：OFF", rendered)
        import re
        self.assertEqual(set(re.findall(r'<([a-z]+)(?=[:>])', rendered)), {'speak', 'photo', 'blank'})

    def test_active_prompt_retains_guidance_and_only_enabled_actions(self):
        import prompt
        import re
        rendered = self.render_prompt(prompt.CO_PHOTO_COMMAND_PROMPT)
        self.assertIn("当前合照状态：ON", rendered)
        self.assertIn("真人姿势", rendered)
        self.assertIn("可见表情", rendered)
        self.assertIn("推荐", rendered)
        self.assertEqual(set(re.findall(r'<([a-z]+)(?=[:>])', rendered)), {'move', 'speak'})

    def test_photography_guidance_is_derived_from_user_instruction(self):
        rendered = self.render_prompt()

        self.assertIn("按用户目标", rendered)
        self.assertIn("主画面是真人", rendered)
        self.assertIn("右上角白底小窗", rendered)
        self.assertNotIn("下巴", rendered)
        self.assertNotIn("侧脸", rendered)
        self.assertNotIn("微笑更好", rendered)

    def test_requires_tag_only_streaming_output_and_no_json(self):
        rendered = self.render_prompt()

        self.assertIn("只能输出指令码", rendered)
        self.assertIn("标签完整闭合后立即输出", rendered)
        self.assertIn("单行连续输出", rendered)
        self.assertNotIn("JSON Lines", rendered)
        self.assertNotIn('{"type"', rendered)
        self.assertNotIn("{character_name}", rendered)


if __name__ == "__main__":
    unittest.main()
