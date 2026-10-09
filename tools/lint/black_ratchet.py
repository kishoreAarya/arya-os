#!/usr/bin/env python3
"""Black formatting ratchet — the Phase 2 lint policy for Black.

The repository carries pre-existing Black formatting debt (223 files
when this policy was introduced). Reformatting them all in one commit
was ruled out (unreviewable mechanical churn), but silently dropping
the Black gate would let NEW debt accumulate. This ratchet is the
explicit middle ground:

  1. Black MUST accept every file NOT listed in the manifest
     (black-debt-manifest.txt, next to this script). A new or newly
     drifted file fails CI: format it (``black <paths>``).
  2. Manifest entries that Black now accepts (or that no longer
     exist) also fail CI: shrink the manifest. The ratchet only
     tightens — debt may only ever leave the list.

The manifest is regenerated only by deleting entries (never adding
them). To clear debt incrementally: run ``black`` on a manifest file,
delete its line, and let the diff show the reformatting.

Black is version-pinned in pyproject.toml (dev extra) — the manifest
is only meaningful against that exact version.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("black-debt-manifest.txt")
WOULD_REFORMAT = re.compile(r"^would reformat (.+)$", re.MULTILINE)


def black_failing(target: str) -> set[str]:
    proc = subprocess.run(
        ["black", "--check", target],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"black itself failed (exit {proc.returncode})")
    text = proc.stdout + proc.stderr
    out = set()
    for m in WOULD_REFORMAT.findall(text):
        p = Path(m)
        if not p.is_absolute():
            p = REPO_ROOT / p
        out.add(p.resolve().relative_to(REPO_ROOT).as_posix())
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write(f"usage: {Path(argv[0]).name} <path>\n")
        return 2
    target = argv[1]

    if not MANIFEST.is_file():
        sys.stderr.write(f"missing manifest: {MANIFEST}\n")
        return 2
    manifest = {
        line.strip()
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    failing = black_failing(target)

    new_debt = sorted(failing - manifest)
    stale = sorted(manifest - failing)

    if new_debt:
        print("NEW Black debt — these files are not in the manifest and fail `black --check`:")
        for p in new_debt:
            print(f"  {p}")
        print("Format them with: uv run black <paths>   (adding entries to the manifest is NOT allowed)")
        return 1

    if stale:
        print("STALE manifest entries — these now pass `black --check` (or no longer exist):")
        for p in stale:
            print(f"  {p}")
        print("The ratchet only tightens: remove these lines from tools/lint/black-debt-manifest.txt")
        return 1

    print(f"Black ratchet holds: {len(manifest)} known-debt files, 0 new, 0 stale.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
