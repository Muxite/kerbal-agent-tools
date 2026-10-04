"""Parse .craft files (VAB/SPH ships and subassemblies)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import cfgnode
from .partindex import normalize_part_name

_PID_SUFFIX = re.compile(r"_\d+$")


def craft_part_name(raw: str) -> str:
    """'sspx-core-375-1_4289248132' -> 'sspx-core-375-1' (strip the persistentId suffix)."""
    return normalize_part_name(_PID_SUFFIX.sub("", raw.strip()))


@dataclass
class Craft:
    path: Path
    name: str
    facility: str  # VAB | SPH | Subassembly
    description: str
    parts: Counter = field(default_factory=Counter)  # part name -> count
    modules: Counter = field(default_factory=Counter)  # PartModule name -> count
    resources: dict[str, float] = field(default_factory=dict)  # resource -> total amount

    @property
    def part_count(self) -> int:
        return sum(self.parts.values())


def parse_craft(path: str | Path) -> Craft:
    path = Path(path)
    root = cfgnode.load(path)
    facility = root.get("type") or ("Subassembly" if "Subassemblies" in path.parts else "")
    craft = Craft(
        path=path,
        name=root.get("ship") or path.stem,
        facility=facility,
        description=(root.get("description") or "").replace("¨", "\n"),
    )
    for part in root.nodes_named("PART"):
        raw = part.get("part") or part.get("name") or ""
        if not raw:
            continue
        craft.parts[craft_part_name(raw)] += 1
        for m in part.nodes_named("MODULE"):
            if m.get("name"):
                craft.modules[m.get("name")] += 1
        for r in part.nodes_named("RESOURCE"):
            try:
                amt = float(r.get("amount") or 0)
            except ValueError:
                amt = 0.0
            name = r.get("name") or "?"
            craft.resources[name] = craft.resources.get(name, 0.0) + amt
    return craft


def find_crafts(save_dir: Path, include_subassemblies: bool = True) -> list[Path]:
    out: list[Path] = []
    ships = save_dir / "Ships"
    for fac in ("VAB", "SPH"):
        d = ships / fac
        if d.is_dir():
            out.extend(sorted(d.rglob("*.craft")))
    if include_subassemblies and (save_dir / "Subassemblies").is_dir():
        out.extend(sorted((save_dir / "Subassemblies").rglob("*.craft")))
    return out
