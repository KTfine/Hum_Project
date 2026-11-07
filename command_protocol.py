"""Forgiving incremental parser for compact streamed character commands."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any


DEFAULT_TRANSITION_MS = 350
_PREFIX_RE = re.compile(r"<(speak|move|scale|tachie|rotate|photo|mode):|<blank")
_STARTERS = (
    "<speak:",
    "<move:",
    "<scale:",
    "<tachie:",
    "<rotate:",
    "<photo:",
    "<mode:",
    "<blank>",
)


@dataclass(frozen=True)
class Command:
    kind: str
    params: dict[str, Any]


class StreamingCommandParser:
    """Extract valid commands, optionally adapting untagged speech fragments.

    Strict parsing is the default for callers that require model-authored tags.
    Plain speech never implies an avatar action.
    """

    def __init__(self, max_buffer: int = 4096, *, allow_plain_speech: bool = False) -> None:
        if max_buffer < 16:
            raise ValueError("max_buffer must be at least 16")
        self.max_buffer = max_buffer
        self.allow_plain_speech = allow_plain_speech
        self.plain_speech_count = 0
        self._response_id: str | None = None
        self._buffer = ""
        self._discarding_tag = False

    def feed(self, response_id: str | None, text: str) -> list[Command]:
        if response_id != self._response_id:
            self._buffer = ""
            self._discarding_tag = False
            self._response_id = response_id
        self._buffer += str(text)
        commands: list[Command] = []

        while self._buffer:
            if self._discarding_tag:
                # After an oversized tag, do not speak its remaining parameters.
                nested = _PREFIX_RE.search(self._buffer)
                closing = self._buffer.find(">")
                if nested is not None and (closing < 0 or nested.start() < closing):
                    self._buffer = self._buffer[nested.start():]
                    self._discarding_tag = False
                    continue
                if closing < 0:
                    self._buffer = self._partial_prefix_suffix(self._buffer)
                    break
                self._buffer = self._buffer[closing + 1:]
                self._discarding_tag = False
                continue
            match = _PREFIX_RE.search(self._buffer)
            if match is None:
                if self.allow_plain_speech:
                    opening = self._buffer.find("<")
                    if opening < 0:
                        commands.extend(self._plain_speech(self._buffer))
                        self._buffer = ""
                        break
                    if opening > 0:
                        commands.extend(self._plain_speech(self._buffer[:opening]))
                        self._buffer = self._buffer[opening:]
                    closing = self._buffer.find(">")
                    if closing >= 0:
                        # Unknown angle-bracket commands are never speech.
                        self._buffer = self._buffer[closing + 1:]
                        continue
                    if len(self._buffer) > self.max_buffer:
                        self._discarding_tag = True
                        self._buffer = self._partial_prefix_suffix(self._buffer)
                    break
                self._buffer = self._partial_prefix_suffix(self._buffer)
                break
            if match.start() > 0:
                if self.allow_plain_speech:
                    commands.extend(self._plain_speech(self._buffer[:match.start()]))
                self._buffer = self._buffer[match.start() :]
                match = _PREFIX_RE.match(self._buffer)
                assert match is not None

            kind = match.group(1) or "blank"
            body_start = match.end()
            nested = _PREFIX_RE.search(self._buffer, body_start)
            closing = self._buffer.find(">", body_start)
            if nested is not None and (closing < 0 or nested.start() < closing):
                prefix_text = self._buffer[body_start : nested.start()]
                # `<speak: <move:>` is still a recoverable outer speech tag.
                # With real speech before the nested prefix, prefer resyncing so
                # a missing speech delimiter cannot swallow a following action.
                if kind != "speak" or prefix_text.strip():
                    self._buffer = self._buffer[nested.start() :]
                    continue
            if closing < 0:
                if len(self._buffer) > self.max_buffer:
                    self._buffer = ""
                    self._discarding_tag = self.allow_plain_speech
                break

            closing_run_end = closing + 1
            while (
                closing_run_end < len(self._buffer)
                and self._buffer[closing_run_end] == ">"
            ):
                closing_run_end += 1
            if (
                kind == "speak"
                and closing_run_end == len(self._buffer)
                and closing_run_end == closing + 1
                and not self._buffer[body_start:closing].strip()
            ):
                # An empty-looking speech tag at a chunk boundary may be the
                # first half of `<speak: >>`; wait for one more text fragment.
                break
            # Repeated `>` is ambiguous only for speech: preserve preceding
            # brackets as spoken content there, but treat them as harmless
            # duplicate delimiters for structured commands.
            delimiter = closing_run_end - 1 if kind == "speak" else closing
            body = self._buffer[body_start:delimiter]
            self._buffer = self._buffer[closing_run_end:]

            command = _parse_command(kind, body)
            if command is not None:
                commands.append(command)

        return commands

    def flush(self, response_id: str | None = None) -> list[Command]:
        if response_id is None or response_id == self._response_id:
            self._buffer = ""
            self._discarding_tag = False
            if response_id is not None:
                self._response_id = response_id
        return []

    def _plain_speech(self, text: str) -> list[Command]:
        # A prefix before a valid command may contain an unknown/broken tag.
        # Strip such spans instead of exposing their contents as speech.
        text = re.sub(r"<[^>]*(?:>|$)", "", text)
        if not text.strip():
            return []
        self.plain_speech_count += 1
        return [Command("speak", {"text": text})]

    @staticmethod
    def _partial_prefix_suffix(text: str) -> str:
        limit = min(len(text), max(map(len, _STARTERS)) - 1)
        for length in range(limit, 0, -1):
            suffix = text[-length:]
            if any(starter.startswith(suffix) for starter in _STARTERS):
                return suffix
        return ""


def _parse_command(kind: str, body: str) -> Command | None:
    if kind == "blank":
        return Command("blank", {}) if not body.strip() else None
    if kind == "speak":
        text = body.strip()
        return Command("speak", {"text": text}) if text else None
    if kind == "photo":
        return Command("photo", {"action": "enter"}) if body.strip() == "enter" else None
    if kind == "mode":
        mode = body.strip()
        return Command("mode", {"mode": mode}) if mode in {"guidance", "co-photo"} else None
    if kind == "tachie":
        sprite_id = body.strip()
        if not sprite_id or not re.fullmatch(r"[A-Za-z0-9_.-]+", sprite_id):
            return None
        return Command("tachie", {"sprite_id": sprite_id})

    parts = [part.strip() for part in body.split(",")]
    if not parts or parts[0] not in {"to", "by"}:
        return None
    mode = parts[0]
    values: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            return None
        key, value = (piece.strip() for piece in part.split("=", 1))
        if not key or not value or key in values:
            return None
        values[key] = value

    ms = _finite_number(values.pop("ms", str(DEFAULT_TRANSITION_MS)))
    if ms is None or not ms.is_integer() or not 0 <= ms <= 3000:
        return None
    params: dict[str, Any] = {"mode": mode, "ms": int(ms)}

    if kind == "move":
        allowed = {"x", "y"} if mode == "to" else {"dx", "dy"}
        if not values or not set(values).issubset(allowed):
            return None
        for key, raw in values.items():
            value = _finite_number(raw)
            if value is None:
                return None
            if mode == "to" and not 0.0 <= value <= 1.0:
                return None
            if mode == "by" and not -1.0 <= value <= 1.0:
                return None
            params[key] = value
        return Command(kind, params)

    if kind == "scale":
        expected = "value" if mode == "to" else "factor"
        if set(values) != {expected}:
            return None
        value = _finite_number(values[expected])
        if value is None or not 0.1 <= value <= 3.0:
            return None
        params[expected] = value
        return Command(kind, params)

    if kind == "rotate":
        if set(values) != {"value"}:
            return None
        value = _finite_number(values["value"])
        if value is None or not -180.0 <= value <= 180.0:
            return None
        params["value"] = value
        return Command(kind, params)

    return None


def _finite_number(raw: str) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None
