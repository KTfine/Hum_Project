#!/usr/bin/env python3
"""Apply the reviewed patches to the pinned Demo, without resetting local files."""
import argparse
from pathlib import Path
import subprocess


PATCH_ROOT = Path(__file__).resolve().parents[1] / 'patches'
PATCHES = ('gateway-internal-host.patch', 'duplex-session-options.patch')


def git_apply(upstream, patch, *flags):
    return subprocess.run(['git', 'apply', *flags, str(patch)], cwd=upstream,
                          capture_output=True, text=True, encoding='utf-8', errors='replace')


def apply_patches(upstream, check_only=False):
    planned = []
    for name in PATCHES:
        patch = PATCH_ROOT / name
        if git_apply(upstream, patch, '--reverse', '--check').returncode == 0:
            print(f'already applied: {name}')
            continue
        check = git_apply(upstream, patch, '--check')
        if check.returncode:
            raise RuntimeError(f'Patch does not match the pinned source: {name}\n{check.stderr}')
        planned.append(patch)
    for patch in planned:
        if check_only:
            print(f'can apply: {patch.name}')
        else:
            applied = git_apply(upstream, patch)
            if applied.returncode:
                raise RuntimeError(f'Cannot apply {patch.name}: {applied.stderr}')
            print(f'applied: {patch.name}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('upstream', type=Path)
    parser.add_argument('--check', action='store_true', help='validate without changing files')
    args = parser.parse_args()
    apply_patches(args.upstream.resolve(strict=True), check_only=args.check)
