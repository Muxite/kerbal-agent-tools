"""Answers to "what does this craft need?" and "what breaks if I remove this mod?". Read-only."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .craft import Craft, find_crafts, parse_craft
from .instance import Instance
from .partindex import GameDataIndex, build_index
from .registry import Registry
from .save import Vessel, load_vessels

LIVE_SAVES = ("persistent.sfs",)
DEFAULT_ALT_SAVES = ("quicksave.sfs",)


@dataclass
class Context:
    inst: Instance
    reg: Registry
    idx: GameDataIndex
    save_dir: Path
    crafts: list[Craft] = field(default_factory=list)
    vessels: dict[str, list[Vessel]] = field(default_factory=dict)  # sfs filename -> vessels


def load_context(inst: Instance, save: str, all_saves: bool = False, rebuild: bool = False,
                 with_crafts: bool = True, with_vessels: bool = True) -> Context:
    reg = Registry.load(inst.registry_path)
    ctx = Context(inst, reg, build_index(inst, reg, rebuild=rebuild), inst.save_dir(save))
    if with_crafts:
        ctx.crafts = [parse_craft(p) for p in find_crafts(ctx.save_dir)]
    if with_vessels:
        files = sorted(ctx.save_dir.glob("*.sfs")) if all_saves else [
            ctx.save_dir / f for f in LIVE_SAVES + DEFAULT_ALT_SAVES if (ctx.save_dir / f).exists()
        ]
        for f in files:
            ctx.vessels[f.name] = load_vessels(f)
    return ctx


def _rel(ctx: Context, p: Path) -> str:
    return p.relative_to(ctx.save_dir).as_posix()


# ---- per craft ------------------------------------------------------------------------------

def craft_deps(ctx: Context, craft: Craft) -> dict:
    """Hard dependencies (mods providing parts), plus parts no installed mod provides."""
    by_mod: dict[str, list[str]] = defaultdict(list)
    missing: list[str] = []
    for part in sorted(craft.parts):
        info = ctx.idx.parts.get(part)
        if info is None:
            missing.append(part)
        else:
            by_mod[info.mod].append(part)
    resources = {r: ctx.idx.resources.get(r, "unknown") for r in sorted(craft.resources)}
    plugin_mods: dict[str, list[str]] = defaultdict(list)
    for mod_name in sorted(craft.modules):
        for owner in ctx.idx.module_owner.get(mod_name, []):
            if owner != "stock:KSP":
                plugin_mods[owner].append(mod_name)
    return {
        "craft": _rel(ctx, craft.path),
        "name": craft.name,
        "facility": craft.facility,
        "part_count": craft.part_count,
        "mods": {m: sorted(ps) for m, ps in sorted(by_mod.items())},
        "missing_parts": missing,
        "plugin_mods": {m: ms for m, ms in sorted(plugin_mods.items()) if m not in by_mod},
        "resources": resources,
    }


# ---- modules ----------------------------------------------------------------------------------

def modules_lost(ctx: Context, removing: set[str]) -> set[str]:
    """PartModules whose every known provider is being removed."""
    return {m for m, owners in ctx.idx.module_owner.items() if owners and set(owners) <= removing}


def modules_provided(ctx: Context, mod: str) -> set[str]:
    return {m for m, owners in ctx.idx.module_owner.items() if mod in owners}


def _module_usage(ctx: Context, modules: set[str]) -> dict:
    crafts = [{"craft": _rel(ctx, c.path), "name": c.name, "modules": sorted(modules & set(c.modules))}
              for c in ctx.crafts if modules & set(c.modules)]
    vessels = {}
    for sfs, vs in ctx.vessels.items():
        rows = [{"vessel": v.name, "situation": v.situation, "body": v.body,
                 "modules": sorted(modules & set(v.modules))} for v in vs if modules & set(v.modules)]
        if rows:
            vessels[sfs] = rows
    return {"crafts": crafts, "vessels": vessels}


# ---- usage ----------------------------------------------------------------------------------

def _usage(ctx: Context, part_names: set[str]) -> dict:
    crafts = []
    for c in ctx.crafts:
        hit = sorted(part_names & set(c.parts))
        if hit:
            crafts.append({"craft": _rel(ctx, c.path), "name": c.name, "parts": hit})
    vessels: dict[str, list[dict]] = {}
    for sfs, vs in ctx.vessels.items():
        rows = []
        for v in vs:
            hit = sorted(part_names & set(v.parts))
            if hit:
                rows.append({"vessel": v.name, "type": v.type, "situation": v.situation,
                             "body": v.body, "parts": hit,
                             "lost_parts": sum(v.parts[p] for p in hit), "total_parts": v.part_count})
        if rows:
            vessels[sfs] = rows
    return {"crafts": crafts, "vessels": vessels}


def mod_usage(ctx: Context, mods: list[str]) -> dict:
    parts = {p.name for p in ctx.idx.parts_of(set(mods))}
    return {"mods": mods, "parts_provided": len(parts), **_usage(ctx, parts)}


def _names_for_needs(ctx: Context, mods: set[str]) -> set[str]:
    """Names a :NEEDS[...] clause could use to refer to these mods: ids, GameData folders, DLL names."""
    names = {m.lower() for m in mods}
    for m in mods:
        for f in ctx.reg.modules[m].files:
            parts = f.split("/")
            if len(parts) >= 2 and parts[0] == "GameData":
                names.add(parts[1].lower())
            if f.lower().endswith(".dll"):
                names.add(Path(f).stem.lower())
    # a folder shared with a mod that stays (e.g. a vendor folder) is not evidence of anything
    for folder, owner in ctx.idx.folder_owner.items():
        if owner not in mods:
            names.discard(folder.lower())
    return names


def removal_impact(ctx: Context, requested: list[str]) -> dict:
    sim = ctx.reg.removal_set(requested)
    removing = set(sim["requested"]) | set(sim["broken_dependents"]) | set(sim["orphaned_auto"])
    parts = ctx.idx.parts_of(removing)
    usage = _usage(ctx, {p.name for p in parts})

    needs_names = _names_for_needs(ctx, removing)
    patched_by = {
        owner: sorted(n for n in toks if n.lower() in needs_names)
        for owner, toks in ctx.idx.needs.items()
        if owner not in removing and any(n.lower() in needs_names for n in toks)
    }

    lost = modules_lost(ctx, removing)
    # Hard: other mods' parts whose own definition needs a lost module (they stay, half-working).
    other_parts = sorted(p.name for p in ctx.idx.parts.values()
                         if p.mod not in removing and lost & set(p.own_modules))
    degraded_usage = _usage(ctx, set(other_parts))
    # Soft: modules the removed mods' own patches added to other parts; they vanish with the patch.
    mod_usage_ = _module_usage(ctx, lost)

    live_hits = {k: v for k, v in usage["vessels"].items() if k in LIVE_SAVES}
    if live_hits:
        verdict = "BREAKS_VESSELS"
    elif usage["crafts"] or usage["vessels"]:
        verdict = "BREAKS_CRAFT"
    elif degraded_usage["crafts"] or degraded_usage["vessels"]:
        verdict = "DEGRADES"
    else:
        verdict = "SAFE"

    return {
        "verdict": verdict,
        "removal_set": sim,
        "parts_provided": {m: [p.name for p in parts if p.mod == m] for m in sorted(removing)},
        "usage": usage,
        "modules_lost": sorted(lost),
        "other_mods_parts_losing_modules": other_parts,
        "degraded_part_usage": degraded_usage,
        "module_usage": mod_usage_,
        "patches_referencing": patched_by,
        "index_source": ctx.idx.source,
        "notes": _notes(ctx, removing),
    }


def _notes(ctx: Context, removing: set[str]) -> list[str]:
    notes = []
    if ctx.idx.source == "raw-scan":
        notes.append("ModuleManager.ConfigCache missing; parts created by MM copy patches are not indexed. "
                     "Launch KSP once to regenerate it for a complete answer.")
    no_signal = [m for m in sorted(removing) if not ctx.idx.parts_of({m}) and not modules_provided(ctx, m)]
    if no_signal:
        notes.append("No parts or part modules (visual/config/UI mods), so save usage can't measure their value: "
                     + ", ".join(no_signal))
    return notes


# ---- candidates -----------------------------------------------------------------------------

def unused_mods(ctx: Context) -> dict:
    """Classify every CKAN mod by whether the save actually uses what it provides.

    in_use      its parts are used, or used parts of other mods are defined with its modules
    behaviour   only its patch-added modules show up in crafts/vessels (life support, recolouring,
                gameplay systems): removing it drops that behaviour, nothing breaks; judge by what it does
    required    nothing used, but another mod depends on it (CKAN depends, or other mods' parts
                are defined with its modules)
    candidates  provides parts/modules, none used, nothing needs it -> removal candidates
    no_signal   no parts or modules (visuals, UI, configs): not judged
    """
    used_parts: set[str] = set()
    used_modules: set[str] = set()
    for c in ctx.crafts:
        used_parts |= set(c.parts)
        used_modules |= set(c.modules)
    for vs in ctx.vessels.values():
        for v in vs:
            used_parts |= set(v.parts)
            used_modules |= set(v.modules)

    parts_by_mod: dict[str, list[str]] = defaultdict(list)
    for p in ctx.idx.parts.values():
        parts_by_mod[p.mod].append(p.name)

    out: dict[str, list] = {"in_use": [], "behaviour": [], "required": [], "candidates": [], "no_signal": []}
    for mod in sorted(ctx.reg.modules):
        parts = parts_by_mod.get(mod, [])
        mods_provided = modules_provided(ctx, mod)
        sole = {m for m in mods_provided if ctx.idx.module_owner[m] == [mod]}
        needing = sorted(p.name for p in ctx.idx.parts.values() if p.mod != mod and sole & set(p.own_modules))
        row = {"mod": mod, "parts": len(parts), "parts_used": len(used_parts & set(parts)),
               "modules": len(mods_provided), "modules_used": sorted(used_modules & mods_provided),
               "parts_of_other_mods_needing_it": needing,
               "used_parts_of_other_mods_needing_it": sorted(used_parts & set(needing)),
               "auto_installed": ctx.reg.modules[mod].auto_installed,
               "dependents": sorted(ctx.reg.dependents(mod))}
        if not parts and not mods_provided:
            out["no_signal"].append(row)
        elif row["parts_used"] or row["used_parts_of_other_mods_needing_it"]:
            out["in_use"].append(row)
        elif row["modules_used"]:
            out["behaviour"].append(row)
        elif row["dependents"] or needing:
            out["required"].append(row)
        else:
            out["candidates"].append(row)
    out["index_source"] = ctx.idx.source
    return out
