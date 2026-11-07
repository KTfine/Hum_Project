# Streaming Command Protocol Implementation Plan

> 历史档案（2026-10-22），不作为当前实现或 AI 执行要求。普通文字适配、模式重建及指导画面后来均有变化；当前行为见 [模式与提示词](../modes-and-prompts.md)。

**Goal:** Replace JSONL controls with a forgiving streamed tag protocol and send webcam imagery with a character-state inset once per second.

**Architecture:** A focused `command_protocol.py` module incrementally extracts and validates commands. The existing realtime client translates commands into independent controller lanes, captures the newest webcam frame, composites the character inset, and keeps the existing continuous WebSocket transport.

**Tech Stack:** Python 3, asyncio, OpenCV, NumPy, unittest, websockets, sounddevice

**Spec:** `2026-10-22-streaming-command-protocol-design.md`

## Global Constraints

- Maintain one continuous WebSocket session and one-second `input.append` cadence.
- Parse and dispatch a command immediately when its recoverable closing `>` arrives.
- Silently discard unrecoverable or invalid model output.
- Do not hard-code photography guidance; follow the user's current instructions.
- Preserve sprites, API documentation, logs, project notes, and unrelated scripts.

## Review Focus

- A known tag split at every possible character boundary must emit exactly once after completion.
- Random prose and unknown tags between valid commands must not block later valid commands.
- Numeric NaN, infinity, missing values, and out-of-range values must be skipped without corrupting state.
- Camera read failure after startup must not reuse unbounded stale frames or crash the receiver task.
- Rapid relative movements during an unfinished animation must accumulate from the latest target.

---

### Task 1: Forgiving Streaming Command Parser

**Files:**
- Create: `command_protocol.py`
- Modify: `tests/test_realtime_av_test.py`

**Interfaces:**
- Produces: `Command(kind: str, params: dict[str, object])`
- Produces: `StreamingCommandParser.feed(response_id: str | None, text: str) -> list[Command]`
- Produces: `StreamingCommandParser.flush(response_id: str | None = None) -> list[Command]`

- [ ] Add failing tests for split commands, multiple commands, doubled closing brackets, nested-prefix resynchronization, unknown text, invalid numbers, overlong input, and response changes.
- [ ] Run the parser tests and confirm they fail because the new module does not exist.
- [ ] Implement bounded incremental scanning and command-specific validation in `command_protocol.py`.
- [ ] Run parser tests and confirm all pass.

### Task 2: Prompt Protocol and User-Directed Photography Observation

**Files:**
- Modify: `prompt.py`
- Modify: `tests/test_prompt.py`

**Interfaces:**
- Produces: `STREAMING_COMMAND_PROMPT: str`, formatted with the existing runtime placeholders.

- [ ] Replace JSON assertions with failing assertions for every tag form, blank behavior, camera/inset distinction, and user-directed photography guidance without fixed aesthetic rules.
- [ ] Run prompt tests and confirm failure against the JSON prompt.
- [ ] Replace the prompt with the compact tag protocol and strict tag-only output requirements.
- [ ] Run prompt tests and confirm all pass.

### Task 3: Independent Control Lanes and Speech FIFO

**Files:**
- Modify: `realtime_av_test.py`
- Modify: `tests/test_realtime_av_test.py`

**Interfaces:**
- Consumes: `Command` from Task 1.
- Produces: `SpriteController.apply_command(command: Command, now: float | None = None) -> SpriteState | None`.
- Produces: `SpeechQueue.enqueue(text: str) -> None` and `SpeechQueue.pop_next() -> str | None`.

- [ ] Add failing tests for absolute retargeting, relative target accumulation, concurrent position/scale/rotation state, tachie geometry preservation, blank no-op, and speech FIFO.
- [ ] Run the controller tests and confirm failure.
- [ ] Implement command translation while retaining the existing interpolation renderer.
- [ ] Run controller tests and confirm all pass.

### Task 4: Webcam Capture and Composite Model Frame

**Files:**
- Modify: `realtime_av_test.py`
- Modify: `tests/test_realtime_av_test.py`

**Interfaces:**
- Produces: `CameraSource(device_index: int)` with `start()`, `latest_frame()`, and `close()`.
- Produces: `compose_model_frame(camera_frame: np.ndarray, character_frame: np.ndarray, inset_ratio: float = 0.28) -> np.ndarray`.

- [ ] Add failing tests for aspect-preserving inset placement, white inset backing, camera-frame immutability, and missing camera-frame handling.
- [ ] Run composition tests and confirm failure.
- [ ] Implement newest-frame capture and upper-right character inset composition.
- [ ] Run composition tests and a no-device rendering smoke test.

### Task 5: Realtime Integration and Silent Recovery

**Files:**
- Modify: `realtime_av_test.py`
- Modify: `tests/test_realtime_av_test.py`

**Interfaces:**
- Consumes: parser, commands, camera, canvas, and speech queue from Tasks 1-4.
- Produces: immediate command dispatch from streamed text deltas and composite JPEG upload once per second.

- [ ] Add failing integration tests proving complete tags dispatch before `listen`, malformed output produces no console error, `listen` is a no-op, and each video tick uses a composite frame.
- [ ] Run integration tests and confirm failure.
- [ ] Replace JSON parsing/event handling, wire camera lifecycle, add camera CLI flags, and retain structured frontend logs.
- [ ] Run integration tests and confirm all pass.

### Task 6: Remove Superseded Protocol Code and Verify

**Files:**
- Modify: `realtime_av_test.py`
- Modify: `README.md`
- Modify: `tests/test_realtime_av_test.py`
- Modify: `tests/test_prompt.py`

**Interfaces:**
- Produces: one documented runnable command and no live JSON-control code paths.

- [ ] Remove `JsonlEventParser`, JSON control handlers, obsolete JSON tests, and stale README claims.
- [ ] Search for remaining JSONL-control references and verify any remaining JSON is transport/logging only.
- [ ] Run `python -m unittest discover -s tests -v` and require zero failures.
- [ ] Run `python -m py_compile realtime_av_test.py command_protocol.py prompt.py` and require exit code zero.
- [ ] Run a local sprite load/render/composite/JPEG smoke test and require a nonempty JPEG.
