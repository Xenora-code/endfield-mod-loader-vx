from __future__ import annotations
import shutil
from pathlib import Path
from typing import List

def build_active(mods_root: Path, enabled_rel_paths: List[str]) -> Path:
    active_root = mods_root / "_active"

    # wipe
    if active_root.exists():
        shutil.rmtree(active_root)
    active_root.mkdir(parents=True, exist_ok=True)

    for rel in enabled_rel_paths:
        rel = rel.replace("\\", "/")
        src = mods_root / rel
        if not src.exists():
            continue
        dst = active_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True)

    return active_root
