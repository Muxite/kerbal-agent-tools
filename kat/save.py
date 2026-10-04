"""Parse .sfs save files: vessels and their parts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import cfgnode
from .partindex import normalize_part_name

# ORBIT REF indices for the stock bodies (Kopernicus systems add more; unknown REFs are kept as "ref:N").
STOCK_BODIES = {
    0: "Sun", 1: "Kerbin", 2: "Mun", 3: "Minmus", 4: "Moho", 5: "Eve", 6: "Duna", 7: "Ike",
    8: "Jool", 9: "Laythe", 10: "Vall", 11: "Bop", 12: "Tylo", 13: "Gilly", 14: "Pol", 15: "Dres", 16: "Eeloo",
}


@dataclass
class Vessel:
    name: str
    type: str
    situation: str
    body: str
    landed_at: str
    lat: float | None
    lon: float | None
    sma: float | None
    ecc: float | None
    crew: list[str] = field(default_factory=list)
    parts: Counter = field(default_factory=Counter)
    modules: Counter = field(default_factory=Counter)

    @property
    def part_count(self) -> int:
        return sum(self.parts.values())


def _f(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def parse_vessels(root: cfgnode.ConfigNode) -> list[Vessel]:
    game = root.node("GAME") or root
    fs = game.node("FLIGHTSTATE")
    if fs is None:
        return []
    out: list[Vessel] = []
    for v in fs.nodes_named("VESSEL"):
        orbit = v.node("ORBIT")
        ref = orbit.get("REF") if orbit else None
        body = STOCK_BODIES.get(int(ref), f"ref:{ref}") if ref and ref.isdigit() else ""
        vessel = Vessel(
            name=v.get("name", ""),
            type=v.get("type", ""),
            situation=v.get("sit", ""),
            body=body,
            landed_at=v.get("landedAt", ""),
            lat=_f(v.get("lat")),
            lon=_f(v.get("lon")),
            sma=_f(orbit.get("SMA")) if orbit else None,
            ecc=_f(orbit.get("ECC")) if orbit else None,
        )
        for p in v.nodes_named("PART"):
            if p.get("name"):
                vessel.parts[normalize_part_name(p.get("name"))] += 1
            for m in p.nodes_named("MODULE"):
                if m.get("name"):
                    vessel.modules[m.get("name")] += 1
            vessel.crew.extend(c for c in p.get_all("crew") if c)
        out.append(vessel)
    return out


def load_vessels(sfs: str | Path) -> list[Vessel]:
    return parse_vessels(cfgnode.load(sfs))
