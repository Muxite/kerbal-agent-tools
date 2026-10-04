"""`kat` command line. Every command accepts --json (global) for machine-readable output."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import analysis, backup, ckan, phaseout, tagparts
from .instance import Instance, InstanceError, find_instance

console = Console()
SKIP_SAVES = {"training", "scenarios"}


class Ctx:
    def __init__(self, ksp_dir: str | None, save: str | None, as_json: bool):
        self.ksp_dir, self._save, self.json = ksp_dir, save, as_json
        self._inst: Instance | None = None

    @property
    def inst(self) -> Instance:
        if self._inst is None:
            self._inst = find_instance(self.ksp_dir)
        return self._inst

    @property
    def save(self) -> str:
        if self._save:
            return self._save
        env = os.environ.get("KAT_SAVE")
        if env:
            return env
        saves = [d for d in self.inst.saves.iterdir()
                 if d.is_dir() and d.name not in SKIP_SAVES and (d / "persistent.sfs").exists()]
        if not saves:
            raise InstanceError("no saves found; pass --save")
        return max(saves, key=lambda d: (d / "persistent.sfs").stat().st_mtime).name

    def emit(self, data, human=None) -> None:
        if self.json or human is None:
            click.echo(json.dumps(data, indent=2, default=str))
        else:
            human(data)


pass_ctx = click.make_pass_decorator(Ctx)


@click.group()
@click.option("--ksp-dir", envvar="KSP_DIR", help="KSP root (default: first instance in CKAN config).")
@click.option("--save", help="Save folder name (default: $KAT_SAVE or most recently played).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output.")
@click.pass_context
def main(cctx: click.Context, ksp_dir, save, as_json):
    """Tools for agents managing a modded KSP install through CKAN."""
    cctx.obj = Ctx(ksp_dir, save, as_json)


def _table(title: str, cols: list[str], rows: list[list]) -> None:
    t = Table(title=title)
    for i, c in enumerate(cols):
        t.add_column(c, overflow="fold", no_wrap=(i == 0))  # fold, not "…": the Windows console can't print the ellipsis
    for r in rows:
        t.add_row(*[str(x) for x in r])
    console.print(t)


# ---- info -----------------------------------------------------------------------------------

@main.command()
@click.option("--rebuild", is_flag=True, help="Rebuild the GameData index cache.")
@pass_ctx
def info(c: Ctx, rebuild):
    """Instance paths, index source and counts."""
    ctx = analysis.load_context(c.inst, c.save, rebuild=rebuild, with_crafts=False, with_vessels=False)
    data = {
        "ksp_root": str(c.inst.root), "save": c.save, "registry": str(c.inst.registry_path),
        "configcache_present": c.inst.configcache_path.exists(), "index_source": ctx.idx.source,
        "installed_mods": len(ctx.reg.modules), "indexed_parts": len(ctx.idx.parts),
        "indexed_resources": len(ctx.idx.resources),
    }
    c.emit(data, lambda d: [console.print(f"[bold]{k}[/]: {v}") for k, v in d.items()])


@main.command()
@pass_ctx
def mods(c: Ctx):
    """Installed CKAN mods with part counts and reverse dependencies."""
    ctx = analysis.load_context(c.inst, c.save, with_crafts=False, with_vessels=False)
    counts: dict[str, int] = {}
    for p in ctx.idx.parts.values():
        counts[p.mod] = counts.get(p.mod, 0) + 1
    rows = [{"mod": i, "version": m.version, "auto": m.auto_installed, "parts": counts.get(i, 0),
             "dependents": sorted(ctx.reg.dependents(i))} for i, m in sorted(ctx.reg.modules.items())]
    c.emit(rows, lambda rs: _table("Installed mods", ["mod", "version", "auto", "parts", "dependents"],
                                   [[r["mod"], r["version"], "y" if r["auto"] else "", r["parts"],
                                     ", ".join(r["dependents"])] for r in rs]))


# ---- crafts & vessels -----------------------------------------------------------------------

@main.command("craft-deps")
@click.argument("crafts", nargs=-1)
@click.option("--missing-only", is_flag=True, help="Only crafts with parts no installed mod provides.")
@pass_ctx
def craft_deps(c: Ctx, crafts, missing_only):
    """Mods each craft needs. CRAFTS are names or paths; default is every craft in the save."""
    ctx = analysis.load_context(c.inst, c.save, with_vessels=False)
    sel = ctx.crafts
    if crafts:
        wanted = {Path(x).stem.lower() for x in crafts}
        sel = [cr for cr in ctx.crafts if cr.path.stem.lower() in wanted or cr.name.lower() in wanted]
    rows = [analysis.craft_deps(ctx, cr) for cr in sel]
    if missing_only:
        rows = [r for r in rows if r["missing_parts"]]

    def human(rs):
        for r in rs:
            console.print(f"[bold cyan]{r['craft']}[/] ({r['part_count']} parts)")
            for m, ps in r["mods"].items():
                console.print(f"  {m}: {len(ps)} part types")
            if r["missing_parts"]:
                console.print(f"  [red]MISSING[/]: {', '.join(r['missing_parts'])}")
    c.emit(rows, human)


@main.command()
@click.option("--all-saves", is_flag=True, help="Every .sfs in the save folder, not just persistent/quicksave.")
@click.option("--body", help="Filter by body name.")
@pass_ctx
def vessels(c: Ctx, all_saves, body):
    """Vessels in the save (persistent.sfs + quicksave.sfs by default)."""
    ctx = analysis.load_context(c.inst, c.save, all_saves=all_saves, with_crafts=False)
    out = {}
    for sfs, vs in ctx.vessels.items():
        out[sfs] = [{"name": v.name, "type": v.type, "situation": v.situation, "body": v.body,
                     "landed_at": v.landed_at, "lat": v.lat, "lon": v.lon, "sma": v.sma,
                     "parts": v.part_count, "crew": v.crew}
                    for v in vs if not body or v.body.lower() == body.lower()]

    def human(d):
        for sfs, rows in d.items():
            _table(f"{sfs} ({len(rows)} vessels)", ["name", "type", "situation", "body", "parts", "crew"],
                   [[r["name"], r["type"], r["situation"], r["body"], r["parts"], len(r["crew"])] for r in rows])
    c.emit(out, human)


# ---- mod impact -----------------------------------------------------------------------------

def _resolve(ctx, names) -> list[str]:
    out = []
    for n in names:
        ident = ctx.reg.resolve(n)
        if not ident:
            raise click.ClickException(f"'{n}' is not an installed CKAN mod")
        out.append(ident)
    return out


@main.command("mod-usage")
@click.argument("mod_names", nargs=-1, required=True)
@click.option("--all-saves", is_flag=True)
@pass_ctx
def mod_usage(c: Ctx, mod_names, all_saves):
    """Which crafts and vessels use parts from these mods."""
    ctx = analysis.load_context(c.inst, c.save, all_saves=all_saves)
    data = analysis.mod_usage(ctx, _resolve(ctx, mod_names))
    c.emit(data, _print_usage)


def _print_usage(d):
    if "parts_provided" in d:
        console.print(f"parts provided: {d['parts_provided']}")
    for r in d["crafts"]:
        console.print(f"  craft [cyan]{r['craft']}[/]: {', '.join(r['parts'])}")
    for sfs, rows in d["vessels"].items():
        for r in rows:
            console.print(f"  {sfs} vessel [yellow]{r['vessel']}[/] ({r['situation']} {r['body']}): "
                          f"{r['lost_parts']}/{r['total_parts']} parts")


@main.command("removal-impact")
@click.argument("mod_names", nargs=-1, required=True)
@click.option("--all-saves", is_flag=True, help="Also check every quicksave/named save.")
@pass_ctx
def removal_impact(c: Ctx, mod_names, all_saves):
    """Dry run: what `ckan remove MOD...` would take out, and what would break. Changes nothing."""
    ctx = analysis.load_context(c.inst, c.save, all_saves=all_saves)
    data = analysis.removal_impact(ctx, _resolve(ctx, mod_names))
    c.emit(data, _print_impact)


def _print_impact(d):
    colour = {"SAFE": "green", "DEGRADES": "yellow", "BREAKS_CRAFT": "dark_orange", "BREAKS_VESSELS": "red"}[d["verdict"]]
    console.print(f"[bold {colour}]{d['verdict']}[/]")
    rs = d["removal_set"]
    console.print(f"requested: {', '.join(rs['requested'])}")
    if rs["broken_dependents"]:
        console.print(f"[red]also removed (would break)[/]: {', '.join(rs['broken_dependents'])}")
    if rs["orphaned_auto"]:
        console.print(f"[yellow]also removed (orphaned auto-installs)[/]: {', '.join(rs['orphaned_auto'])}")
    for m, ps in d["parts_provided"].items():
        if ps:
            console.print(f"  {m}: {len(ps)} parts")
    _print_usage(d["usage"])
    if d["modules_lost"]:
        console.print(f"part modules lost: {', '.join(d['modules_lost'])}")
    if d["other_mods_parts_losing_modules"]:
        console.print(f"[yellow]other mods' parts that lose modules[/]: {', '.join(d['other_mods_parts_losing_modules'])}")
        _print_usage(d["degraded_part_usage"])
    mu = d["module_usage"]
    if mu["crafts"] or mu["vessels"]:
        n = len(mu["crafts"]) + sum(len(v) for v in mu["vessels"].values())
        console.print(f"[dim]{n} crafts/vessels carry patch-added modules that are simply dropped "
                      f"(see --json module_usage)[/]")
    for owner, names in d["patches_referencing"].items():
        console.print(f"  patches in [magenta]{owner}[/] use :NEEDS[{', '.join(names)}]")
    for n in d["notes"]:
        console.print(f"[dim]note: {n}[/]")


@main.command("unused-mods")
@pass_ctx
def unused_mods(c: Ctx):
    """Part mods that no craft or vessel uses (removal candidates)."""
    ctx = analysis.load_context(c.inst, c.save)
    data = analysis.unused_mods(ctx)

    def human(d):
        _table("Removal candidates (nothing used, nothing needs them)", ["mod", "parts", "modules", "auto"],
               [[r["mod"], r["parts"], r["modules"], "y" if r["auto_installed"] else ""] for r in d["candidates"]])
        _table("Unused directly, but needed by other mods", ["mod", "parts", "needed by"],
               [[r["mod"], r["parts"], ", ".join(r["dependents"]) or
                 f"{len(r['parts_of_other_mods_needing_it'])} parts of other mods use its modules"]
                for r in d["required"]])
        _table("Behaviour only: just its patch-added modules are used (judge by what it does)",
               ["mod", "modules seen in crafts/vessels"],
               [[r["mod"], ", ".join(r["modules_used"][:6])] for r in d["behaviour"]])
        console.print(f"[dim]{len(d['in_use'])} mods in use; {len(d['no_signal'])} mods have no parts/modules "
                      f"(visual/UI/config, not judged). index: {d['index_source']}[/]")
    c.emit(data, human)


# ---- part lookup & phase-out ----------------------------------------------------------------

@main.command()
@click.argument("query", nargs=-1, required=True)
@click.option("--limit", default=25, show_default=True)
@pass_ctx
def part(c: Ctx, query, limit):
    """Which mod a part comes from. QUERY is the in-game title or internal name (partial is fine)."""
    ctx = analysis.load_context(c.inst, c.save)
    rows = phaseout.find_parts(ctx, " ".join(query), limit)

    def human(rs):
        if not rs:
            console.print("[red]no matching parts[/]")
        _table(f"Parts matching '{' '.join(query)}'", ["title", "internal name", "mod", "crafts", "vessels"],
               [[r["title"], r["name"], r["mod"], len(r["crafts"]),
                 len([v for v in r["vessels"] if v["save"] == "persistent.sfs"])] for r in rs])
    c.emit(rows, human)


@main.command("phase-out")
@click.option("--max-effort", default=6, show_default=True,
              help="Only mods needing at most this many craft edits + 2x live vessels.")
@click.option("--mod", "mods", multiple=True, help="Show one mod in detail regardless of effort (repeatable).")
@click.option("--out", "out_md", type=click.Path(path_type=Path), help="Also write a Markdown checklist here.")
@click.option("--include-dependents", is_flag=True,
              help="Also list libraries whose removal would break other installed mods.")
@pass_ctx
def phase_out(c: Ctx, max_effort, mods, out_md, include_dependents):
    """Mods that are nearly unused: what to swap in game before they can be removed."""
    ctx = analysis.load_context(c.inst, c.save)
    only = _resolve(ctx, mods) if mods else None
    rows = phaseout.phase_out(ctx, max_effort=max_effort, only=only, include_dependents=include_dependents)
    if out_md:
        out_md.write_text(phaseout.checklist_markdown(rows, c.save), encoding="utf-8")

    def human(rs):
        if not mods:
            _table(f"Phase-out candidates (effort <= {max_effort}; effort = crafts + 2 x live vessels)",
                   ["mod", "eff", "parts", "crafts", "vessels", "+mods"],
                   [[r["mod"], r["effort"],
                     f"{len(r['parts_used'])}/{r['parts_total']}"
                     + (f"+{len(r['dependent_parts_used'])}" if r["dependent_parts_used"] else ""),
                     len(r["crafts"]), len(r["live_vessels"]), len(r["also_removed"]) or ""]
                    for r in rs])
            console.print("[dim]parts = used/total(+other mods' used parts built on it); vessels = live, "
                          "non-debris; +mods = also removed by CKAN[/]")
            console.print("[dim]detail: kat phase-out --mod <mod>   checklist: --out phaseout.md[/]")
        for r in rs if mods else []:
            console.print(f"\n[bold]{r['name']}[/] ({r['mod']}): effort {r['effort']}")
            for p in r["parts_used"] + r["dependent_parts_used"]:
                via = (f" [magenta](from {p['mod']}; uses this mod's {', '.join(p['via_modules'])})[/]"
                       if p["mod"] != r["mod"] else "")
                console.print(f"  [cyan]{p['title']}[/] ({p['name']}){via}")
                for cr in p["crafts"]:
                    console.print(f"     craft {cr}")
                for v in p["vessels"]:
                    tag = " [dim](debris)[/]" if v["disposable"] else ""
                    console.print(f"     {v['save']}: {v['vessel']} {v['situation']} {v['body']}{tag}")
            if r["soft_modules"]:
                console.print(f"  [dim]dropped harmlessly with the mod: {', '.join(r['soft_modules'])}[/]")
            if r["also_removed"]:
                console.print(f"  [yellow]removing it also removes[/]: {', '.join(r['also_removed'])}")
        if out_md:
            console.print(f"[green]checklist written[/] -> {out_md}")
    c.emit(rows, human)


@main.command("tag-parts")
@click.option("--install", "do_install", is_flag=True, help=f"Write GameData/{tagparts.FOLDER}/ModTags.cfg.")
@click.option("--uninstall", "do_uninstall", is_flag=True, help="Delete that folder.")
@click.option("--out", "out_path", type=click.Path(path_type=Path), help="Write the patch somewhere else instead.")
@pass_ctx
def tag_parts(c: Ctx, do_install, do_uninstall, out_path):
    """In-game mod labels: '[Mod: X]' in part descriptions + mod id in VAB search tags."""
    if do_uninstall:
        c.emit(tagparts.uninstall(c.inst), lambda d: console.print(f"removed: {d['removed']}"))
        return
    ctx = analysis.load_context(c.inst, c.save, with_crafts=False, with_vessels=False)
    if do_install:
        data = tagparts.install(c.inst, ctx.idx, ctx.reg)
        c.emit(data, lambda d: console.print(
            f"[green]tagged {d['parts_tagged']} parts[/] -> {d['installed']} ({len(d['skipped'])} skipped). "
            "Takes effect next KSP launch; `kat tag-parts --uninstall` to undo."))
        return
    text, skipped = tagparts.generate(ctx.idx, ctx.reg)
    if out_path:
        out_path.write_text(text, encoding="utf-8")
        c.emit({"written": str(out_path), "skipped": skipped}, lambda d: console.print(f"written -> {d['written']}"))
    else:
        click.echo(text)


# ---- changes (guarded) ----------------------------------------------------------------------

@main.command("backup-save")
@click.option("--dest", type=click.Path(path_type=Path), default=backup.DEFAULT_DEST, show_default=True)
@pass_ctx
def backup_save(c: Ctx, dest):
    """Zip the save folder and verify the archive."""
    data = backup.backup_save(c.inst.save_dir(c.save), dest)
    c.emit(data, lambda d: console.print(f"[green]backed up[/] {d['files']} files -> {d['zip']}"))


@main.command()
@click.argument("mod_names", nargs=-1, required=True)
@click.option("--force", is_flag=True, help="Proceed even if live vessels would lose parts.")
@click.option("--yes", is_flag=True, help="Actually run ckan remove (otherwise only show the plan).")
@click.option("--max-backup-age", default=24.0, show_default=True, help="Hours.")
@pass_ctx
def remove(c: Ctx, mod_names, force, yes, max_backup_age):
    """Guarded `ckan remove`: requires a fresh save backup and a non-breaking removal-impact."""
    ctx = analysis.load_context(c.inst, c.save)
    idents = _resolve(ctx, mod_names)
    impact = analysis.removal_impact(ctx, idents)
    age = backup.backup_age_hours(c.save)
    problems = []
    if age is None or age > max_backup_age:
        problems.append(f"no backup of '{c.save}' newer than {max_backup_age}h; run `kat backup-save`")
    if impact["verdict"] == "BREAKS_VESSELS" and not force:
        problems.append("live vessels would lose parts; rerun with --force if intended")
    result = {"impact": impact, "backup_age_hours": age, "problems": problems, "executed": False}
    if problems or not yes:
        if not c.json:
            _print_impact(impact)
            for p in problems:
                console.print(f"[red]blocked:[/] {p}")
            if not problems:
                console.print("[dim]plan only; add --yes to run ckan remove[/]")
        else:
            c.emit(result)
        sys.exit(2 if problems else 0)
    res = ckan.run(["remove", *idents])
    result.update(executed=True, ckan_returncode=res.returncode, ckan_output=res.output)
    c.emit(result, lambda d: console.print(d["ckan_output"]))
    sys.exit(0 if res.ok else 1)


@main.command("ckan", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.option("--allow-write", is_flag=True, help="Permit subcommands that modify the install/config.")
@pass_ctx
def ckan_cmd(c: Ctx, args, allow_write):
    """Pass through to ckan.exe. Mutating subcommands need --allow-write (prefer `kat remove`)."""
    args = list(args)
    if ckan.is_mutating(args) and not allow_write:
        raise click.ClickException(f"'ckan {' '.join(args)}' modifies the install; add --allow-write")
    res = ckan.run(args)
    c.emit({"args": res.args, "returncode": res.returncode, "output": res.output},
           lambda d: click.echo(d["output"]))
    sys.exit(res.returncode)


def run() -> None:
    try:
        main()
    except InstanceError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    run()
