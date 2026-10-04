# kerbal-agent-tools

Tools for AI agents (and people) to inspect and safely modify a modded Kerbal Space Program install
managed by [CKAN](https://github.com/KSP-CKAN/CKAN).

The main question it answers: **which mods can I remove without breaking my craft and save?**
It answers before anything is removed:

```
$ python -m kat removal-impact USI-Core
BREAKS_VESSELS
requested: USI-Core
also removed (would break): Karbonite, UKS, USI-FTT
also removed (orphaned auto-installs): Konstruction
  craft Ships/VAB/MT2 Para.craft: MKS.LandingLeg, SalamanderPod
  persistent.sfs vessel SKG 2 (LANDED Minmus): 2/39 parts
  ...
```

## How it works

- Parses KSP ConfigNode files (`.cfg`, `.craft`, `.sfs`) with a small parser (`kat/cfgnode.py`).
- Builds a GameData index: part → owning CKAN mod (through `CKAN/registry.json`'s file list), resource
  definitions, `:NEEDS[...]` references, and part module → plugin DLL that defines it.
- Simulates `ckan remove` from the registry: dependents that would break (handles `any_of` and
  `provides`) plus auto-installed mods left orphaned.
- Cross-references with every craft (`Ships/VAB`, `Ships/SPH`, `Subassemblies`) and the vessels in the save.

## Install

```
pip install -e .[dev]
python -m kat info
```

The KSP path is read from CKAN's `config.json` (override with `--ksp-dir` / `KSP_DIR`). `ckan.exe`
is found through `CKAN_EXE`, `PATH`, or `~/Downloads/ckan.exe`.

See [AGENTS.md](AGENTS.md) for the command list, verdict meanings, safety rules and known limits.
