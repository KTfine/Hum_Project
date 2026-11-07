# Streaming Command Protocol Design

> 历史档案（2026-10-22），不作为当前实现或 AI 执行要求。普通文字适配、模式重建及指导画面后来均有变化；当前行为见 [模式与提示词](../modes-and-prompts.md)。

## Goal

Replace streamed JSONL model output with a compact tag protocol so commands can be dispatched as soon as their closing delimiter arrives. Keep one continuous MiniCPM-o video WebSocket session and send one second of fresh microphone audio plus one current composite video frame per input tick. Add camera observation so the model can give photography guidance only according to the user's instructions, without hard-coded posing or aesthetic rules.

## Model output protocol

The model may emit only these commands:

```text
<speak:text>
<move:to,x=0.35,y=0.95,ms=400>
<move:by,dx=-0.10,dy=0,ms=300>
<scale:to,value=0.8,ms=400>
<scale:by,factor=1.1,ms=300>
<tachie:smile>
<rotate:to,value=10,ms=300>
<rotate:by,value=-5,ms=300>
<blank>
```

`move:to` changes only the axes present. `move:by` adds to the latest target position. `scale:to` sets the scale; `scale:by` multiplies the latest target scale. `tachie` changes only the sprite. Animation duration defaults to 350 ms. `blank` is a no-op and is valid only when there is no useful speech or action.

The prompt describes the camera layout and asks the model to observe pose and expression. It does not prescribe photography rules. The model follows the user's current photography request and otherwise avoids inventing a shooting objective.

## Forgiving incremental parser

The parser consumes arbitrary streamed text fragments. It recognizes known command prefixes and dispatches a command immediately after a recoverable closing `>` arrives. It tolerates whitespace, text outside commands, fragmented commands, repeated angle brackets, and a new known command prefix appearing before the previous malformed command closed.

Recovery rules:

- Text outside recognized commands is silently discarded.
- A new recognized prefix resynchronizes the parser when the current candidate is malformed.
- In a run of closing brackets, the last bracket closes the command and earlier brackets belong to the payload. Thus `<speak: >>` can produce speech containing `>`.
- Empty, unknown, numerically invalid, or incomplete commands are silently skipped.
- An unterminated candidate is retained only up to a small maximum buffer size; overlong data is discarded and scanning resumes.
- No parse warning is printed for malformed model output. Debug logging may record only aggregate skipped-command counters, not noisy per-fragment errors.

## Scheduling

Commands are dispatched as soon as parsed:

- Speech uses one FIFO lane so multiple utterances cannot overlap.
- Position, scale, and rotation use independent animation lanes and run concurrently with speech and each other.
- Sprite changes apply immediately and preserve all geometry.
- A newer absolute command on the same lane retargets from the currently rendered value.
- Relative commands accumulate from the lane's latest target, preventing rapid relative commands from losing movement while an animation is still running.

The first implementation keeps speech as a queued text sink because TTS is out of scope. This interface can later be replaced by a sequential TTS worker without changing the model protocol.

## Visual input

Capture the webcam continuously. For each one-second input tick, use the newest camera frame as the main image and place a small white-backed current-character preview in the upper-right corner. The local preview remains the white character canvas. If the camera cannot be opened, fail clearly at startup unless camera capture was explicitly disabled.

The prompt explicitly distinguishes the real user in the main camera image from the virtual character in the inset. Photography guidance is governed by the user's spoken instructions and conversation context rather than fixed posing rules.

## Session behavior and latency

Maintain one WebSocket session. Every second, send the newest one-second audio block and one composite JPEG. Do not reconnect per tick. `kind=listen` is treated as an implicit no-op. Explicit `<blank>` is accepted but not printed unless verbose logging is enabled.

The shorter protocol and immediate delimiter dispatch reduce text-generation and frontend wait time. They cannot remove backend model inference or unwanted backend TTS work; the client continues requesting text-only output and ignores any unexpected audio.

## Files and cleanup

- Replace the prompt template in `prompt.py`.
- Replace `JsonlEventParser` and JSON event handling in `realtime_av_test.py` with the forgiving tag parser and command scheduler.
- Add webcam capture and composite-frame generation to `realtime_av_test.py`.
- Replace obsolete JSON protocol tests with tag-parser, scheduling, and camera-composition tests.
- Update `README.md` to describe the new protocol and camera options.
- Remove only superseded JSON-parser implementation and obsolete tests. Preserve sprites, API documentation, logs, project notes, and unrelated scripts unless their obsolescence is certain.

## Verification

Automated tests cover split chunks, several commands in one chunk, malformed delimiter recovery, silent skipping, relative accumulation, same-lane retargeting, cross-lane concurrency, sprite geometry preservation, speech FIFO ordering, and camera/inset composition. Run the full unit suite and Python bytecode compilation, then perform a local no-network rendering smoke test.
