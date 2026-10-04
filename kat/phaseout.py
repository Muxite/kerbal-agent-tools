"""Find mods that are *almost* unused, so their last few parts can be swapped out in game.

Effort to phase a mod out = craft files that use it + 2 x live (non-debris) vessels that use it.
Debris is listed but not counted: KSP deletes vessels with missing parts on load, which for debris
is usually what you want anyway.
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from dataclasses import dataclass, field

from .analysis import LIVE_SAVES, Context, _rel, modules_provided
from .partindex import PartInfo, normalize_part_name

DISPOSABLE_TYPES = {"Debris", "SpaceObject", "Flag", "DeployedScienceController", "DeployedSciencePart"}


@dataclass
class UsageMaps:
    part_crafts: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    module_crafts: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # part -> {(sfs, vessel name, type, situation, body)}
    part_vessels: dict[str, set[tuple]] = field(default_factory=lambda: defaultdict(set))
    module_vessels: dict[str, set[tuple]] = field(default_factory=lambda: defaultdict(set))


def usage_maps(ctx: Context) -> UsageMaps:
    u = UsageMaps()
    for c in ctx.crafts:
        rel = _rel(ctx, c.path)
        for p in c.parts:
            u.part_crafts[p].add(rel)
        for m in c.modules:
            u.module_crafts[m].add(rel)
    for sfs, vs in ctx.vessels.items():
        for v in vs:
            key = (sfs, v.name, v.type, v.situation, v.body)
            for p in v.parts:
                u.part_vessels[p].add(key)
            for m in v.modules:
                u.module_vessels[m].add(key)
    return u


def _vessel_row(key: tuple) -> dict:
    sfs, name, vtype, sit, body = key
    return {"save": sfs, "vessel": name, "type": vtype, "situation": sit, "body": body,
            "disposable": vtype in DISPOSABLE_TYPES}


def _part_row(p: PartInfo, u: UsageMaps) -> dict:
    vessels = sorted(u.part_vessels.get(p.name, ()))
    return {"name": p.name, "title": p.title, "mod": p.mod, "category": p.category, "file": p.file,
            "crafts": sorted(u.part_crafts.get(p.name, ())),
            "vessels": [_vessel_row(k) for k in vessels]}


# ---- part lookup ----------------------------------------------------------------------------

def find_parts(ctx: Context, query: str, limit: int = 25) -> list[dict]:
    """Find parts by internal name or in-game title (case-insensitive substring, then fuzzy)."""
    q = query.strip().lower()
    qn = normalize_part_name(q)
    parts = list(ctx.idx.parts.values())
    exact = [p for p in parts if p.name.lower() == qn or p.title.lower() == q]
    sub = [p for p in parts if p not in exact and (q in p.title.lower() or qn in p.name.lower())]
    hits = exact + sorted(sub, key=lambda p: (len(p.title), p.title))
    if not hits:
        titles = {p.title.lower(): p for p in parts}
        hits = [titles[t] for t in difflib.get_close_matches(q, list(titles), n=limit, cutoff=0.6)]
    u = usage_maps(ctx)
    return [_part_row(p, u) for p in hits[:limit]]


# ---- phase-out candidates -------------------------------------------------------------------

def phase_out(ctx: Context, max_effort: int | None = 6, only: list[str] | None = None,
              include_dependents: bool = False) -> list[dict]:
    """Rank mods by the in-game work needed to stop using them.

    Mods whose removal would break other installed mods (libraries like SystemHeat) are skipped
    unless ``include_dependents`` or they're named in ``only``: they can't be phased out alone.
    """
    u = usage_maps(ctx)
    parts_by_mod: dict[str, list[PartInfo]] = defaultdict(list)
    for p in ctx.idx.parts.values():
        parts_by_mod[p.mod].append(p)

    rows = []
    for mod in sorted(only or ctx.reg.modules):
        if mod not in ctx.reg.modules:
            continue
        def used(p: PartInfo) -> bool:
            return p.name in u.part_crafts or p.name in u.part_vessels

        used_parts = [p for p in parts_by_mod.get(mod, []) if used(p)]
        sole_modules = {m for m in modules_provided(ctx, mod) if ctx.idx.module_owner[m] == [mod]}
        # Other mods' parts *defined* with this mod's modules also have to be swapped out.
        dependent_parts = [p for p in ctx.idx.parts.values()
                           if p.mod != mod and sole_modules & set(p.own_modules) and used(p)]
        # Modules this mod's patches add to *other* parts just disappear with it (soft).
        own_part_modules = {m for p in parts_by_mod.get(mod, []) for m in p.own_modules}
        soft_modules = sorted(m for m in sole_modules - own_part_modules
                              if m in u.module_crafts or m in u.module_vessels)
        if not used_parts and not dependent_parts:
            continue  # unused, or only patch-added behaviour: see `unused-mods`

        crafts: set[str] = set()
        vessel_keys: set[tuple] = set()
        for p in used_parts + dependent_parts:
            crafts |= u.part_crafts.get(p.name, set())
            vessel_keys |= u.part_vessels.get(p.name, set())

        vessels = [_vessel_row(k) for k in sorted(vessel_keys)]
        live = [v for v in vessels if v["save"] in LIVE_SAVES and not v["disposable"]]
        effort = len(crafts) + 2 * len(live)
        if max_effort is not None and not only and effort > max_effort:
            continue

        sim = ctx.reg.removal_set([mod])
        if sim["broken_dependents"] and not include_dependents and not only:
            continue
        rows.append({
            "mod": mod,
            "name": ctx.reg.modules[mod].name,
            "effort": effort,
            "parts_total": len(parts_by_mod.get(mod, [])),
            "parts_used": [_part_row(p, u) for p in sorted(used_parts, key=lambda p: p.title)],
            "dependent_parts_used": [{**_part_row(p, u), "via_modules": sorted(sole_modules & set(p.own_modules))}
                                     for p in sorted(dependent_parts, key=lambda p: p.title)],
            "soft_modules": soft_modules,
            "crafts": sorted(crafts),
            "live_vessels": live,
            "disposable_vessels": [v for v in vessels if v["save"] in LIVE_SAVES and v["disposable"]],
            "other_save_vessels": [v for v in vessels if v["save"] not in LIVE_SAVES],
            "breaks_mods": sim["broken_dependents"],
            "also_removed": sim["broken_dependents"] + sim["orphaned_auto"],
        })
    rows.sort(key=lambda r: (r["effort"], len(r["parts_used"]), r["mod"]))
    return rows


def checklist_markdown(rows: list[dict], save: str) -> str:
    """An in-game to-do list: which craft to edit and which vessels to recover, per mod."""
    out = [f"# Phase-out checklist ({save})", "",
           "Edit each craft in the VAB/SPH to swap the listed parts, recover or terminate the live vessels, "
           "then re-run `kat phase-out --mod <mod>` until nothing is left and remove it with `kat remove`.", ""]
    for r in rows:
        out.append(f"## {r['name']} (`{r['mod']}`): effort {r['effort']}")
        if r["also_removed"]:
            out.append(f"_Removing it also removes: {', '.join(r['also_removed'])}_")
        out.append("")
        for p in r["parts_used"] + r["dependent_parts_used"]:
            via = (f", from {p['mod']}; its config uses this mod's {', '.join(p['via_modules'])}"
                   if p["mod"] != r["mod"] else "")
            out.append(f"- **{p['title']}** (`{p['name']}`{via})")
            for c in p["crafts"]:
                out.append(f"  - [ ] edit craft `{c}`")
            for v in p["vessels"]:
                if v["save"] in LIVE_SAVES and not v["disposable"]:
                    out.append(f"  - [ ] vessel **{v['vessel']}** ({v['situation']} {v['body']}): recover or replace")
        if r["soft_modules"]:
            out.append(f"- dropped harmlessly with the mod: {', '.join(r['soft_modules'])}")
        if r["disposable_vessels"]:
            names = sorted({v["vessel"] for v in r["disposable_vessels"]})
            out.append(f"- debris/objects that would simply vanish: {', '.join(names)}")
        out.append("")
    return "\n".join(out)
