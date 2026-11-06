"""Exercise the existing realtime client with repeatable spoken instructions."""
import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys
import threading
import time
import wave

import cv2
import numpy as np
import websockets

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT
sys.path.insert(0, str(SOURCE))
import realtime_av_test as client


def wav_samples(path):
    with wave.open(str(path), 'rb') as source:
        if (source.getnchannels(), source.getframerate(), source.getsampwidth()) != (1, 16000, 2):
            raise ValueError('Probe speech must be 16 kHz mono signed 16-bit WAV')
        return np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype('<f4') / 32768.0


async def run(args):
    out = ROOT / 'runtime_results' / args.output_subdir
    out.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    canvas = client.CanvasSource(SOURCE / 'tachie/sanae', 'normal', 1280, 720, 80, stop, preview=args.preview)
    camera = None if args.no_camera else client.CameraSource(0, stop)
    logger = client.FrontendEventLogger(out / 'effect-probe.jsonl')
    canvas.start()
    cv2.imwrite(str(out / 'initial-avatar.png'), canvas.render_frame())
    websocket = None
    receiver = None
    try:
        if camera is not None:
            camera.start()
            print('CAMERA_FRAME', camera.latest_frame().shape, flush=True)
        prompt_args = client.parse_args([])
        prompt = client.build_control_prompt(canvas, prompt_args)
        if args.prompt_file:
            prompt = Path(args.prompt_file).read_text(encoding='utf-8')
        init = client.build_session_init(prompt, use_tts=False)
        if args.generation_config:
            init['payload']['config'].update(json.loads(args.generation_config))
        websocket, created = await client.connect_and_open_session_with_retry(
            websockets.connect, client.normalize_video_ws_url(args.url), client.make_tls_context(True),
            init, connect_timeout=15, session_timeout=120, event_log=logger,
        )
        print('SESSION', created.get('session_id'), flush=True)
        receiver = asyncio.create_task(client.receive_realtime_outputs(
            websocket, stop, canvas, client.SpeechQueue(), verbose=True, event_log=logger,
        ))
        timeline = np.zeros(args.seconds * 16000, dtype='<f4')
        instructions = [(3, 'move_left_smile.wav'), (25, 'return_center.wav')]
        if args.instructions_file:
            instructions = json.loads(Path(args.instructions_file).read_text(encoding='utf-8'))
        if args.visual_check:
            instructions.append((40, 'visual_color_check.wav'))
        for start_second, file_name in instructions:
            spoken = wav_samples(ROOT / 'runtime_results' / file_name)
            offset = start_second * 16000
            count = min(len(spoken), max(0, len(timeline) - offset))
            timeline[offset:offset + count] = spoken[:count]
        samples = []
        max_shift = 0.0
        last_snapshot_state = None
        began = time.monotonic()
        for sequence in range(args.seconds):
            if stop.is_set() or receiver.done():
                break
            frame = camera.latest_frame() if camera is not None else None
            if args.visual_check and sequence >= 40 and frame is not None:
                frame = frame.copy()
                cv2.rectangle(frame, (20, 20), (150, 150), (0, 0, 255), thickness=-1)
            jpeg = canvas.latest_jpeg(frame)
            audio = timeline[sequence * 16000:(sequence + 1) * 16000].tobytes()
            message = client.build_video_input(sequence + 1, audio, jpeg)
            await websocket.send(json.dumps(message))
            logger.record_message('gateway.send', message)
            current = canvas.controller.state_at()
            samples.append({'second': sequence, **asdict(current)})
            if asdict(current) != last_snapshot_state:
                cv2.imwrite(str(out / f'state-{sequence:03d}.png'), canvas.render_frame())
                last_snapshot_state = asdict(current)
            shift = abs(current.x - 0.5)
            if shift > max_shift:
                max_shift = shift
                cv2.imwrite(str(out / 'moved-avatar.png'), canvas.render_frame())
            await asyncio.sleep(max(0, began + sequence + 1 - time.monotonic()))
        final = asdict(canvas.controller.state_at())
        cv2.imwrite(str(out / 'final-avatar.png'), canvas.render_frame())
        (out / 'effect-state.json').write_text(json.dumps({'session_id': created.get('session_id'), 'max_horizontal_shift': max_shift, 'states': samples, 'final': final}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('FINAL_STATE', json.dumps(final, ensure_ascii=False), flush=True)
        if receiver.done():
            receiver.result()
        else:
            await websocket.send(json.dumps({'type': 'session.close', 'reason': 'probe_complete'}))
            try:
                await asyncio.wait_for(receiver, 5)
            except asyncio.TimeoutError:
                receiver.cancel()
    finally:
        stop.set()
        if receiver is not None:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
        if websocket is not None:
            await websocket.close()
        if camera is not None:
            camera.close()
        canvas.close()
        logger.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='https://localhost:18006')
    parser.add_argument('--seconds', type=int, default=50)
    parser.add_argument('--no-camera', action='store_true')
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--visual-check', action='store_true')
    parser.add_argument('--output-subdir', default='')
    parser.add_argument('--prompt-file')
    parser.add_argument('--instructions-file')
    parser.add_argument('--generation-config')
    asyncio.run(run(parser.parse_args()))
