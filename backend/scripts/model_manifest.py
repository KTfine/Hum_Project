#!/usr/bin/env python3
"""Create and verify a pinned local MiniCPM-o snapshot manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MANIFEST_NAME = ".model_manifest.json"
IGNORED_NAMES = {MANIFEST_NAME, ".model_revision"}
REQUIRED_FILES = {
    "config.json",
    "assets/token2wav/campplus.onnx",
    "assets/token2wav/flow.pt",
    "assets/token2wav/flow.yaml",
    "assets/token2wav/hift.pt",
    "assets/token2wav/speech_tokenizer_v2_25hz.onnx",
    "model-00001-of-00004.safetensors",
    "model-00002-of-00004.safetensors",
    "model-00003-of-00004.safetensors",
    "model-00004-of-00004.safetensors",
    "model.safetensors.index.json",
}


def snapshot_files(root: Path) -> dict[str, int]:
    files: dict[str, int] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or relative.parts[0] == ".cache" or path.name in IGNORED_NAMES:
            continue
        files[relative.as_posix()] = path.stat().st_size
    return files


def validate_required(files: dict[str, int]) -> None:
    missing = sorted(REQUIRED_FILES.difference(files))
    if missing:
        raise ValueError("missing required model files: " + ", ".join(missing))


def build_manifest(root: Path, repo: str, revision: str) -> dict[str, object]:
    files = snapshot_files(root)
    validate_required(files)
    return {"repo": repo, "revision": revision, "files": files}


def write_manifest(root: Path, repo: str, revision: str) -> None:
    manifest = build_manifest(root, repo, revision)
    target = root / MANIFEST_NAME
    temporary = root / f"{MANIFEST_NAME}.tmp"
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)


def verify_manifest(root: Path, repo: str, revision: str) -> None:
    path = root / MANIFEST_NAME
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("repo") != repo or manifest.get("revision") != revision:
        raise ValueError("model manifest repository or revision does not match the pin")
    expected = manifest.get("files")
    if not isinstance(expected, dict):
        raise ValueError("model manifest has no file table")
    validate_required(expected)
    actual = snapshot_files(root)
    if actual != expected:
        missing = sorted(set(expected).difference(actual))
        extra = sorted(set(actual).difference(expected))
        changed = sorted(name for name in set(actual).intersection(expected) if actual[name] != expected[name])
        raise ValueError(f"model snapshot mismatch: missing={missing}, extra={extra}, changed={changed}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("write", "verify"))
    parser.add_argument("root", type=Path)
    parser.add_argument("repo")
    parser.add_argument("revision")
    args = parser.parse_args()
    if args.action == "write":
        write_manifest(args.root, args.repo, args.revision)
    else:
        verify_manifest(args.root, args.repo, args.revision)


if __name__ == "__main__":
    main()
