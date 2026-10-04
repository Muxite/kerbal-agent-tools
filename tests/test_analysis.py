import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kat import analysis
from kat.cli import main
from kat.craft import craft_part_name, parse_craft
from kat.instance import find_instance
from kat.registry import Registry
from kat.save import load_vessels


@pytest.fixture
def ctx(ksp):
    return analysis.load_context(find_instance(), "Test")


def test_craft_part_names():
    assert craft_part_name("sspx-core-375-1_4289248132") == "sspx-core-375-1"
    assert craft_part_name("pa_engine_77") == "pa.engine"


def test_parse_craft(ksp):
    c = parse_craft(ksp / "saves/Test/Ships/VAB/Rocket.craft")
    assert c.name == "Rocket" and c.facility == "VAB" and c.part_count == 2
    assert c.description == "big\nrocket"
    assert c.resources == {"Goo": 5.0}


def test_parse_vessels(ksp):
    vs = load_vessels(ksp / "saves/Test/persistent.sfs")
    assert [(v.name, v.body, v.part_count) for v in vs] == [("Probe", "Kerbin", 1), ("Flag", "Mun", 0)]
    assert vs[0].crew == ["Jebediah Kerman"]


def test_index_maps_parts_modules_and_stock(ctx):
    idx = ctx.idx
    assert idx.parts["pa.engine"].mod == "PartPack"  # '_' normalised to '.'
    assert idx.parts["fuelTank"].mod == "stock:Squad"  # BOM-prefixed file still indexed
    assert idx.module_owner["ModuleFancy"] == ["PluginLib"]
    assert idx.resources["Goo"] == "PartPack"
    assert "PartPack" in idx.needs["manual:zzz_Fix"]


def test_craft_deps(ctx):
    d = analysis.craft_deps(ctx, ctx.crafts[0])
    assert d["mods"] == {"PartPack": ["pa.tank"], "stock:Squad": ["fuelTank"]}
    assert d["plugin_mods"] == {"PluginLib": ["ModuleFancy"]}
    assert d["missing_parts"] == []


def test_removal_set_cascades_and_orphans(ksp):
    reg = Registry.load(ksp / "CKAN/registry.json")
    assert reg.removal_set(["PartPack"]) == {
        "requested": ["PartPack"], "broken_dependents": ["Addon"], "orphaned_auto": []}
    # Once PartPack and Choice are both gone, nothing needs the auto-installed PluginLib.
    sim = reg.removal_set(["PartPack", "Choice"])
    assert sim["orphaned_auto"] == ["PluginLib"]


def test_removal_impact_verdicts(ctx):
    assert analysis.removal_impact(ctx, ["Unused"])["verdict"] == "SAFE"
    assert analysis.removal_impact(ctx, ["Visuals"])["verdict"] == "SAFE"
    impact = analysis.removal_impact(ctx, ["PartPack"])
    assert impact["verdict"] == "BREAKS_VESSELS"
    assert impact["usage"]["vessels"]["persistent.sfs"][0]["vessel"] == "Probe"
    assert impact["patches_referencing"] == {"manual:zzz_Fix": ["PartPack"]}


def test_removal_impact_module_only_degrades(ctx):
    # PartPack depends on PluginLib directly; Choice's any_of is only met by PluginLib's 'provides'.
    impact = analysis.removal_impact(ctx, ["PluginLib"])
    assert set(impact["removal_set"]["broken_dependents"]) >= {"PartPack", "Choice"}
    assert "ModuleFancy" in impact["modules_lost"]


def test_unused_mods(ctx):
    out = analysis.unused_mods(ctx)
    names = {k: [r["mod"] for r in v] for k, v in out.items() if isinstance(v, list)}
    assert "Unused" in names["candidates"]
    assert "PartPack" in names["in_use"]
    assert "PluginLib" in names["in_use"]  # its module is used by the craft
    assert "Visuals" in names["no_signal"]


def test_cli_json(ksp):
    r = CliRunner().invoke(main, ["--save", "Test", "--json", "removal-impact", "Unused"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["verdict"] == "SAFE"


def test_cli_remove_blocked_without_backup(ksp):
    r = CliRunner().invoke(main, ["--save", "Test", "--json", "remove", "Unused", "--yes"])
    assert r.exit_code == 2
    assert "no backup" in json.loads(r.output)["problems"][0]


def test_cli_ckan_passthrough_blocks_writes(ksp):
    r = CliRunner().invoke(main, ["ckan", "remove", "Unused"])
    assert r.exit_code != 0 and "--allow-write" in r.output


def test_backup_roundtrip(ksp, tmp_path):
    r = CliRunner().invoke(main, ["--save", "Test", "--json", "backup-save", "--dest", str(tmp_path / "bk")])
    assert r.exit_code == 0, r.output
    d = json.loads(r.output)
    assert d["verified"] and d["files"] == 2 and Path(d["zip"]).exists()
