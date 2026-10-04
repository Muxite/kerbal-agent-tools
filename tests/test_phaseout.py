import json

import pytest
from click.testing import CliRunner

from kat import analysis, cfgnode, phaseout, tagparts
from kat.cli import main
from kat.instance import find_instance


@pytest.fixture
def ctx(ksp):
    return analysis.load_context(find_instance(), "Test")


def test_find_parts_by_title_and_name(ctx):
    rows = phaseout.find_parts(ctx, "tank")
    assert [r["name"] for r in rows][:2] == ["pa.tank", "fuelTank"]
    assert rows[0]["mod"] == "PartPack" and rows[0]["title"] == "Tank"
    assert rows[0]["crafts"] == ["Ships/VAB/Rocket.craft"]
    assert phaseout.find_parts(ctx, "pa_engine")[0]["vessels"][0]["vessel"] == "Probe"


def test_phase_out_effort_and_dependent_parts(ctx):
    rows = {r["mod"]: r for r in phaseout.phase_out(ctx, max_effort=None, include_dependents=True)}
    # PartPack: 1 craft + 2 x 1 live vessel
    assert rows["PartPack"]["effort"] == 3
    # PluginLib has no parts, but PartPack's tank is defined with its ModuleFancy
    dep = rows["PluginLib"]["dependent_parts_used"]
    assert [d["name"] for d in dep] == ["pa.tank"] and dep[0]["via_modules"] == ["ModuleFancy"]
    assert "Unused" not in rows and "Addon" not in rows  # fully unused -> unused-mods, not phase-out


def test_phase_out_threshold_and_checklist(ctx):
    assert [r["mod"] for r in phaseout.phase_out(ctx, max_effort=1, include_dependents=True)] == ["PluginLib"]
    # PartPack and PluginLib would break Addon/Choice, so they're hidden by default...
    assert phaseout.phase_out(ctx, max_effort=None) == []
    # ...but asking for a mod by name always shows it.
    assert [r["mod"] for r in phaseout.phase_out(ctx, only=["PartPack"])] == ["PartPack"]
    md = phaseout.checklist_markdown(phaseout.phase_out(ctx, max_effort=None, include_dependents=True), "Test")
    assert "- [ ] edit craft `Ships/VAB/Rocket.craft`" in md
    assert "vessel **Probe**" in md


def test_tag_patch_is_valid_and_uses_raw_names(ctx):
    text, skipped = tagparts.generate(ctx.idx, ctx.reg)
    assert skipped == []
    assert "@PART[pa_engine]:FINAL" in text  # cfg name, not the '.' form KSP uses at runtime
    assert "%description = [Mod: Part Pack]" in text
    assert "%tags = partpack" in text
    root = cfgnode.loads(text)
    assert len(root.nodes) == len(ctx.idx.parts)


def test_tag_install_uninstall(ksp):
    r = CliRunner().invoke(main, ["--save", "Test", "--json", "tag-parts", "--install"])
    assert r.exit_code == 0, r.output
    assert (ksp / "GameData" / tagparts.FOLDER / "ModTags.cfg").exists()
    CliRunner().invoke(main, ["--json", "tag-parts", "--uninstall"])
    assert not (ksp / "GameData" / tagparts.FOLDER).exists()


CONFIGCACHE = """patchedNodeCount = 3
UrlConfig
{
\tparentUrl = PartPack/parts.cfg
\tPART
\t{
\t\tname = pa.tank
\t\ttitle = Tank
\t\tMODULE
\t\t{
\t\t\tname = ModuleFancy
\t\t}
\t\tMODULE
\t\t{
\t\t\tname = ModuleInjected
\t\t}
\t}
}
UrlConfig
{
\tparentUrl = Squad/fuelTank.cfg
\tPART
\t{
\t\tname = fuelTank
\t}
}
"""


def test_configcache_source_keeps_own_modules(ksp):
    (ksp / "GameData" / "ModuleManager.ConfigCache").write_text(CONFIGCACHE, encoding="utf-8")
    ctx = analysis.load_context(find_instance(), "Test", rebuild=True)
    assert ctx.idx.source == "configcache"
    assert set(ctx.idx.parts) == {"pa.tank", "fuelTank"}
    tank = ctx.idx.parts["pa.tank"]
    assert tank.mod == "PartPack"
    assert "ModuleInjected" in tank.modules and "ModuleInjected" not in tank.own_modules


def test_cli_part_and_phase_out(ksp, tmp_path):
    r = CliRunner().invoke(main, ["--save", "Test", "--json", "part", "Tank"])
    assert json.loads(r.output)[0]["name"] == "pa.tank"
    md = tmp_path / "po.md"
    r = CliRunner().invoke(main, ["--save", "Test", "--json", "phase-out", "--out", str(md)])
    assert r.exit_code == 0, r.output
    assert md.read_text(encoding="utf-8").startswith("# Phase-out checklist (Test)")


def test_tag_patch_is_idempotent_on_already_tagged_cache(ctx):
    tank = ctx.idx.parts["pa.tank"]
    tank.description, tank.tags = "[Mod: Part Pack] A tank", "fuel partpack"
    text, _ = tagparts.generate(ctx.idx, ctx.reg)
    assert "%description = [Mod: Part Pack] A tank\n" in text
    assert "%tags = fuel partpack\n" in text
