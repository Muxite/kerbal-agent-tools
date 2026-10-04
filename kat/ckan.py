"""Thin wrapper around the ckan.exe command line (always --headless)."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from .instance import find_ckan_exe

# CKAN progress fragments, e.g. "12.3 MiB left - 40%" or "40.7 MiB/sec - 133.3 MiB (3 sec) left - 78%".
_PROGRESS = re.compile(r"[ \t]*(?:[\d.]+ [KMG]?i?B/sec - )?[\d.]+ [KMG]?i?B(?: \(\d+ sec\))? left - \d+%[ \t]*\n?")

# Subcommands that change the install or CKAN's config. Everything else is treated as read-only.
MUTATING = {"install", "remove", "upgrade", "replace", "import", "update", "mark", "dedup"}
# Command groups that are read-only only for these sub-subcommands (e.g. "filter list").
GROUPS = {"filter", "repo", "instance", "compat", "cache", "authtoken", "stability"}
READONLY_SUB = {"list", "show", "available", "known"}


@dataclass
class CkanResult:
    args: list[str]
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run(args: list[str], timeout: int = 1800) -> CkanResult:
    exe = find_ckan_exe()
    cmd = [str(exe), *args]
    if args and args[0] in {"install", "remove", "upgrade", "replace", "update", "import"} and "--headless" not in args:
        cmd.insert(2, "--headless")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    out = _PROGRESS.sub("", proc.stdout + proc.stderr)
    return CkanResult(cmd[1:], proc.returncode, out.strip())


def is_mutating(args: list[str]) -> bool:
    if not args:
        return False
    if args[0] in MUTATING:
        return True
    if args[0] in GROUPS:
        return len(args) < 2 or args[1] not in READONLY_SUB
    return False
