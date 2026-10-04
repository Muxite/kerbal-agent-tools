"""Parser for KSP's ConfigNode text format (.cfg, .craft, .sfs, ModuleManager.ConfigCache).

The format is a tree of nodes. Each node has an ordered list of ``key = value`` pairs
(keys may repeat) and child nodes:

    PART
    {
        name = foo
        MODULE { name = ModuleEngines }
    }

KSP strips ``//`` comments everywhere, and braces may share a line with other content.
Files with no top-level node name (``.craft``) parse into an unnamed root node.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class ConfigNode:
    name: str = ""
    values: list[tuple[str, str]] = field(default_factory=list)
    nodes: list["ConfigNode"] = field(default_factory=list)

    def get(self, key: str, default: str | None = None) -> str | None:
        for k, v in self.values:
            if k == key:
                return v
        return default

    def get_all(self, key: str) -> list[str]:
        return [v for k, v in self.values if k == key]

    def node(self, name: str) -> "ConfigNode | None":
        for n in self.nodes:
            if n.name == name:
                return n
        return None

    def nodes_named(self, name: str) -> list["ConfigNode"]:
        return [n for n in self.nodes if n.name == name]

    def walk(self) -> Iterator["ConfigNode"]:
        """Yield this node and every descendant, depth first."""
        yield self
        for n in self.nodes:
            yield from n.walk()


def _tokens(text: str) -> Iterator[str]:
    """Yield logical lines, splitting out ``{`` and ``}`` as their own tokens."""
    for raw in text.splitlines():
        i = raw.find("//")
        line = raw[:i] if i >= 0 else raw
        if "{" not in line and "}" not in line:
            line = line.strip()
            if line:
                yield line
            continue
        start = 0
        for j, ch in enumerate(line):
            if ch in "{}":
                part = line[start:j].strip()
                if part:
                    yield part
                yield ch
                start = j + 1
        part = line[start:].strip()
        if part:
            yield part


def loads(text: str) -> ConfigNode:
    """Parse ConfigNode text into an unnamed root node."""
    if text.startswith("﻿"):
        text = text[1:]
    root = ConfigNode()
    stack = [root]
    pending: str | None = None  # a bare word that may be the name of the next node

    for tok in _tokens(text):
        if tok == "{":
            child = ConfigNode(pending or "")
            stack[-1].nodes.append(child)
            stack.append(child)
            pending = None
        elif tok == "}":
            if pending is not None:
                stack[-1].values.append((pending, ""))
                pending = None
            if len(stack) > 1:  # tolerate stray closing braces like KSP does
                stack.pop()
        else:
            if pending is not None:
                stack[-1].values.append((pending, ""))
                pending = None
            eq = tok.find("=")
            if eq >= 0:
                stack[-1].values.append((tok[:eq].strip(), tok[eq + 1 :].strip()))
            else:
                pending = tok
    if pending is not None:
        stack[-1].values.append((pending, ""))
    return root


def load(path: str | Path) -> ConfigNode:
    return loads(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
