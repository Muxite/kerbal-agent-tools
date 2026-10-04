"""Zip a save folder and verify the archive."""

from __future__ import annotations

import os
import time
import zipfile
from pathlib import Path

DEFAULT_DEST = Path.home() / "KSP_backups"


def backup_save(save_dir: Path, dest: Path = DEFAULT_DEST) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{save_dir.name}_{time.strftime('%Y-%m-%d_%H%M%S')}.zip"
    n = size = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(save_dir):
            for f in files:
                p = Path(root) / f
                z.write(p, p.relative_to(save_dir.parent).as_posix())
                n += 1
                size += p.stat().st_size
    with zipfile.ZipFile(out) as z:
        infos = z.infolist()
        bad = z.testzip()
    ok = bad is None and len(infos) == n and sum(i.file_size for i in infos) == size
    if not ok:
        raise RuntimeError(f"backup verification failed for {out} (first bad entry: {bad})")
    return {"zip": str(out), "files": n, "bytes": size, "zip_bytes": out.stat().st_size, "verified": ok}


def latest_backup(save_name: str, dest: Path = DEFAULT_DEST) -> Path | None:
    zips = sorted(dest.glob(f"{save_name}_*.zip"), key=lambda p: p.stat().st_mtime)
    return zips[-1] if zips else None


def backup_age_hours(save_name: str, dest: Path = DEFAULT_DEST) -> float | None:
    z = latest_backup(save_name, dest)
    return None if z is None else (time.time() - z.stat().st_mtime) / 3600
