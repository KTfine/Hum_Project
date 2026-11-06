"""Run the actual patched methods with a fake decoder; no GPU/model load needed."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest


UPSTREAM = Path(os.environ.get('MINICPM_UPSTREAM_DIR', Path(__file__).resolve().parents[1] / 'upstream'))


def method_from_file(relative, class_name, method_name, namespace):
    tree = ast.parse((UPSTREAM / relative).read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    method.decorator_list = []
    method.returns = None
    for arg in [*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs]:
        arg.annotation = None
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    exec(compile(module, str(UPSTREAM / relative), 'exec'), namespace)
    return namespace[method_name]


class DuplexSessionOptionsTests(unittest.TestCase):
    def test_session_audio_and_budget_reach_decoder_and_can_be_restored(self):
        decoder = SimpleNamespace(generate_audio=True, max_new_speak_tokens_per_chunk=20)
        view = SimpleNamespace(config=None)
        processor = SimpleNamespace(model=SimpleNamespace(duplex=decoder), set_duplex_mode=lambda: view)
        backend = SimpleNamespace(processor=processor)
        method = method_from_file('core/processors/pytorch_backend.py', 'PyTorchBackend', 'set_duplex_config',
                                  {'DuplexConfig': lambda **kw: SimpleNamespace(**kw),
                                   'logger': SimpleNamespace(info=lambda *args: None)})
        method(backend, {'generate_audio': False, 'max_new_speak_tokens_per_chunk': 96})
        self.assertFalse(decoder.generate_audio)
        self.assertEqual(decoder.max_new_speak_tokens_per_chunk, 96)
        method(backend, {'generate_audio': True, 'max_new_speak_tokens_per_chunk': 20})
        self.assertTrue(decoder.generate_audio)
        self.assertEqual(decoder.max_new_speak_tokens_per_chunk, 20)

    def test_generation_forwards_budget_and_other_options(self):
        captured = {}

        def generate(**kwargs):
            captured.update(kwargs)
            return {'is_listen': False, 'text': '<blank>'}

        model = SimpleNamespace(duplex=SimpleNamespace(max_new_speak_tokens_per_chunk=96, streaming_generate=generate))
        method = method_from_file('MiniCPMO45/modeling_minicpmo_unified.py', 'MiniCPMO', 'duplex_generate', {})
        result = method(model, temperature=0.2, force_listen_override=False)
        self.assertEqual(captured.get('max_new_speak_tokens_per_chunk'), 96)
        self.assertEqual(captured['temperature'], 0.2)
        self.assertFalse(captured['force_listen_override'])
        self.assertEqual(result['text'], '<blank>')


if __name__ == '__main__':
    unittest.main()
