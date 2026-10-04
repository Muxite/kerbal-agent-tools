"""A miniature KSP install for tests.

Mods (CKAN registry):
  PartPack     parts pa.tank, pa_engine (-> pa.engine); explicit
  PluginLib    PluginLib.dll defines ModuleFancy; auto-installed, needed by PartPack
  Addon        depends on PartPack; part ad.wing (uses ModuleFancy)
  Visuals      no parts, no modules; explicit
  Unused       part un.box; explicit
  Choice       depends any_of [PluginLib, OtherLib]
Untracked:     GameData/Squad (stock), GameData/zzz_Fix (manual patch with :NEEDS[PartPack])
Save "Test":   craft Rocket.craft uses pa.tank + Squad fuelTank; vessel "Probe" uses pa.engine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REGISTRY = {
    "installed_modules": {
        "PartPack": {"auto_installed": False, "source_module": {
            "name": "Part Pack", "version": "1.0", "depends": [{"name": "PluginLib"}]},
            "installed_files": {"GameData/PartPack": {}}},
        "PluginLib": {"auto_installed": True, "source_module": {
            "name": "Plugin Lib", "version": "2.0", "provides": ["PluginLibAPI"]},
            "installed_files": {"GameData/PluginLib": {}}},
        "Addon": {"auto_installed": False, "source_module": {
            "name": "Addon", "version": "1.0", "depends": [{"name": "PartPack"}]},
            "installed_files": {"GameData/Addon": {}}},
        "Visuals": {"auto_installed": False, "source_module": {"name": "Visuals", "version": "1"},
                    "installed_files": {"GameData/Visuals": {}}},
        "Unused": {"auto_installed": False, "source_module": {"name": "Unused", "version": "1"},
                   "installed_files": {"GameData/Unused": {}}},
        "Choice": {"auto_installed": False, "source_module": {
            "name": "Choice", "version": "1",
            "depends": [{"any_of": [{"name": "PluginLibAPI"}, {"name": "OtherLib"}]}]},
            "installed_files": {"GameData/Choice": {}}},
    },
    "installed_files": {
        "GameData/PartPack/parts.cfg": "PartPack",
        "GameData/PartPack": "PartPack",
        "GameData/PluginLib/PluginLib.dll": "PluginLib",
        "GameData/PluginLib": "PluginLib",
        "GameData/Addon/wing.cfg": "Addon",
        "GameData/Addon": "Addon",
        "GameData/Visuals/clouds.cfg": "Visuals",
        "GameData/Visuals": "Visuals",
        "GameData/Unused/box.cfg": "Unused",
        "GameData/Unused": "Unused",
        "GameData/Choice": "Choice",
    },
    "installed_dlls": {},
}

FILES = {
    "GameData/PartPack/parts.cfg": """
PART
{
    name = pa.tank
    title = Tank
    MODULE { name = ModuleFancy }
}
PART
{
    name = pa_engine
    MODULE
    {
        name = ModuleEngines
    }
}
RESOURCE_DEFINITION { name = Goo }
""",
    "GameData/Addon/wing.cfg": "PART\n{\n\tname = ad.wing\n\tMODULE { name = ModuleFancy }\n}\n",
    "GameData/Unused/box.cfg": "PART { name = un.box }\n",
    "GameData/Visuals/clouds.cfg": "EVE_CLOUDS { name = c }\n",
    "GameData/Squad/fuelTank.cfg": "﻿PART\r\n{\r\n\tname = fuelTank\r\n}\r\n",
    "GameData/zzz_Fix/fix.cfg": "@PART[pa.tank]:NEEDS[PartPack]:FINAL { @title = Fixed }\n",
    "saves/Test/Ships/VAB/Rocket.craft": """ship = Rocket
version = 1.12.5
description = big¨rocket
type = VAB
PART
{
\tpart = pa.tank_4289248132
\tMODULE
\t{
\t\tname = ModuleFancy
\t}
\tRESOURCE
\t{
\t\tname = Goo
\t\tamount = 5
\t}
}
PART
{
\tpart = fuelTank_123
}
""",
    "saves/Test/persistent.sfs": """GAME
{
\tFLIGHTSTATE
\t{
\t\tVESSEL
\t\t{
\t\t\tname = Probe
\t\t\ttype = Probe
\t\t\tsit = ORBITING
\t\t\tORBIT
\t\t\t{
\t\t\t\tSMA = 700000
\t\t\t\tREF = 1
\t\t\t}
\t\t\tPART
\t\t\t{
\t\t\t\tname = pa.engine
\t\t\t\tcrew = Jebediah Kerman
\t\t\t}
\t\t}
\t\tVESSEL
\t\t{
\t\t\tname = Flag
\t\t\ttype = Flag
\t\t\tsit = LANDED
\t\t\tlat = 1.5
\t\t\tlon = -70
\t\t\tORBIT { REF = 2 }
\t\t}
\t}
}
""",
}


@pytest.fixture
def ksp(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "KSP"
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    (root / "CKAN").mkdir()
    (root / "CKAN" / "registry.json").write_text(json.dumps(REGISTRY), encoding="utf-8")
    # A fake .NET assembly: type names live in the #Strings heap as NUL-terminated identifiers.
    dll = root / "GameData" / "PluginLib" / "PluginLib.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"MZ\x00\x00ModuleFancy\x00SomethingElse\x00")
    monkeypatch.setenv("KSP_DIR", str(root))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.delenv("KAT_SAVE", raising=False)
    return root
