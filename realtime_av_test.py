"""Interactive white-canvas sprite controller for MiniCPM-o realtime video."""

import argparse
import asyncio
import base64
from collections import deque
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import ssl
import sys
import threading
import time
import traceback
from urllib.parse import urlsplit, urlunsplit

import numpy as np

from command_protocol import Command, StreamingCommandParser


AUDIO_SAMPLE_RATE = 16_000
AUDIO_SAMPLE_BYTES = 4
AUDIO_CHUNK_BYTES = AUDIO_SAMPLE_RATE * AUDIO_SAMPLE_BYTES


class RealtimeServiceError(RuntimeError):
    pass


def _decoded_base64_size(value: object) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        return len(base64.b64decode(value, validate=True))
    except (ValueError, TypeError):
        return None


def summarize_protocol_message(value: object) -> object:
    """Copy a protocol message while replacing binary Base64 with byte counts."""
    if isinstance(value, list):
        return [summarize_protocol_message(item) for item in value]
    if not isinstance(value, dict):
        return value
    summary = {}
    for key, item in value.items():
        if key in {"audio", "ref_audio_base64", "tts_ref_audio_base64"}:
            summary[f"{key}_bytes"] = _decoded_base64_size(item)
        elif key == "video_frames" and isinstance(item, list):
            summary["video_frame_bytes"] = [
                _decoded_base64_size(frame) for frame in item
            ]
        else:
            summary[key] = summarize_protocol_message(item)
    return summary


class FrontendEventLogger:
    """Thread-safe JSONL log for protocol, parser, control, and failure events."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8", buffering=1)
        self._lock = threading.Lock()

    def record(self, event: str, **fields) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self._file.write(line + "\n")

    def record_message(self, event: str, message: dict) -> None:
        self.record(event, message=summarize_protocol_message(message))

    def record_exception(self, event: str, exc: BaseException) -> None:
        self.record(
            event,
            error_type=type(exc).__name__,
            error=str(exc),
            traceback="".join(traceback.format_exception(exc)),
        )

    def close(self) -> None:
        with self._lock:
            self._file.close()


class AudioInputBuffer:
    """Thread-safe newest-audio buffer that never accumulates latency."""

    def __init__(self, chunk_bytes: int = AUDIO_CHUNK_BYTES) -> None:
        if chunk_bytes <= 0:
            raise ValueError("chunk_bytes must be positive")
        self.chunk_bytes = chunk_bytes
        self._data = bytearray()
        self._lock = threading.Lock()

    def push(self, data: bytes) -> None:
        with self._lock:
            self._data.extend(data)
            if len(self._data) > self.chunk_bytes:
                del self._data[: len(self._data) - self.chunk_bytes]

    def pop_chunk(self) -> bytes:
        with self._lock:
            data = bytes(self._data)
            self._data.clear()
        return data + (b"\x00" * (self.chunk_bytes - len(data)))


class MicrophoneSource:
    """Capture 16 kHz mono Float32 PCM into an AudioInputBuffer."""

    def __init__(self, buffer: AudioInputBuffer, device=None) -> None:
        self.buffer = buffer
        self.device = device
        self._stream = None

    def start(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                "sounddevice is required for microphone capture; "
                "install requirements-client.txt"
            ) from exc

        def callback(indata, _frames, _time_info, status) -> None:
            if status:
                print(f"\n[microphone] {status}", file=sys.stderr, flush=True)
            self.buffer.push(bytes(indata))

        self._stream = sd.RawInputStream(
            samplerate=AUDIO_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=1_600,
            device=self.device,
            callback=callback,
        )
        self._stream.start()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


@dataclass(frozen=True)
class SpriteState:
    sprite_id: str
    x: float
    y: float
    scale: float
    rotation: float


class SpriteController:
    """Maintain sprite state with independent geometry animation lanes."""

    def __init__(self, sprite_ids: set[str], initial_state: SpriteState) -> None:
        if initial_state.sprite_id not in sprite_ids:
            raise ValueError(f"unknown initial sprite: {initial_state.sprite_id}")
        self.sprite_ids = frozenset(sprite_ids)
        self._current = initial_state
        self._transitions: dict[str, tuple[float, float, float, float]] = {}
        self._lock = threading.RLock()

    def state_at(self, now: float | None = None) -> SpriteState:
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            return self._state_at_unlocked(timestamp)

    def _state_at_unlocked(self, now: float) -> SpriteState:
        values = {}
        for name in ("x", "y", "scale", "rotation"):
            transition = self._transitions.get(name)
            if transition is None:
                values[name] = getattr(self._current, name)
                continue
            start, target, started_at, duration = transition
            if duration <= 0 or now >= started_at + duration:
                values[name] = target
                self._current = replace(self._current, **{name: target})
                del self._transitions[name]
                continue
            progress = max(0.0, (now - started_at) / duration)
            values[name] = start + (target - start) * progress
        return SpriteState(sprite_id=self._current.sprite_id, **values)

    def _target_state_unlocked(self) -> SpriteState:
        values = {}
        for name in ("x", "y", "scale", "rotation"):
            transition = self._transitions.get(name)
            values[name] = transition[1] if transition else getattr(self._current, name)
        return SpriteState(sprite_id=self._current.sprite_id, **values)

    def _set_lane(
        self, name: str, start: float, target: float, now: float, duration_ms: float
    ) -> None:
        if duration_ms <= 0:
            self._current = replace(self._current, **{name: target})
            self._transitions.pop(name, None)
        else:
            self._transitions[name] = (start, target, now, duration_ms / 1000.0)

    def apply_command(self, command, now: float | None = None) -> SpriteState | None:
        timestamp = time.monotonic() if now is None else now
        with self._lock:
            current = self._state_at_unlocked(timestamp)
            params = command.params
            if command.kind == "blank":
                return None
            if command.kind == "tachie":
                sprite_id = str(params["sprite_id"])
                if sprite_id not in self.sprite_ids:
                    return None
                self._current = replace(self._current, sprite_id=sprite_id)
                return self._target_state_unlocked()
            if command.kind not in {"move", "scale", "rotate"}:
                return None

            duration_ms = float(params.get("ms", 350))
            targets: dict[str, float] = {}
            latest = self._target_state_unlocked()
            if command.kind == "move":
                if params["mode"] == "to":
                    for name in ("x", "y"):
                        if name in params:
                            targets[name] = float(params[name])
                else:
                    if "dx" in params:
                        targets["x"] = min(1.0, max(0.0, latest.x + float(params["dx"])))
                    if "dy" in params:
                        targets["y"] = min(1.0, max(0.0, latest.y + float(params["dy"])))
            elif command.kind == "scale":
                value = (
                    float(params["value"])
                    if params["mode"] == "to"
                    else latest.scale * float(params["factor"])
                )
                targets["scale"] = min(3.0, max(0.1, value))
            else:
                value = (
                    float(params["value"])
                    if params["mode"] == "to"
                    else latest.rotation + float(params["value"])
                )
                targets["rotation"] = min(180.0, max(-180.0, value))

            for name, target in targets.items():
                self._set_lane(
                    name,
                    getattr(current, name),
                    target,
                    timestamp,
                    duration_ms,
                )
            return self._target_state_unlocked()

class SpeechQueue:
    """Thread-safe FIFO for the current text sink and future sequential TTS."""

    def __init__(self) -> None:
        self._items: deque[str] = deque()
        self._lock = threading.Lock()

    def enqueue(self, text: str) -> None:
        if text:
            with self._lock:
                self._items.append(text)

    def pop_next(self) -> str | None:
        with self._lock:
            return self._items.popleft() if self._items else None


def alpha_composite_at(
    canvas: np.ndarray, sprite: np.ndarray, left: int, top: int
) -> None:
    """Alpha-composite a BGRA sprite onto a BGR canvas, clipping at its edges."""
    if canvas.ndim != 3 or canvas.shape[2] != 3:
        raise ValueError("canvas must be a BGR image")
    if sprite.ndim != 3 or sprite.shape[2] != 4:
        raise ValueError("sprite must be a BGRA image")

    canvas_h, canvas_w = canvas.shape[:2]
    sprite_h, sprite_w = sprite.shape[:2]
    dst_left = max(0, left)
    dst_top = max(0, top)
    dst_right = min(canvas_w, left + sprite_w)
    dst_bottom = min(canvas_h, top + sprite_h)
    if dst_left >= dst_right or dst_top >= dst_bottom:
        return

    src_left = dst_left - left
    src_top = dst_top - top
    src_right = src_left + (dst_right - dst_left)
    src_bottom = src_top + (dst_bottom - dst_top)
    source = sprite[src_top:src_bottom, src_left:src_right]
    destination = canvas[dst_top:dst_bottom, dst_left:dst_right]
    alpha = source[:, :, 3:4].astype(np.float32) / 255.0
    blended = source[:, :, :3].astype(np.float32) * alpha
    blended += destination.astype(np.float32) * (1.0 - alpha)
    destination[:] = np.rint(blended).clip(0, 255).astype(np.uint8)


def compose_model_frame(
    camera_frame: np.ndarray | None,
    character_frame: np.ndarray,
    inset_ratio: float = 0.28,
) -> np.ndarray:
    """Return the camera image with an aspect-preserving character inset."""
    if camera_frame is None:
        return character_frame.copy()
    if not 0.1 <= inset_ratio <= 0.8:
        raise ValueError("inset_ratio must be between 0.1 and 0.8")
    if camera_frame.ndim != 3 or camera_frame.shape[2] != 3:
        raise ValueError("camera_frame must be a BGR image")
    if character_frame.ndim != 3 or character_frame.shape[2] != 3:
        raise ValueError("character_frame must be a BGR image")

    import cv2

    result = camera_frame.copy()
    camera_h, camera_w = result.shape[:2]
    character_h, character_w = character_frame.shape[:2]
    max_w = max(1, int(round(camera_w * inset_ratio)))
    max_h = max(1, int(round(camera_h * inset_ratio)))
    resize_scale = min(max_w / character_w, max_h / character_h)
    inset_w = max(1, int(round(character_w * resize_scale)))
    inset_h = max(1, int(round(character_h * resize_scale)))
    inset = cv2.resize(character_frame, (inset_w, inset_h), interpolation=cv2.INTER_AREA)
    margin = min(8, max(0, min(camera_h - inset_h, camera_w - inset_w)))
    top = margin
    left = camera_w - inset_w - margin
    result[top : top + inset_h, left : left + inset_w] = inset
    return result


class CameraSource:
    """Continuously retain only the newest non-stale webcam frame."""

    def __init__(
        self,
        device_index: int,
        stop_event: threading.Event,
        *,
        max_frame_age: float = 2.5,
    ) -> None:
        self.device_index = device_index
        self.stop_event = stop_event
        self.max_frame_age = max_frame_age
        self._capture = None
        self._thread = None
        self._frame: np.ndarray | None = None
        self._frame_time = float("-inf")
        self._lock = threading.Lock()

    def start(self) -> None:
        import cv2

        capture = cv2.VideoCapture(self.device_index)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError(f"cannot open camera device {self.device_index}")
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = capture.read()
        if not ok or frame is None:
            capture.release()
            raise RuntimeError(f"camera device {self.device_index} returned no frame")
        with self._lock:
            self._frame = frame.copy()
            self._frame_time = time.monotonic()
        self._capture = capture
        self._thread = threading.Thread(
            target=self._capture_loop, name="camera-capture", daemon=True
        )
        self._thread.start()

    def _capture_loop(self) -> None:
        while not self.stop_event.is_set():
            ok, frame = self._capture.read()
            if not ok or frame is None:
                time.sleep(0.05)
                continue
            with self._lock:
                self._frame = frame.copy()
                self._frame_time = time.monotonic()

    def latest_frame(self) -> np.ndarray | None:
        with self._lock:
            if (
                self._frame is None
                or time.monotonic() - self._frame_time > self.max_frame_age
            ):
                return None
            return self._frame.copy()

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._capture = None


class CanvasSource:
    """Render a controllable PNG sprite over a white canvas."""

    WINDOW_TITLE = "MiniCPM-o sprite test - press Q to stop"

    def __init__(
        self,
        sprite_dir: Path,
        initial_sprite: str,
        width: int,
        height: int,
        jpeg_quality: int,
        stop_event: threading.Event,
        *,
        preview: bool,
    ) -> None:
        self.sprite_dir = Path(sprite_dir)
        self.initial_sprite = initial_sprite
        self.width = width
        self.height = height
        self.jpeg_quality = jpeg_quality
        self.stop_event = stop_event
        self.preview = preview
        self.sprites: dict[str, np.ndarray] = {}
        self.controller: SpriteController | None = None
        self._thread = None
        self.error: Exception | None = None

    @property
    def sprite_ids(self) -> list[str]:
        return sorted(self.sprites)

    def start(self) -> None:
        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError(
                "opencv-python is required; install requirements-client.txt"
            ) from exc
        if not self.sprite_dir.is_dir():
            raise RuntimeError(f"sprite directory does not exist: {self.sprite_dir}")
        for path in sorted(self.sprite_dir.glob("*.png")):
            image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if image is None:
                raise RuntimeError(f"failed to load sprite: {path}")
            if image.ndim == 2:
                image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
            elif image.shape[2] == 3:
                alpha = np.full(image.shape[:2] + (1,), 255, dtype=np.uint8)
                image = np.concatenate((image, alpha), axis=2)
            self.sprites[path.stem] = image
        if not self.sprites:
            raise RuntimeError(f"no PNG sprites found in {self.sprite_dir}")
        initial = SpriteState(self.initial_sprite, 0.5, 0.95, 1.0, 0.0)
        self.controller = SpriteController(set(self.sprites), initial)
        if self.preview:
            self._thread = threading.Thread(
                target=self._preview_loop, name="canvas-preview", daemon=True
            )
            self._thread.start()

    def apply_command(self, command: Command) -> SpriteState | None:
        if self.controller is None:
            raise RuntimeError("canvas has not been started")
        return self.controller.apply_command(command)

    def render_frame(self, now: float | None = None) -> np.ndarray:
        if self.controller is None:
            raise RuntimeError("canvas has not been started")
        state = self.controller.state_at(now)
        sprite = self._transform_sprite(self.sprites[state.sprite_id], state)
        canvas = np.full((self.height, self.width, 3), 255, dtype=np.uint8)
        anchor_x = int(round(state.x * self.width))
        anchor_y = int(round(state.y * self.height))
        left = anchor_x - sprite.shape[1] // 2
        top = anchor_y - sprite.shape[0]
        alpha_composite_at(canvas, sprite, left, top)
        return canvas

    def _transform_sprite(
        self, sprite: np.ndarray, state: SpriteState
    ) -> np.ndarray:
        import cv2

        sprite_h, sprite_w = sprite.shape[:2]
        fit_scale = min(
            1.0,
            (self.width * 0.9) / sprite_w,
            (self.height * 0.9) / sprite_h,
        )
        scale = fit_scale * state.scale
        radians = math.radians(state.rotation)
        cos_value = abs(math.cos(radians) * scale)
        sin_value = abs(math.sin(radians) * scale)
        output_w = max(1, int(math.ceil(sprite_w * cos_value + sprite_h * sin_value)))
        output_h = max(1, int(math.ceil(sprite_h * cos_value + sprite_w * sin_value)))
        matrix = cv2.getRotationMatrix2D(
            (sprite_w / 2.0, sprite_h / 2.0), -state.rotation, scale
        )
        matrix[0, 2] += output_w / 2.0 - sprite_w / 2.0
        matrix[1, 2] += output_h / 2.0 - sprite_h / 2.0
        return cv2.warpAffine(
            sprite,
            matrix,
            (output_w, output_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )

    def latest_jpeg(self, camera_frame: np.ndarray | None = None) -> bytes:
        import cv2

        frame = compose_model_frame(camera_frame, self.render_frame())
        ok, encoded = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
        )
        if not ok:
            raise RuntimeError("failed to JPEG-encode canvas")
        return encoded.tobytes()

    def _preview_loop(self) -> None:
        import cv2

        try:
            while not self.stop_event.is_set():
                cv2.imshow(self.WINDOW_TITLE, self.render_frame())
                if cv2.waitKey(16) & 0xFF in (ord("q"), ord("Q")):
                    self.stop_event.set()
                    break
        except Exception as exc:
            self.error = exc
            self.stop_event.set()
        finally:
            cv2.destroyAllWindows()

    def close(self) -> None:
        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


def normalize_video_ws_url(url: str) -> str:
    """Return the MiniCPM-o video realtime WebSocket endpoint for *url*."""
    value = url.strip()
    if "://" not in value:
        value = f"https://{value}"
    parts = urlsplit(value)
    scheme = {"https": "wss", "http": "ws", "wss": "wss", "ws": "ws"}.get(
        parts.scheme.lower()
    )
    if scheme is None:
        raise ValueError(f"Unsupported URL scheme: {parts.scheme!r}")
    return urlunsplit((scheme, parts.netloc, "/v1/realtime", "mode=video", ""))


def build_session_init(
    system_prompt: str,
    *,
    use_tts: bool,
    max_slice_nums: int = 1,
    length_penalty: float = 1.0,
) -> dict:
    return {
        "type": "session.init",
        "payload": {
            "system_prompt": system_prompt,
            "config": {
                "length_penalty": length_penalty,
                "generate_audio": use_tts,
                "max_new_speak_tokens_per_chunk": 96,
                "temperature": 0.2,
                "top_p": 0.8,
                "top_k": 10,
            },
            "max_slice_nums": max_slice_nums,
            # Kept for compatibility with the locally documented gateway. Current
            # duplex backends use config.generate_audio instead.
            "use_tts": use_tts,
        },
    }


def build_video_input(
    sequence: int,
    audio_bytes: bytes,
    jpeg_bytes: bytes | None,
    *,
    force_listen: bool = False,
    max_slice_nums: int = 1,
) -> dict:
    """Build one one-second full-duplex input message."""
    if len(audio_bytes) != AUDIO_CHUNK_BYTES:
        raise ValueError(
            f"audio chunk must contain exactly {AUDIO_CHUNK_BYTES} bytes "
            "(one second of 16 kHz mono Float32 PCM)"
        )
    input_payload = {
        "input_id": f"chunk-{sequence:06d}",
        "audio": base64.b64encode(audio_bytes).decode("ascii"),
        "force_listen": force_listen,
        "max_slice_nums": max_slice_nums,
    }
    if jpeg_bytes is not None:
        input_payload["video_frames"] = [
            base64.b64encode(jpeg_bytes).decode("ascii")
        ]
    return {"type": "input.append", "input": input_payload}


def decode_output_event(event: dict) -> tuple[str, object]:
    """Convert a gateway event into the client-facing streaming value."""
    event_type = event.get("type")
    if event_type == "error":
        error = event.get("error") or {}
        code = error.get("code", "unknown_error")
        message = error.get("message", "no message")
        raise RealtimeServiceError(f"{code}: {message}")
    if event_type == "session.closed":
        return "closed", event.get("reason", "unknown")
    if event_type == "response.done":
        return "done", event.get("text", "")
    if event_type != "response.output.delta":
        return "other", event
    kind = event.get("kind")
    if kind == "text":
        return "text", event.get("text", "")
    if kind == "audio":
        return "audio", base64.b64decode(event.get("audio", ""), validate=True)
    if kind == "listen":
        return "listen", None
    return "other", event


async def open_realtime_session(
    websocket, init_message: dict, event_log: FrontendEventLogger | None = None
) -> dict:
    """Complete the gateway queue and initialization handshake."""
    init_sent = False
    while True:
        event = json.loads(await websocket.recv())
        if event_log is not None:
            event_log.record_message("gateway.receive", event)
        event_type = event.get("type")
        if event_type == "error":
            decode_output_event(event)
        if event_type == "session.queue_done" and not init_sent:
            await websocket.send(json.dumps(init_message, ensure_ascii=False))
            if event_log is not None:
                event_log.record_message("gateway.send", init_message)
            init_sent = True
        elif event_type == "session.created":
            return event


async def connect_and_open_session_with_retry(
    connect,
    ws_url: str,
    ssl_context,
    init_message: dict,
    *,
    connect_timeout: float,
    session_timeout: float,
    attempts: int = 3,
    sleep=asyncio.sleep,
    event_log: FrontendEventLogger | None = None,
):
    """Retry transient transport failures that occur before session creation."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    for attempt in range(1, attempts + 1):
        websocket = None
        try:
            websocket = await connect(
                ws_url,
                ssl=ssl_context,
                max_size=128 * 1024 * 1024,
                open_timeout=connect_timeout,
                ping_interval=20,
                ping_timeout=20,
            )
            created = await asyncio.wait_for(
                open_realtime_session(websocket, init_message, event_log),
                timeout=session_timeout,
            )
            return websocket, created
        except (OSError, asyncio.TimeoutError) as exc:
            if event_log is not None:
                event_log.record(
                    "connection.retry",
                    attempt=attempt,
                    max_attempts=attempts,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            if websocket is not None:
                await websocket.close()
            if attempt >= attempts:
                raise
            delay = min(2 ** (attempt - 1), 4)
            print(
                f"[connect] transient failure ({exc}); retrying "
                f"{attempt + 1}/{attempts} in {delay}s",
                file=sys.stderr,
                flush=True,
            )
            await sleep(delay)
    raise RuntimeError("unreachable")


async def send_realtime_inputs(
    websocket,
    canvas: CanvasSource,
    camera: CameraSource | None,
    audio_buffer: AudioInputBuffer,
    stop_event: threading.Event,
    *,
    event_log: FrontendEventLogger | None = None,
) -> None:
    """Send real-time audio and periodically attach camera plus character inset."""
    loop = asyncio.get_running_loop()
    next_tick = loop.time()
    sequence = 0
    while not stop_event.is_set():
        camera_frame = camera.latest_frame() if camera is not None else None
        jpeg = canvas.latest_jpeg(camera_frame)
        sequence += 1
        message = build_video_input(sequence, audio_buffer.pop_chunk(), jpeg)
        await websocket.send(json.dumps(message, ensure_ascii=False))
        if event_log is not None:
            event_log.record_message("gateway.send", message)
        next_tick += 1.0
        delay = next_tick - loop.time()
        if delay <= 0:
            next_tick = loop.time()
            continue
        await asyncio.sleep(delay)


def dispatch_model_commands(
    commands: list[Command],
    canvas: CanvasSource,
    speech_queue: SpeechQueue,
    event_log: FrontendEventLogger | None = None,
    *,
    verbose: bool = False,
) -> None:
    """Dispatch valid commands; invalid semantic commands are silently ignored."""
    for command in commands:
        if command.kind == "speak":
            speech_queue.enqueue(str(command.params["text"]))
        elif command.kind == "blank":
            if verbose:
                print("[blank]", flush=True)
        else:
            try:
                target = canvas.apply_command(command)
            except (TypeError, ValueError, RuntimeError) as exc:
                if event_log is not None:
                    event_log.record(
                        "command.skipped", command=asdict(command), error=str(exc)
                    )
                continue
            if target is not None:
                print(
                    f"[canvas] {command.kind} "
                    f"{json.dumps(command.params, ensure_ascii=False)}",
                    flush=True,
                )
                if event_log is not None:
                    event_log.record(
                        "command.applied",
                        command=asdict(command),
                        target=asdict(target),
                    )

    while True:
        text = speech_queue.pop_next()
        if text is None:
            break
        print(f"[speak] {text}", flush=True)
        if event_log is not None:
            event_log.record("speak", text=text)


async def receive_realtime_outputs(
    websocket,
    stop_event: threading.Event,
    canvas: CanvasSource,
    speech_queue: SpeechQueue,
    *,
    verbose: bool,
    event_log: FrontendEventLogger | None = None,
) -> None:
    """Print raw deltas and dispatch complete streamed tag commands immediately."""
    parser = StreamingCommandParser()
    active_response_id = None
    while not stop_event.is_set():
        raw = await websocket.recv()
        event = json.loads(raw)
        if event_log is not None:
            event_log.record_message("gateway.receive", event)
        kind, value = decode_output_event(event)
        response_id = event.get("response_id")

        if kind == "text":
            if response_id != active_response_id:
                if active_response_id is not None:
                    print()
                print("[model] ", end="", flush=True)
                active_response_id = response_id
            print(value, end="", flush=True)
            commands = parser.feed(response_id, str(value))
            if event_log is not None:
                for command in commands:
                    event_log.record("parser.command", command=asdict(command))
            dispatch_model_commands(
                commands, canvas, speech_queue, event_log, verbose=verbose
            )
        elif kind in ("listen", "done"):
            parser.flush(response_id if kind == "done" else None)
            if active_response_id is not None:
                print()
            if kind == "listen" and verbose:
                print("[model] listening", flush=True)
            active_response_id = None
        elif kind == "audio":
            if verbose:
                print("[model] ignored unexpected audio output", file=sys.stderr)
        elif kind == "closed":
            print(f"\n[session] closed: {value}", flush=True)
            stop_event.set()
            return

        if verbose and event.get("metrics"):
            print(
                f"\n[metrics] {json.dumps(event['metrics'], ensure_ascii=False)}",
                file=sys.stderr,
                flush=True,
            )


def make_tls_context(insecure: bool) -> ssl.SSLContext:
    if insecure:
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def build_control_prompt(canvas: CanvasSource, args: argparse.Namespace) -> str:
    from prompt import STREAMING_COMMAND_PROMPT

    if canvas.controller is None:
        raise RuntimeError("canvas has not been started")
    return STREAMING_COMMAND_PROMPT.format(
        character_name=args.character_name,
        character_persona=args.character_persona,
        response_language="中文",
        sprite_catalog=", ".join(canvas.sprite_ids),
        current_character_state=json.dumps(
            asdict(canvas.controller.state_at()), ensure_ascii=False
        ),
        recent_context="这是一次新会话，没有更早的上下文。",
        extra_instructions="用户通过麦克风与你说话；保持回复简短。",
    )


async def run_probe(
    args: argparse.Namespace, event_log: FrontendEventLogger | None = None
) -> None:
    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "websockets is required; install requirements-client.txt"
        ) from exc

    stop_event = threading.Event()
    audio_buffer = AudioInputBuffer()
    canvas = CanvasSource(
        args.sprite_dir,
        args.initial_sprite,
        args.canvas_width,
        args.canvas_height,
        args.jpeg_quality,
        stop_event,
        preview=not args.no_preview,
    )
    camera = None if args.no_camera else CameraSource(args.camera_device, stop_event)
    microphone = None if args.no_mic else MicrophoneSource(audio_buffer, args.input_device)
    speech_queue = SpeechQueue()
    ws_url = normalize_video_ws_url(args.url)
    ssl_context = make_tls_context(args.insecure) if ws_url.startswith("wss://") else None

    try:
        if camera is not None:
            camera.start()
        canvas.start()
        if microphone is not None:
            microphone.start()
    except Exception:
        stop_event.set()
        if microphone is not None:
            microphone.close()
        canvas.close()
        if camera is not None:
            camera.close()
        raise
    system_prompt = args.prompt or build_control_prompt(canvas, args)

    if event_log is not None:
        event_log.record(
            "client.start",
            url=ws_url,
            sprite_dir=str(args.sprite_dir),
            sprite_ids=canvas.sprite_ids,
            initial_sprite=args.initial_sprite,
            canvas_width=args.canvas_width,
            canvas_height=args.canvas_height,
            microphone_enabled=not args.no_mic,
            camera_enabled=not args.no_camera,
            camera_device=args.camera_device,
        )

    print(f"[sprites] {', '.join(canvas.sprite_ids)}", flush=True)
    print(f"[connect] {ws_url}", flush=True)
    print(
        f"[camera] {'disabled' if camera is None else f'device {args.camera_device}'}",
        flush=True,
    )
    print("[controls] press Q in the canvas window or Ctrl+C to stop", flush=True)
    print("[audio] MiniCPM-o TTS is disabled; model text is printed below", flush=True)

    try:
        websocket, created = await connect_and_open_session_with_retry(
            websockets.connect,
            ws_url,
            ssl_context,
            build_session_init(system_prompt, use_tts=False),
            connect_timeout=args.connect_timeout,
            session_timeout=args.session_timeout,
            attempts=3,
            event_log=event_log,
        )
        sender = None
        receiver = None
        try:
            print(f"[session] created: {created.get('session_id', 'unknown')}", flush=True)
            sender = asyncio.create_task(
                send_realtime_inputs(
                    websocket,
                    canvas,
                    camera,
                    audio_buffer,
                    stop_event,
                    event_log=event_log,
                ),
                name="realtime-sender",
            )
            receiver = asyncio.create_task(
                receive_realtime_outputs(
                    websocket,
                    stop_event,
                    canvas,
                    speech_queue,
                    verbose=args.verbose,
                    event_log=event_log,
                ),
                name="realtime-receiver",
            )
            done, pending = await asyncio.wait(
                {sender, receiver}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                task.result()
            if not receiver.done():
                close_message = {"type": "session.close", "reason": "user_stop"}
                await websocket.send(json.dumps(close_message, ensure_ascii=False))
                if event_log is not None:
                    event_log.record_message("gateway.send", close_message)
                try:
                    await asyncio.wait_for(receiver, timeout=2.0)
                except asyncio.TimeoutError:
                    receiver.cancel()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            for task in (sender, receiver):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (sender, receiver) if task is not None),
                return_exceptions=True,
            )
            await websocket.close()
    finally:
        stop_event.set()
        if microphone is not None:
            microphone.close()
        canvas.close()
        if camera is not None:
            camera.close()
        if canvas.error is not None:
            raise canvas.error


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send microphone audio plus webcam video with a character inset to "
            "MiniCPM-o, then apply streamed tag commands."
        )
    )
    parser.add_argument(
        "--url",
        default="https://localhost:8006",
        help="Gateway base URL or full realtime WebSocket URL",
    )
    parser.add_argument(
        "--sprite-dir", type=Path, default=Path("tachie/sanae"), help="PNG directory"
    )
    parser.add_argument("--initial-sprite", default="normal", help="initial PNG stem")
    parser.add_argument("--canvas-width", type=int, default=1280)
    parser.add_argument("--canvas-height", type=int, default=720)
    parser.add_argument(
        "--jpeg-quality", type=int, default=80, help="JPEG quality from 1 to 100"
    )
    parser.add_argument(
        "--prompt", help="override the generated streaming-command system prompt"
    )
    parser.add_argument("--character-name", default="早苗")
    parser.add_argument(
        "--character-persona",
        default="自然、敏锐、友善，像真实伙伴一样回应，但不要无意义地重复说话。",
    )
    parser.add_argument("--input-device", help="sounddevice input device id or name")
    parser.add_argument("--no-mic", action="store_true", help="send silence instead")
    parser.add_argument("--camera-device", type=int, default=0, help="OpenCV camera index")
    parser.add_argument(
        "--no-camera",
        action="store_true",
        help="send only the white character canvas",
    )
    parser.add_argument("--no-preview", action="store_true", help="hide canvas preview")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="accept the localhost self-signed TLS certificate",
    )
    parser.add_argument("--verbose", action="store_true", help="print server metrics")
    parser.add_argument(
        "--log-file",
        type=Path,
        help="JSONL frontend log path (default: logs/frontend-<timestamp>.jsonl)",
    )
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--session-timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    if not 1 <= args.jpeg_quality <= 100:
        parser.error("--jpeg-quality must be between 1 and 100")
    if args.canvas_width <= 0 or args.canvas_height <= 0:
        parser.error("canvas dimensions must be positive")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    log_path = args.log_file or Path("logs") / (
        f"frontend-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.jsonl"
    )
    event_log = FrontendEventLogger(log_path)
    print(f"[log] {log_path.resolve()}", flush=True)
    try:
        asyncio.run(run_probe(args, event_log))
    except KeyboardInterrupt:
        print("\n[client] interrupted", flush=True)
        event_log.record("client.interrupted")
        return 130
    except Exception as exc:
        print(f"\n[client] error: {exc}", file=sys.stderr, flush=True)
        event_log.record_exception("client.error", exc)
        return 1
    finally:
        event_log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
