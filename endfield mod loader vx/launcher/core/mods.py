from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class ModInfo:
    name: str
    rel_path: str
    mod_type: str  # "config", "asset", "migoto", "folder"
    version: str = ""
    author: str = ""
    description: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# These are "category" folders directly under mods/
CATEGORY_FOLDERS = {"misc", "skins", "configs", "assets", "folders"}

# These are NOT mods — they are common internal subfolders of a mod
# If the scanner sees these, it must NOT list them as separate mods.
NOT_A_MOD_FOLDER_NAMES = {
    "texture", "textures",
    "buffer", "buffers",
    "shader", "shaders",
    "output", "outputs",
    "cache", "caches",
    "override", "overrides",
    "resources", "resource",
    "__pycache__",
}

_ALLOWED_ASSET_ROOTS = ("Endfield_Data", "resources", "game_files", "translations", "plugins")


def _has_any_suffix(root: Path, suffixes: tuple[str, ...]) -> bool:
    for p in root.rglob("*"):
        if p.is_file() and p.name.lower().endswith(suffixes):
            return True
    return False


def _looks_like_migoto_mod_folder(mod_dir: Path) -> bool:
    # Migoto marker folders/files at THIS LEVEL
    if (mod_dir / "Texture").exists() or (mod_dir / "texture").exists():
        return True
    if (mod_dir / "Buffer").exists() or (mod_dir / "buffer").exists():
        return True
    if (mod_dir / "d3dx.ini").exists():
        return True
    # Or any .dds/.buf inside (common for packed folders)
    return _has_any_suffix(mod_dir, (".dds", ".buf"))


def _looks_like_asset_mod_folder(mod_dir: Path) -> bool:
    for root in _ALLOWED_ASSET_ROOTS:
        if (mod_dir / root).exists():
            return True
    return False


def _looks_like_config_mod_folder(mod_dir: Path) -> bool:
    # Loose heuristic
    return _has_any_suffix(mod_dir, (".ini", ".cfg", ".txt", ".json"))


def _folder_has_any_file(mod_dir: Path) -> bool:
    for p in mod_dir.rglob("*"):
        if p.is_file():
            # ignore windows junk
            if p.name.lower() in ("desktop.ini",):
                continue
            return True
    return False


def _is_container_folder(mod_dir: Path, mods_root: Path) -> bool:
    """
    Do not list:
      - mods/ root
      - top-level category folders like mods/misc, mods/skins, etc.
    """
    try:
        rel = mod_dir.relative_to(mods_root)
    except Exception:
        return True

    if rel.as_posix() in (".", ""):
        return True

    # first folder under mods/
    if len(rel.parts) == 1:
        return True

    return False


def _is_subfolder_that_should_not_be_listed(mod_dir: Path, mods_root: Path) -> bool:
    """
    Skip folders like Texture/ and Buffer/ (3DMigoto internals),
    even though they contain files.
    """
    name = mod_dir.name.lower().strip()

    if name in NOT_A_MOD_FOLDER_NAMES:
        return True

    # If it is exactly mods/misc or mods/skins etc, skip (container)
    try:
        rel = mod_dir.relative_to(mods_root)
        if len(rel.parts) == 1 and rel.parts[0].lower() in CATEGORY_FOLDERS:
            return True
    except Exception:
        pass

    # If parent looks like migoto mod and this folder is Texture/Buffer -> skip
    parent = mod_dir.parent
    if parent.exists() and _looks_like_migoto_mod_folder(parent):
        if name in ("texture", "buffer"):
            return True

    return False


def _iter_real_mod_folders(mods_root: Path) -> List[Path]:
    mods_root = mods_root.resolve()
    if not mods_root.exists():
        return []

    deny_names = {"_active", "__pycache__", ".git"}
    candidates: List[Path] = []

    for d in mods_root.rglob("*"):
        if not d.is_dir():
            continue

        if d.name in deny_names:
            continue

        if "_active" in {p.name for p in d.parents}:
            continue

        if _is_container_folder(d, mods_root):
            continue

        if _is_subfolder_that_should_not_be_listed(d, mods_root):
            continue

        if not _folder_has_any_file(d):
            continue

        candidates.append(d)

    candidates = sorted(set(candidates), key=lambda p: (len(p.parts), str(p).lower()))
    candidate_set = set(candidates)

    final: List[Path] = []

    for d in candidates:
        # If a child dir is also a candidate, d might just be a container for multiple mods
        has_child_candidate = False
        for c in candidate_set:
            if c != d and d in c.parents:
                has_child_candidate = True
                break

        looks_like_mod = (
            _looks_like_migoto_mod_folder(d)
            or _looks_like_asset_mod_folder(d)
            or _looks_like_config_mod_folder(d)
        )

        if looks_like_mod:
            final.append(d)
            continue

        # If it doesn't look like a mod folder, keep only if leaf
        if not has_child_candidate:
            final.append(d)

    return final


def scan_mods(mods_root: Path) -> List[ModInfo]:
    mods_root = Path(mods_root).resolve()
    mods: List[ModInfo] = []

    for folder in _iter_real_mod_folders(mods_root):
        rel = folder.relative_to(mods_root)
        rel_norm = str(rel).replace("\\", "/")

        errors: List[str] = []
        warnings: List[str] = []

        if _looks_like_migoto_mod_folder(folder):
            mod_type = "migoto"
        elif _looks_like_asset_mod_folder(folder):
            mod_type = "asset"
        elif _looks_like_config_mod_folder(folder):
            mod_type = "config"
        else:
            mod_type = "folder"

        mods.append(
            ModInfo(
                name=folder.name,
                rel_path=rel_norm,
                mod_type=mod_type,
                errors=errors,
                warnings=warnings,
            )
        )

    order = {"migoto": 0, "asset": 1, "config": 2, "folder": 3}
    mods.sort(key=lambda m: (order.get(m.mod_type, 99), m.name.lower(), m.rel_path.lower()))
    return mods
