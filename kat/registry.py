"""Read-only view of CKAN's registry.json, plus a simulation of what ``ckan remove`` would remove."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Module:
    identifier: str
    name: str
    version: str
    abstract: str
    auto_installed: bool
    depends: list[list[str]]  # each entry is a set of alternatives (any_of); one must remain
    provides: list[str]
    files: list[str] = field(default_factory=list)

    @property
    def names(self) -> set[str]:
        """Identifiers this module satisfies a dependency on (itself plus 'provides')."""
        return {self.identifier, *self.provides}


def _dep_alternatives(dep: dict) -> list[str]:
    if "any_of" in dep:
        out: list[str] = []
        for alt in dep["any_of"]:
            out.extend(_dep_alternatives(alt))
        return out
    return [dep["name"]] if "name" in dep else []


class Registry:
    def __init__(self, data: dict):
        self.raw = data
        self.modules: dict[str, Module] = {}
        for ident, entry in data.get("installed_modules", {}).items():
            sm = entry.get("source_module", {})
            self.modules[ident] = Module(
                identifier=ident,
                name=sm.get("name", ident),
                version=str(sm.get("version", "")),
                abstract=sm.get("abstract", ""),
                auto_installed=bool(entry.get("auto_installed", False)),
                depends=[alts for d in sm.get("depends", []) or [] if (alts := _dep_alternatives(d))],
                provides=list(sm.get("provides", []) or []),
                files=list(entry.get("installed_files", {}).keys()),
            )
        # DLLs CKAN saw but doesn't manage still satisfy dependencies by name.
        self.manual_dlls: set[str] = set(data.get("installed_dlls", {}).keys())
        self._file_index = {p.lower(): mod for p, mod in data.get("installed_files", {}).items()}

    @classmethod
    def load(cls, path: str | Path) -> "Registry":
        return cls(json.loads(Path(path).read_text(encoding="utf-8-sig")))

    # ---- lookups -------------------------------------------------------------------------

    def owner_of(self, rel_path: str) -> str | None:
        """CKAN identifier owning a path relative to the KSP root (e.g. 'GameData/KAS/x.cfg')."""
        p = rel_path.replace("\\", "/").strip("/").lower()
        while p:
            if p in self._file_index:
                return self._file_index[p]
            if "/" not in p:
                return None
            p = p.rsplit("/", 1)[0]
        return None

    def resolve(self, name: str) -> str | None:
        """Map an identifier, display name or folder-ish name to an installed identifier."""
        if name in self.modules:
            return name
        low = name.lower()
        for ident, m in self.modules.items():
            if ident.lower() == low or m.name.lower() == low:
                return ident
        return None

    def providers(self, dep_name: str, installed: set[str]) -> set[str]:
        return {i for i in installed if dep_name in self.modules[i].names}

    def dependents(self, ident: str, installed: set[str] | None = None) -> set[str]:
        """Installed modules with a dependency that ``ident`` (or something it provides) can satisfy."""
        installed = set(self.modules) if installed is None else installed
        names = self.modules[ident].names
        return {
            i for i in installed
            if i != ident and any(names & set(alts) for alts in self.modules[i].depends)
        }

    # ---- removal simulation --------------------------------------------------------------

    def _satisfied(self, alts: list[str], remaining: set[str]) -> bool:
        return any(self.providers(a, remaining) for a in alts) or any(a in self.manual_dlls for a in alts)

    def removal_set(self, requested: list[str]) -> dict[str, list[str]]:
        """Simulate ``ckan remove``. Returns {"requested", "broken_dependents", "orphaned_auto"}.

        1. Requested modules.
        2. Every installed module with a dependency that nothing remaining can satisfy (fixed point).
        3. Auto-installed modules that nothing remaining depends on any more (fixed point).
        """
        missing = [r for r in requested if r not in self.modules]
        if missing:
            raise KeyError(f"not installed: {', '.join(missing)}")

        installed = set(self.modules)
        removing = set(requested)
        broken: list[str] = []
        changed = True
        while changed:
            changed = False
            remaining = installed - removing
            for i in sorted(remaining):
                if not all(self._satisfied(alts, remaining) for alts in self.modules[i].depends):
                    removing.add(i)
                    broken.append(i)
                    changed = True

        orphaned: list[str] = []
        changed = True
        while changed:
            changed = False
            remaining = installed - removing
            for i in sorted(remaining):
                if self.modules[i].auto_installed and not self.dependents(i, remaining):
                    removing.add(i)
                    orphaned.append(i)
                    changed = True

        return {"requested": sorted(requested), "broken_dependents": broken, "orphaned_auto": orphaned}
