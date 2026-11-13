"""Replay typed turns through the API gateway and real frontend parser; no devices.

Run from the main checkout after starting the backend branch's API service.
Only the backend process needs DEEPSEEK_API_KEY. Logs contain model text, not media.
"""
import argparse
import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
import websockets

import realtime_av_test as frontend


async def run(args):
    stop = threading.Event()
    canvas = frontend.CanvasSource(ROOT / 'tachie/sanae', 'normal', 1280, 720, 80, stop, preview=False)
    selection = frontend.ModeSelection()
    speech = frontend.SpeechQueue()
    options = frontend.parse_args(['--backend', 'api', '--no-camera', '--no-preview'])
    camera_frame = None
    if args.image:
        camera_frame = cv2.imdecode(np.frombuffer(args.image.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if camera_frame is None:
            raise ValueError('Cannot decode image')
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    ws = None
    ready_mode = None
    system = ''
    records = []
    try:
        canvas.start()
        for number, text in enumerate(args.text, 1):
            stop.clear()
            mode, revision = selection.snapshot()
            if ws is None or mode != ready_mode:
                if ws is not None:
                    await ws.send(json.dumps({'type': 'session.close', 'reason': 'mode_switch'}))
                    await ws.close()
                ws = await websockets.connect(frontend.normalize_video_ws_url(args.url), max_size=128 * 1024 * 1024)
                system = frontend.build_control_prompt(canvas, options, mode=mode)
                await frontend.open_realtime_session(ws, frontend.build_session_init(system, use_tts=False))
                selection.mark_loaded(mode, revision)
                ready_mode = mode
            frames = canvas.latest_jpeg(camera_frame, include_character=mode == 'co-photo')
            message = frontend.build_video_input(number, b'\0' * frontend.AUDIO_CHUNK_BYTES, frames)
            message['input']['text'] = text
            before = asdict(canvas.controller.state_at())
            events = []

            class CapturingSocket:
                async def recv(self):
                    raw = await ws.recv()
                    event = json.loads(raw)
                    events.append(frontend.summarize_protocol_message(event))
                    if event.get('type') == 'response.done':
                        stop.set()
                    return raw

            started = time.monotonic()
            await ws.send(json.dumps(message, ensure_ascii=False))
            error = None
            try:
                await asyncio.wait_for(frontend.receive_realtime_outputs(
                    CapturingSocket(), stop, canvas, speech, verbose=False, mode_selection=selection), args.timeout)
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
            # Evaluate the completed animation target without waiting on a device.
            after = asdict(canvas.controller.state_at(time.monotonic() + 60))
            record = {'turn': number, 'mode': mode, 'requested_mode': selection.mode,
                      'system_prompt': system,
                      'system_sha256': hashlib.sha256(system.encode()).hexdigest(),
                      'input_text': text, 'image': args.image.name if args.image else None,
                      'elapsed_seconds': round(time.monotonic() - started, 3),
                      'state_before': before, 'state_after': after, 'events': events, 'error': error}
            records.append(record)
            output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({key: record[key] for key in ('turn', 'mode', 'requested_mode', 'elapsed_seconds', 'error')}, ensure_ascii=False))
            if error:
                return 1
    finally:
        if ws is not None:
            await ws.close()
        canvas.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8006')
    parser.add_argument('--text', action='append', required=True, help='Repeat for sequential turns')
    parser.add_argument('--image', type=Path)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--output', type=Path, default=ROOT / 'experiments/runtime/api-gateway-probe.json')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    raise SystemExit(asyncio.run(run(args)))


if __name__ == '__main__':
    main()
