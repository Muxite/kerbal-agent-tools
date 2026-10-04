"""Index of GameData: which mod provides each part and resource, and which mods' patches NEED what.

Two part sources:
  * ``ModuleManager.ConfigCache`` (preferred): the post-patch database. Each top-level
    ``UrlConfig`` records the file a node came from (``parentUrl``) and catches parts created by
    copy patches (``+PART``).
  * A raw scan of ``GameData/**/*.cfg`` (fallback): top-level ``PART`` nodes only.

Ownership of a file is resolved via the CKAN registry; untracked folders become
``manual:<Folder>`` and the stock folders ``stock:Squad`` / ``stock:SquadExpansion``.
The index is cached outside GameData (we never write into the game install).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import cfgnode
from .instance import Instance
from .registry import Registry

STOCK_FOLDERS = {"squad", "squadexpansion"}
_PART_LINE = re.compile(r"^\s*PART\b", re.M)
_NEEDS = re.compile(r":NEEDS\[([^\]]*)\]", re.I)
_SPLIT = re.compile(r"[,|&]")


def normalize_part_name(name: str) -> str:
    """KSP replaces '_' with '.' in part names when it loads them."""
    return name.strip().replace("_", ".")


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    d = Path(base) / "kerbal-agent-tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class PartInfo:
    name: str
    mod: str
    file: str
    title: str = ""
    modules: list[str] = field(default_factory=list)
    raw_name: str = ""  # name as written in the cfg (may contain '_'); what MM patches must match
    category: str = ""
    description: str = ""
    tags: str = ""
    # Modules in the part's own cfg definition (before other mods' patches). Hard dependencies use
    # these; `modules` may be post-patch when the index comes from ModuleManager.ConfigCache.
    own_modules: list[str] = field(default_factory=list)


@dataclass
class GameDataIndex:
    source: str  # "configcache" | "raw-scan"
    parts: dict[str, PartInfo] = field(default_factory=dict)
    resources: dict[str, str] = field(default_factory=dict)  # resource name -> mod
    needs: dict[str, list[str]] = field(default_factory=dict)  # mod -> names it :NEEDS
    folder_owner: dict[str, str] = field(default_factory=dict)  # top-level GameData folder -> mod
    module_owner: dict[str, list[str]] = field(default_factory=dict)  # PartModule class -> mods whose DLLs define it

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "GameDataIndex":
        idx = cls(source=d["source"], resources=d["resources"], needs=d["needs"],
                  folder_owner=d["folder_owner"], module_owner=d["module_owner"])
        idx.parts = {k: PartInfo(**v) for k, v in d["parts"].items()}
        return idx

    def parts_of(self, mods: set[str]) -> list[PartInfo]:
        return sorted((p for p in self.parts.values() if p.mod in mods), key=lambda p: p.name)

    def mod_of_part(self, part_name: str) -> str:
        info = self.parts.get(normalize_part_name(part_name))
        return info.mod if info else "unknown"


def _owner(reg: Registry, rel_from_gamedata: str) -> str:
    rel = rel_from_gamedata.replace("\\", "/").lstrip("/")
    mod = reg.owner_of("GameData/" + rel)
    if mod:
        return mod
    top = rel.split("/", 1)[0]
    if top.lower() in STOCK_FOLDERS:
        return f"stock:{top}"
    return f"manual:{top}"


def _needs_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for m in _NEEDS.finditer(text):
        for tok in _SPLIT.split(m.group(1)):
            tok = tok.strip().lstrip("!").strip()
            if tok:
                out.add(tok)
    return out


def _signature(inst: Instance) -> dict:
    gd = inst.gamedata
    tops = {}
    for entry in os.scandir(gd):
        try:
            tops[entry.name] = entry.stat().st_mtime
        except OSError:
            pass
    cc = inst.configcache_path
    return {
        "root": str(inst.root),
        "registry": inst.registry_path.stat().st_mtime if inst.registry_path.exists() else 0,
        "configcache": cc.stat().st_mtime if cc.exists() else 0,
        "tops": tops,
        "version": 6,
    }


def _base_name(node_name: str) -> str:
    """'@PART[foo]:NEEDS[x]' -> 'PART'; '+MODULE' -> 'MODULE'."""
    return re.split(r"[\[:]", node_name.lstrip("@+$-!%&|*"), maxsplit=1)[0].strip()


def _part_info(n: cfgnode.ConfigNode, owner: str, rel: str) -> PartInfo:
    raw = n.get("name") or ""
    return PartInfo(
        name=normalize_part_name(raw), mod=owner, file=rel, title=n.get("title", ""),
        modules=[m.get("name") for m in n.nodes_named("MODULE") if m.get("name")],
        raw_name=raw, category=n.get("category", ""), description=n.get("description", ""),
        tags=n.get("tags", ""),
        own_modules=[m.get("name") for m in n.nodes_named("MODULE") if m.get("name")],
    )


def _collect_localization(root: cfgnode.ConfigNode, loc: dict[str, str], lang: str = "en-us") -> None:
    for n in root.nodes:
        if n.name == "Localization":
            for table in n.nodes_named(lang):
                for k, v in table.values:
                    loc.setdefault(k, v)


def localize(text: str, loc: dict[str, str]) -> str:
    """Resolve a '#autoLOC_...'/'#LOC_...' key to English; KSP writes newlines as a literal '\\n'."""
    if text.startswith("#"):
        text = loc.get(text, text)
    return text.replace("\\n", " ").strip()


def _scan_cfg_files(inst: Instance, reg: Registry, idx: GameDataIndex, raw_parts: dict[str, PartInfo],
                    module_names: set[str], loc: dict[str, str]) -> None:
    gd = inst.gamedata
    for dirpath, _dirs, files in os.walk(gd):
        for f in files:
            if not f.lower().endswith(".cfg"):
                continue
            path = Path(dirpath) / f
            rel = path.relative_to(gd).as_posix()
            owner = _owner(reg, rel)
            try:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            toks = _needs_tokens(text)
            if toks:
                idx.needs[owner] = sorted(set(idx.needs.get(owner, [])) | toks)
            if not ("RESOURCE_DEFINITION" in text or "MODULE" in text or "Localization" in text
                    or _PART_LINE.search(text)):
                continue
            root = cfgnode.loads(text)
            if "Localization" in text:
                _collect_localization(root, loc)
            for n in root.walk():
                if _base_name(n.name) == "MODULE" and n.get("name"):
                    module_names.add(n.get("name"))
            for n in root.nodes:
                base = n.name.split(":")[0]
                if base == "RESOURCE_DEFINITION" and n.get("name"):
                    idx.resources.setdefault(n.get("name"), owner)
                elif base == "PART" and n.get("name"):
                    info = _part_info(n, owner, rel)
                    raw_parts.setdefault(info.name, info)


def _scan_configcache(inst: Instance, reg: Registry, idx: GameDataIndex, module_names: set[str]) -> None:
    root = cfgnode.load(inst.configcache_path)
    for uc in root.nodes:
        if uc.name != "UrlConfig":
            continue
        parent = (uc.get("parentUrl") or "").lstrip("/")
        for n in uc.nodes:
            if n.name == "PART" and n.get("name"):
                info = _part_info(n, _owner(reg, parent), parent)
                module_names.update(info.modules)
                idx.parts[info.name] = info
            elif n.name == "RESOURCE_DEFINITION" and n.get("name"):
                idx.resources.setdefault(n.get("name"), _owner(reg, parent))


_IDENT = re.compile(rb"\x00([A-Za-z_][A-Za-z0-9_]{2,80})(?=\x00)")


def _dll_identifiers(path: Path) -> set[str]:
    """Null-terminated identifiers in a .NET assembly (the #Strings heap holds type names)."""
    try:
        data = path.read_bytes()
    except OSError:
        return set()
    return {m.group(1).decode("ascii") for m in _IDENT.finditer(data)}


def _scan_dlls(inst: Instance, reg: Registry, idx: GameDataIndex, module_names: set[str]) -> None:
    """Map PartModule names used in configs to the mods whose plugins define them."""
    stock_dll = inst.root / "KSP_x64_Data" / "Managed" / "Assembly-CSharp.dll"
    stock = _dll_identifiers(stock_dll) & module_names
    owners: dict[str, set[str]] = {m: {"stock:KSP"} for m in stock}
    for dirpath, _dirs, files in os.walk(inst.gamedata):
        for f in files:
            if not f.lower().endswith(".dll"):
                continue
            path = Path(dirpath) / f
            owner = _owner(reg, path.relative_to(inst.gamedata).as_posix())
            for name in (_dll_identifiers(path) & module_names) - stock:
                owners.setdefault(name, set()).add(owner)
    idx.module_owner = {k: sorted(v) for k, v in sorted(owners.items())}


def build_index(inst: Instance, reg: Registry, rebuild: bool = False) -> GameDataIndex:
    sig = _signature(inst)
    cache_file = cache_dir() / "gamedata-index.json"
    if not rebuild and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("signature") == sig:
                return GameDataIndex.from_json(cached["index"])
        except (ValueError, KeyError, TypeError):
            pass

    use_cc = inst.configcache_path.exists()
    idx = GameDataIndex(source="configcache" if use_cc else "raw-scan")
    module_names: set[str] = set()
    loc: dict[str, str] = {}
    raw_parts: dict[str, PartInfo] = {}
    _scan_cfg_files(inst, reg, idx, raw_parts, module_names=module_names, loc=loc)
    if use_cc:
        _scan_configcache(inst, reg, idx, module_names)
        for name, p in idx.parts.items():
            if name in raw_parts:
                p.own_modules = raw_parts[name].own_modules
    else:
        idx.parts = raw_parts
    _scan_dlls(inst, reg, idx, module_names)
    for p in idx.parts.values():
        p.title = localize(p.title, loc) or p.name
        p.description = localize(p.description, loc)
        p.tags = localize(p.tags, loc)
    for entry in os.scandir(inst.gamedata):
        if entry.is_dir():
            idx.folder_owner[entry.name] = _owner(reg, entry.name + "/")

    cache_file.write_text(json.dumps({"signature": sig, "index": idx.to_json()}), encoding="utf-8")
    return idx
