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
| `unused-mods` | Every mod classified: `candidates` / `required` / `behaviour` / `in_use` / `no_signal`. |
| `part QUERY...` | Which mod a part is from, by in-game title or internal name (partial/fuzzy), plus where it's used. |
| `phase-out [--max-effort N] [--mod M] [--out file.md] [--include-dependents]` | Mods that are *nearly* unused, ranked by effort (crafts to edit + 2 x live vessels), with the exact parts/crafts/vessels to change and an in-game Markdown checklist. |
| `tag-parts [--install / --uninstall / --out F]` | MM patch: "[Mod: X]" at the start of every part description and the mod id in its VAB search tags. Writes only `GameData/zzz_kat_ModTags/`. |
| `backup-save` | Zip + verify the save. |
| `remove MOD... [--yes] [--force]` | Guarded `ckan remove`. Without `--yes` it only prints the plan. |
| `ckan ARGS... [--allow-write]` | Passthrough to ckan.exe (headless). |

Global options: `--ksp-dir` (or `$KSP_DIR`), `--save` (or `$KAT_SAVE`; default = most recently
played save), `--json`.

## Phasing a mod out

1. `kat phase-out` lists candidates; `kat phase-out --mod X` shows each part (in-game title) and the
   crafts/vessels that use it; `--out` writes a checklist.
2. The user swaps those parts in the VAB/SPH and recovers or replaces the live vessels. Debris is
   listed but not counted: KSP deletes it on load once its parts are gone.
3. Re-run `kat phase-out --mod X` until it's empty, then follow the removal rules above.

Libraries whose removal would break other installed mods (SystemHeat, CryoTanks...) are hidden unless
`--include-dependents`: they only go when everything built on them goes.

## Verdicts (`removal-impact`)

- `SAFE`: nothing in crafts or saves uses what is removed.
- `DEGRADES`: no parts vanish, but used parts *of other mods* are defined with a module that goes away
  (e.g. a KPBS corridor built on KAS). They load without that behaviour; check whether it matters
  (TextureReplacer's `TRReflection` on Mk2Expansion cockpits is only window reflections).
  Modules the removed mod's own patches added to other parts are listed under `module_usage` but
  don't count: they disappear together with the patch.
- `BREAKS_CRAFT`: stored craft files or non-live saves (quicksave etc.) use removed parts.
- `BREAKS_VESSELS`: vessels in `persistent.sfs` use removed parts. KSP deletes those vessels on load.

## Limits

- `no_signal` mods (visuals, UI, configs, libraries without part modules) can't be judged by usage.
  Decide on those from what they do, not from this tool.
- With `GameData/ModuleManager.ConfigCache` present (after any KSP launch) the index uses the
  post-patch part list; parts disabled or deleted by patches are excluded and copy-patch parts are
  included. Without it (MM cache cleared), raw configs are used. `info` shows `index_source`.
  Hard module dependencies always use each part's own cfg modules (`own_modules`), never patch-added ones.
- Part titles, descriptions and tags are resolved from `en-us` localization.
- Module → mod mapping reads type names out of plugin DLLs. A name shared by two plugins is
  attributed to both; a module counts as lost only when every provider is removed. A DLL that only
  *references* another mod's class (for compatibility) is also matched: e.g. xScienceContinued shows
  up as providing `DMModuleScienceAnimateGeneric`. Treat a UI/utility mod listed as a candidate with
  0 parts as `no_signal`.
- `removal-impact` also lists auto-installed libraries CKAN would orphan. If one is still wanted
  (e.g. TexturesUnlimited recolouring used by craft), keep it with
  `kat ckan --allow-write mark user <mod>` before removing.
- Vessel bodies are named for stock bodies; Kopernicus-added bodies show as `ref:N`.
