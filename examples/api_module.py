"""Run from repo root: python -m examples.api_module --image path/to/image.png."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path

from hum_api import DeepSeekClient, Image, PhotoSession


async def main():
    parser = argparse.ArgumentParser(description='Image/observation input and incremental command callback example')
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--text', default='我想拍一张展现活力的照片，请给一个适合这个场景的姿势建议。')
    parser.add_argument('--observations-json', type=Path, help='optional actual observations from your module')
    args = parser.parse_args()
    observations = json.loads(args.observations_json.read_text(encoding='utf-8')) if args.observations_json else None

    def receive_command(command):
        # Replace with a fast queue.put(command) for the UI/voice/avatar module.
        # All valid commands arrive here, including actions in guidance mode.
        print(json.dumps(asdict(command), ensure_ascii=False), flush=True)

    async with DeepSeekClient() as client:
        session = PhotoSession(client)
        result = await session.ask(args.text, images=[Image.from_path(args.image)],
                                   observations=observations, on_command=receive_command)
        print(json.dumps(result.metadata, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
