from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List


def _read_manifest_json(manifest_path: Path) -> dict:
    """
    Read manifest.json robustly:
    - handles UTF-8 BOM (utf-8-sig)
    - handles leading/trailing whitespace
    - throws ValueError if empty
    """
    text = manifest_path.read_text(encoding="utf-8-sig").strip()
    if not text:
        raise ValueError("manifest.json is empty")
    return json.loads(text)


def _copy_item(src: Path, dst: Path) -> None:
    """Copy a file or directory into destination path."""
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for child in src.iterdir():
            if child.is_dir():
                shutil.copytree(child, dst / child.name, dirs_exist_ok=True)
            else:
                (dst / child.name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, dst / child.name)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _build_config_mod(src_mod: Path, dst_mod: Path) -> None:
    """
    Build a config-type mod using manifest.json copy[].
    - Always includes manifest.json in the destination.
    - If copy[] is missing/empty, falls back to copying the whole folder.
    """
    manifest_path = src_mod / "manifest.json"

    # If manifest doesn't exist, treat as folder copy
    if not manifest_path.exists():
        shutil.copytree(src_mod, dst_mod, dirs_exist_ok=True)
        return

    try:
        data = _read_manifest_json(manifest_path)
    except Exception:
        # If manifest is unreadable, safest fallback is full folder copy
        shutil.copytree(src_mod, dst_mod, dirs_exist_ok=True)
        return

    copy_list = data.get("copy", [])
    if not isinstance(copy_list, list) or len(copy_list) == 0:
        # Fallback: copy whole mod folder (includes manifest)
        shutil.copytree(src_mod, dst_mod, dirs_exist_ok=True)
        return

    dst_mod.mkdir(parents=True, exist_ok=True)

    # Always copy manifest.json
    shutil.copy2(manifest_path, dst_mod / "manifest.json")

    for entry in copy_list:
        entry = str(entry).strip()
        if not entry:
            continue

        # Normalize slashes
        entry = entry.replace("\\", "/")

        is_dir = entry.endswith("/")
        rel = entry[:-1] if is_dir else entry

        # Security/safety: don't allow copy entries to escape the mod folder
        # (e.g. "../something")
        if rel.startswith("../") or rel.startswith("..\\") or "/../" in rel or "\\..\\" in rel:
            continue

        src_item = src_mod / rel
        dst_item = dst_mod / rel

        if not src_item.exists():
            continue

        _copy_item(src_item, dst_item)


def build_active(mods_root: Path, enabled_rel_paths: List[str]) -> Path:
    """
    Build mods/_active as a generated, per-mod folder structure.

    enabled_rel_paths examples:
      - "configs/EstellaMod"
      - "skins/CoolSkinPack"

    Returns the active root path.
    """
    active_root = mods_root / "_active"

    # Wipe and recreate
    if active_root.exists():
        shutil.rmtree(active_root)
    active_root.mkdir(parents=True, exist_ok=True)

    for rel in enabled_rel_paths:
        rel = str(rel).replace("\\", "/").strip()
        if not rel or rel.startswith("#"):
            continue

        # Safety: never allow building from inside _active
        if rel.startswith("_active/") or rel == "_active":
            continue

        src = mods_root / rel
        if not src.exists():
            continue

        dst = active_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        manifest = src / "manifest.json"
        mod_type = "folder"

        if manifest.exists():
            try:
                data = _read_manifest_json(manifest)
                mod_type = str(data.get("type") or "folder").lower().strip()
            except Exception:
                mod_type = "folder"

        if mod_type == "config":
            _build_config_mod(src, dst)
        else:
            shutil.copytree(src, dst, dirs_exist_ok=True)

    return active_root
