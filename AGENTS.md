# Agent guide: kerbal-agent-tools

`kat` inspects a modded Kerbal Space Program install (CKAN-managed) and answers "what does this
craft need?" and "what breaks if I remove this mod?" **before** anything is changed.

Run it as `python -m kat ...` (works without the Scripts dir on PATH). Pass `--json` before the
subcommand for machine-readable output: `python -m kat --json removal-impact KAS`.

## Rules

1. **Analysis is read-only.** Nothing in `kat` writes to `GameData/` or `saves/`. The GameData index
   is cached in `%LOCALAPPDATA%/kerbal-agent-tools/`.
2. **Before removing any mod:**
   1. `kat backup-save` (zips the save to `~/KSP_backups`, verifies CRCs).
   2. `kat removal-impact MOD...` and show the user the verdict, the full removal set (CKAN also
      removes broken dependents and orphaned auto-installs), and any affected crafts/vessels.
   3. Get the user's go-ahead, then `kat remove MOD... --yes`. It refuses without a backup from the
      last 24h, and refuses `BREAKS_VESSELS` without `--force`.
3. Don't use `kat ckan remove/install/...` to bypass that; mutating passthrough requires
   `--allow-write` and is for installs/upgrades the user asked for.
4. KSP and the CKAN GUI must be closed before any CKAN change.
5. Never edit `.sfs` save files.

## Commands

| Command | What it answers |
|---|---|
| `info [--rebuild]` | Paths, index source, counts. `--rebuild` after mods change outside CKAN. |
| `mods` | Installed mods with part counts and reverse dependencies. |
| `craft-deps [CRAFT...] [--missing-only]` | Mods each craft needs (parts → hard deps; part modules → `plugin_mods`). `--missing-only` finds crafts already broken. |
| `vessels [--all-saves] [--body X]` | Vessels in persistent/quicksave (or every .sfs). |
| `mod-usage MOD...` | Crafts/vessels that use parts from these mods. |
| `removal-impact MOD... [--all-saves]` | Dry run of `ckan remove`: removal set, parts lost, usage, modules lost, other mods' parts that lose modules, patches with `:NEEDS[...]` on it, verdict. |
| `unused-mods` | Every mod classified: `candidates` / `required` / `in_use` / `no_signal`. |
| `backup-save` | Zip + verify the save. |
| `remove MOD... [--yes] [--force]` | Guarded `ckan remove`. Without `--yes` it only prints the plan. |
| `ckan ARGS... [--allow-write]` | Passthrough to ckan.exe (headless). |

Global options: `--ksp-dir` (or `$KSP_DIR`), `--save` (or `$KAT_SAVE`; default = most recently
played save), `--json`.

## Verdicts (`removal-impact`)

- `SAFE`: nothing in crafts or saves uses what is removed.
- `DEGRADES`: no parts vanish, but part modules do (used by crafts/vessels, or by other mods' parts).
  Parts load without that behaviour (e.g. a wheel without its wheel module).
- `BREAKS_CRAFT`: stored craft files or non-live saves (quicksave etc.) use removed parts.
- `BREAKS_VESSELS`: vessels in `persistent.sfs` use removed parts. KSP deletes those vessels on load.

## Limits

- `no_signal` mods (visuals, UI, configs, libraries without part modules) can't be judged by usage.
  Decide on those from what they do, not from this tool.
- Without `GameData/ModuleManager.ConfigCache` (it's deleted whenever the MM cache is cleared; KSP
  regenerates it on the next launch), parts created by ModuleManager copy patches aren't indexed and
  part module lists come from raw configs (no patch-added modules). Prefer running after a game
  launch; `info` shows `index_source`.
- Module → mod mapping reads type names out of plugin DLLs. A name shared by two plugins is
  attributed to both; a module counts as lost only when every provider is removed.
- Vessel bodies are named for stock bodies; Kopernicus-added bodies show as `ref:N`.
