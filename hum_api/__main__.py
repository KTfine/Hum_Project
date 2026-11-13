"""python -m hum_api --text ... [--image ...] [--interactive]."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from . import ApiError, DeepSeekClient, Image, PhotoSession


def parse_args(argv=None):
    p = argparse.ArgumentParser(description='DeepSeek text/image photography experiments (no camera or microphone)')
    p.add_argument('--text', help='first user message')
    p.add_argument('--image', action='append', default=[], type=Path, help='image for the first turn; repeatable')
    p.add_argument('--interactive', action='store_true', help='keep conversation in this process')
    p.add_argument('--prompt-file', type=Path, help='complete literal UTF-8 system prompt; disables automatic mode switching')
    p.add_argument('--mode', choices=['guidance', 'co-photo'], default='guidance')
    p.add_argument('--model', default='deepseek-flash')
    p.add_argument('--thinking', choices=['off', 'low', 'high', 'max'], default='low')
    p.add_argument('--timeout', type=float, default=90)
    p.add_argument('--max-tokens', type=int, default=4096)
    p.add_argument('--max-turns', type=int, default=20)
    p.add_argument('--allow-plain-speech', action='store_true', help='adapt untagged text to speak; recorded separately')
    p.add_argument('--character-persona', default='自然、敏锐、友善，像真实伙伴一样回应，但不要无意义地重复说话。')
    p.add_argument('--sprite-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'tachie/sanae')
    p.add_argument('--log-file', type=Path, help='local JSONL (default runtime_results/api/<unique run>.jsonl)')
    args = p.parse_args(argv)
    if not args.interactive and args.text is None and not args.image:
        p.error('provide --text, --image or --interactive')
    return args


def revision():
    try:
        root = Path(__file__).resolve().parents[1]
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, stderr=subprocess.DEVNULL, text=True))
        return {'commit': sha, 'dirty': dirty}
    except (OSError, subprocess.CalledProcessError):
        return {'commit': None, 'dirty': None}


async def run(args):
    log = args.log_file or Path('runtime_results/api') / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid4().hex[:8] + '.jsonl')
    log.parent.mkdir(parents=True, exist_ok=True)
    custom = args.prompt_file.read_text(encoding='utf-8-sig') if args.prompt_file else None
    state = {'sprite_id': 'normal', 'x': 0.5, 'y': 0.95, 'scale': 1.0, 'rotation': 0.0}
    repo = revision()
    print(f'[log] {log.resolve()}', file=sys.stderr)

    def save(row):
        with log.open('a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

    async with DeepSeekClient(model=args.model, thinking=args.thinking, timeout=args.timeout, max_tokens=args.max_tokens) as client:
        session = PhotoSession(client, mode=args.mode, system_prompt=custom, max_turns=args.max_turns,
                               allow_plain_speech=args.allow_plain_speech, character_persona=args.character_persona,
                               sprite_ids=[p.stem for p in args.sprite_dir.glob('*.png')], character_state=state)
        save({'event': 'run', **repo, 'started_utc': datetime.now(timezone.utc).isoformat()})
        paths, text = args.image, args.text
        pending = text is not None or bool(paths)
        if args.interactive:
            print('输入文字发送；/image 路径 为下一轮附图；/clear-images；/reset；/mode guidance|co-photo；/quit', file=sys.stderr)
        while True:
            if not pending:
                if not args.interactive:
                    return 0
                try:
                    text = input('\n你> ').strip()
                except EOFError:
                    return 0
                if text == '/quit':
                    return 0
                if text.startswith('/image '):
                    paths.append(Path(text[7:].strip().strip('"')))
                    continue
                if text == '/clear-images':
                    paths = []
                    continue
                if text == '/reset' or text.startswith('/mode '):
                    try:
                        session.reset(None if text == '/reset' else text[6:].strip())
                        paths = []
                        save({'event': 'reset', 'mode': session.mode})
                        print(f'[mode] {session.mode}', file=sys.stderr)
                    except ValueError as exc:
                        print(str(exc), file=sys.stderr)
                    continue
                if not text:
                    continue
            pending = False
            system = session.system_prompt
            try:
                images = [Image.from_path(p) for p in paths]
                result = await session.ask(text or '', images=images,
                                           on_delta=lambda s: print(s, end='', flush=True))
            except ApiError as exc:
                result = exc.result
                print(f'\n[error] {exc}', file=sys.stderr)
            except asyncio.CancelledError as exc:
                if hasattr(exc, 'result'):
                    save({'event': 'turn', 'system_prompt': system, 'input_text': text or '',
                          'output': exc.result.text, **exc.result.metadata})
                raise
            except (OSError, ValueError) as exc:
                save({'event': 'input_error', 'error': str(exc)})
                print(f'[input] {exc}', file=sys.stderr)
                if not args.interactive:
                    return 1
                continue
            print()
            save({'event': 'turn', 'system_prompt': system, 'input_text': text or '',
                  'output': result.text, **result.metadata})
            print(f'[mode] {session.mode}; [status] {result.metadata["status"]}', file=sys.stderr)
            paths = []
            if not args.interactive:
                return 0 if result.metadata['status'] == 'ok' else 1


def main():
    try:
        return asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError) as exc:
        print(f'[error] {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
