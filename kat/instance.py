"""Locate the KSP install, its CKAN registry and the ckan.exe CLI."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


class InstanceError(RuntimeError):
    pass


def ckan_config_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "CKAN" / "config.json"


@dataclass(frozen=True)
class Instance:
    root: Path

    @property
    def gamedata(self) -> Path:
        return self.root / "GameData"

    @property
    def saves(self) -> Path:
        return self.root / "saves"

    @property
    def registry_path(self) -> Path:
        return self.root / "CKAN" / "registry.json"

    @property
    def configcache_path(self) -> Path:
        return self.gamedata / "ModuleManager.ConfigCache"

    def save_dir(self, save: str) -> Path:
        d = self.saves / save
        if not d.is_dir():
            raise InstanceError(f"save '{save}' not found under {self.saves}")
        return d


def find_instance(ksp_dir: str | None = None, name: str | None = None) -> Instance:
    """Resolve the KSP root: explicit dir > $KSP_DIR > CKAN config (by name, else the first KSP instance)."""
    explicit = ksp_dir or os.environ.get("KSP_DIR")
    if explicit:
        root = Path(explicit)
    else:
        cfg = ckan_config_path()
        if not cfg.exists():
            raise InstanceError(f"no --ksp-dir given and CKAN config not found at {cfg}")
        data = json.loads(cfg.read_text(encoding="utf-8-sig"))
        instances = [i for i in data.get("GameInstances", []) if i.get("Game", "KSP") == "KSP"]
        if name:
            instances = [i for i in instances if i.get("Name") == name]
        if not instances:
            raise InstanceError("no matching KSP instance in CKAN config")
        root = Path(instances[0]["Path"])
    if not (root / "GameData").is_dir():
        raise InstanceError(f"{root} does not look like a KSP install (no GameData)")
    return Instance(root)


def find_ckan_exe() -> Path:
    """$CKAN_EXE > ckan(.exe) on PATH > ~/Downloads/ckan.exe."""
    env = os.environ.get("CKAN_EXE")
    if env and Path(env).exists():
        return Path(env)
    on_path = shutil.which("ckan") or shutil.which("ckan.exe")
    if on_path:
        return Path(on_path)
    guess = Path.home() / "Downloads" / "ckan.exe"
    if guess.exists():
        return guess
    raise InstanceError("ckan.exe not found; set CKAN_EXE")
