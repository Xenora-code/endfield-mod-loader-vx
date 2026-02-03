from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path  # ✅ FIX: Path is defined now
from typing import Callable, Dict, List, Optional, Tuple


# =========================================================
# Existing ModSafe deploy (VFS / StreamingAssets)
# =========================================================

@dataclass
class DeployResult:
    safe_root: Path          # .../Endfield_Data/Persistent/VFS/EndfieldModSafe
    dest_active: Path        # .../Endfield_Data/Persistent/VFS/EndfieldModSafe/active
    receipt_path: Path       # .../Endfield_Data/Persistent/VFS/EndfieldModSafe/receipt.json
    file_count: int
    backend: str             # "vfs" or "streamingassets"


def _read_json(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig", errors="ignore").strip()
    if not text:
        return {}
    return json.loads(text)


def _copy_tree_merge(src: Path, dst: Path) -> int:
    """
    Copy src -> dst (recursive), overwrite files, create folders as needed.
    Returns number of files copied.
    """
    count = 0
    if not src.exists():
        return 0

    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return 1

    for p in src.rglob("*"):
        rel = p.relative_to(src)
        out = dst / rel
        if p.is_dir():
            out.mkdir(parents=True, exist_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)
            count += 1
    return count


def _pick_backend_root(game_exe: str) -> Tuple[str, Path]:
    """
    Prefer Endfield_Data/Persistent/VFS if it exists,
    otherwise fall back to Endfield_Data/StreamingAssets.
    """
    game_root = Path(game_exe).resolve().parent
    endfield_data = game_root / "Endfield_Data"

    vfs_root = endfield_data / "Persistent" / "VFS"
    if vfs_root.exists():
        return "vfs", vfs_root

    sa_root = endfield_data / "StreamingAssets"
    sa_root.mkdir(parents=True, exist_ok=True)
    return "streamingassets", sa_root


def get_modsafe_paths(game_exe: str, folder_name: str = "EndfieldModSafe") -> Tuple[str, Path, Path]:
    """
    Returns (backend, safe_root, dest_active)
    """
    backend, base = _pick_backend_root(game_exe)
    safe_root = (base / folder_name).resolve()
    dest_active = (safe_root / "active").resolve()
    return backend, safe_root, dest_active


def deploy_endfield_modsafe(
    project_root: Path,
    mods_root: Path,
    enabled_mods: List[str],
    game_exe: str,
    folder_name: str = "EndfieldModSafe",
) -> DeployResult:
    """
    Copies the project's built active pack into the game's *real* mount location:
    - Prefer: Endfield_Data/Persistent/VFS/<folder_name>/active
    - Fallback: Endfield_Data/StreamingAssets/<folder_name>/active

    Assumes build_active() creates: <project>/mods/_active/...
    """
    backend, safe_root, dest_active = get_modsafe_paths(game_exe, folder_name)
    safe_root.mkdir(parents=True, exist_ok=True)
    dest_active.mkdir(parents=True, exist_ok=True)

    src_active = (mods_root / "_active").resolve()
    if not src_active.exists():
        raise FileNotFoundError(f"Active pack not found: {src_active} (run Build first)")

    # Clean old active so removed mods don't linger
    if dest_active.exists():
        shutil.rmtree(dest_active)
    dest_active.mkdir(parents=True, exist_ok=True)

    file_count = _copy_tree_merge(src_active, dest_active)

    receipt = {
        "folder_name": folder_name,
        "backend": backend,
        "safe_root": str(safe_root),
        "dest_active": str(dest_active),
        "enabled_mods": [m.replace("\\", "/") for m in enabled_mods],
        "source_active": str(src_active),
        "file_count": file_count,
    }
    receipt_path = (safe_root / "receipt.json").resolve()
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    return DeployResult(
        safe_root=safe_root,
        dest_active=dest_active,
        receipt_path=receipt_path,
        file_count=file_count,
        backend=backend,
    )


def restore_endfield_modsafe(game_exe: str, folder_name: str = "EndfieldModSafe") -> bool:
    """
    Removes <folder_name>/active from the backend root if present.
    Returns True if something was removed.
    """
    backend, safe_root, dest_active = get_modsafe_paths(game_exe, folder_name)
    removed = False

    if dest_active.exists():
        shutil.rmtree(dest_active)
        removed = True

    # Optional: keep safe_root for receipt/history; remove if empty
    try:
        if safe_root.exists() and not any(safe_root.iterdir()):
            safe_root.rmdir()
    except Exception:
        pass

    return removed


# =========================================================
# Existing conflict detection (ModSafe/_active style)
# =========================================================

def _list_manifest_copy_paths(mod_folder: Path) -> List[str]:
    """
    Legacy: Reads manifest.json 'copy' list, returns normalized relative destinations.
    If no manifest or no 'copy', returns [].
    """
    manifest = mod_folder / "manifest.json"
    if not manifest.exists():
        return []
    data = _read_json(manifest)
    copy_list = data.get("copy") or []
    out: List[str] = []
    for item in copy_list:
        if not isinstance(item, str):
            continue
        norm = item.replace("\\", "/").lstrip("/")
        if norm:
            out.append(norm)
    return out


def detect_enabled_path_conflicts(mods_root: Path, enabled_mods: List[str]) -> List[dict]:
    """
    Conflict detector (ModSafe style):
    - Uses manifest.json 'copy' entries IF they exist.
    If your mods don't use manifests, this won't block you.
    """
    writers: Dict[str, List[str]] = {}

    for rel in enabled_mods:
        rel_norm = rel.replace("\\", "/").strip("/")
        mod_folder = (mods_root / rel_norm).resolve()
        if not mod_folder.exists():
            continue

        copy_entries = _list_manifest_copy_paths(mod_folder)
        if not copy_entries:
            continue

        for entry in copy_entries:
            src = mod_folder / entry
            dest_base = Path(rel_norm) / entry

            if src.exists() and src.is_dir():
                for f in src.rglob("*"):
                    if f.is_file():
                        sub = f.relative_to(mod_folder)
                        key = str(sub).replace("\\", "/")
                        writers.setdefault(key, []).append(rel_norm)
            else:
                key = str(dest_base).replace("\\", "/")
                writers.setdefault(key, []).append(rel_norm)

    conflicts = []
    for path, mods in writers.items():
        uniq = sorted(set(mods))
        if len(uniq) > 1:
            conflicts.append({"path": path, "mods": uniq})

    conflicts.sort(key=lambda x: x["path"])
    return conflicts


# =========================================================
# NEW: 3DMigoto folder-mod deploy (NO manifest.json)
# =========================================================

def _looks_like_migoto_mod_folder(mod_dir: Path) -> bool:
    """
    True if folder contains typical 3DMigoto structure:
      - Buffer/ or Texture/ folder
      - or any .buf/.dds files anywhere
      - or a d3dx.ini
    """
    if (mod_dir / "Buffer").exists() or (mod_dir / "Texture").exists():
        return True
    if (mod_dir / "d3dx.ini").exists():
        return True
    for p in mod_dir.rglob("*"):
        if p.is_file():
            s = p.name.lower()
            if s.endswith(".buf") or s.endswith(".dds"):
                return True
    return False


def deploy_3dmigoto_folder_mods(
    mods_root: Path,
    enabled_mods: List[str],
    game_exe: str,
    log_fn: Callable[[str], None],
) -> int:
    """
    Copies enabled 3DMigoto folder-mods to:
      <game_root>/Mods/<ModName>/...

    NO manifest required.
    Returns number of files copied.
    """
    game_root = Path(game_exe).resolve().parent
    mods_out = game_root / "Mods"
    mods_out.mkdir(parents=True, exist_ok=True)

    deployed = 0
    total_files = 0

    for rel in enabled_mods:
        rel_norm = rel.replace("\\", "/").strip("/")
        src_mod_dir = (mods_root / rel_norm).resolve()
        if not src_mod_dir.exists():
            continue

        if not _looks_like_migoto_mod_folder(src_mod_dir):
            continue

        mod_name = src_mod_dir.name
        dst_mod_dir = (mods_out / mod_name).resolve()

        if dst_mod_dir.exists():
            shutil.rmtree(dst_mod_dir, ignore_errors=True)
        dst_mod_dir.mkdir(parents=True, exist_ok=True)

        shutil.copytree(src_mod_dir, dst_mod_dir, dirs_exist_ok=True)
        n = sum(1 for p in dst_mod_dir.rglob("*") if p.is_file())

        deployed += 1
        total_files += n
        log_fn(f"[3DMigoto] Folder mod deployed: {mod_name} ({n} files) -> {dst_mod_dir}")

    if deployed == 0:
        log_fn("[3DMigoto] No folder-style mods detected (Buffer/Texture/.buf/.dds/d3dx.ini).")
    else:
        log_fn(f"[3DMigoto] Total: {deployed} mod(s), {total_files} files -> {mods_out}")

    return total_files


# =========================================================
# NEW: Unity asset replacement deploy + receipt restore (NO manifest.json)
# =========================================================

LogFn = Callable[[str], None]

ASSET_RECEIPT_DIRNAME = "deploy"          # project_root/deploy
ASSET_RECEIPT_NAME = "receipt.json"       # project_root/deploy/receipt.json
ASSET_BACKUP_DIRNAME = "backup"           # project_root/deploy/backup/...

_ALLOWED_ASSET_ROOTS = (
    "Endfield_Data/",
    "resources/",
    "game_files/",
    "translations/",
    "plugins/",
)


def _project_deploy_dir(project_root: Path) -> Path:
    return (project_root / ASSET_RECEIPT_DIRNAME).resolve()


def _load_asset_receipt(deploy_dir: Path) -> dict:
    deploy_dir.mkdir(parents=True, exist_ok=True)
    p = deploy_dir / ASSET_RECEIPT_NAME
    if not p.exists():
        return {"files": {}}
    try:
        data = _read_json(p)
        if not isinstance(data, dict):
            return {"files": {}}
        data.setdefault("files", {})
        if not isinstance(data["files"], dict):
            data["files"] = {}
        return data
    except Exception:
        return {"files": {}}


def _save_asset_receipt(deploy_dir: Path, data: dict) -> None:
    deploy_dir.mkdir(parents=True, exist_ok=True)
    p = deploy_dir / ASSET_RECEIPT_NAME
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_allowed_asset_relpath(rel_game_path: str) -> bool:
    rel_game_path = rel_game_path.replace("\\", "/").lstrip("/")
    return any(rel_game_path.startswith(root) for root in _ALLOWED_ASSET_ROOTS)


def _backup_original_once(
    game_root: Path,
    deploy_dir: Path,
    rel_game_path: str,
    log_fn: Optional[LogFn] = None,
) -> Optional[str]:
    rel_game_path = rel_game_path.replace("\\", "/").lstrip("/")
    src = game_root / rel_game_path
    if not src.exists():
        return None

    backup_rel = f"{ASSET_BACKUP_DIRNAME}/{rel_game_path}"
    backup_abs = deploy_dir / backup_rel
    if backup_abs.exists():
        return backup_rel

    backup_abs.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, backup_abs, dirs_exist_ok=True)
    else:
        shutil.copy2(src, backup_abs)

    if log_fn:
        log_fn(f"[Backup] Saved original -> {backup_abs}")
    return backup_rel


def deploy_assets_with_receipt(
    project_root: Path,
    mods_root: Path,
    enabled_mods: List[str],
    game_exe: str,
    log_fn: LogFn,
) -> int:
    game_root = Path(game_exe).resolve().parent
    deploy_dir = _project_deploy_dir(project_root)

    receipt = _load_asset_receipt(deploy_dir)
    files_map: Dict[str, dict] = receipt.setdefault("files", {})

    copied_total = 0
    deployed_mods = 0

    for rel in enabled_mods:
        rel_norm = rel.replace("\\", "/").strip("/")
        mod_dir = (mods_root / rel_norm).resolve()
        if not mod_dir.exists():
            continue

        files = []
        for p in mod_dir.rglob("*"):
            if not p.is_file():
                continue
            rel_game_path = str(p.relative_to(mod_dir)).replace("\\", "/")
            if _is_allowed_asset_relpath(rel_game_path):
                files.append((p, rel_game_path))

        if not files:
            continue

        copied_this = 0
        for src, rel_game_path in files:
            dst = (game_root / rel_game_path).resolve()

            backup_rel = _backup_original_once(game_root, deploy_dir, rel_game_path, log_fn=log_fn)

            entry = files_map.get(rel_game_path) or {}
            entry["backup"] = backup_rel if backup_rel else entry.get("backup", None)

            mods_list = entry.get("mods") or []
            if isinstance(mods_list, str):
                mods_list = [mods_list]
            if rel_norm not in mods_list:
                mods_list.append(rel_norm)
            entry["mods"] = mods_list

            files_map[rel_game_path] = entry

            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied_total += 1
            copied_this += 1
            log_fn(f"[Assets] Deployed file: {rel_game_path}")

        deployed_mods += 1
        log_fn(f"[Assets] Mod applied: {rel_norm} ({copied_this} file(s))")

    _save_asset_receipt(deploy_dir, receipt)

    if deployed_mods == 0:
        log_fn("[Assets] No asset files deployed (must be under Endfield_Data/resources/game_files/etc).")
    else:
        log_fn(f"[Assets] Total deployed: {deployed_mods} mod(s), {copied_total} file(s)")

    return copied_total


def restore_assets_with_receipt(
    project_root: Path,
    game_exe: str,
    log_fn: LogFn,
    clear_receipt: bool = True,
) -> int:
    game_root = Path(game_exe).resolve().parent
    deploy_dir = _project_deploy_dir(project_root)

    receipt = _load_asset_receipt(deploy_dir)
    files_map: Dict[str, dict] = receipt.get("files", {}) if isinstance(receipt, dict) else {}
    if not files_map:
        log_fn("[Restore] Nothing to restore (asset receipt is empty).")
        return 0

    restored = 0

    for rel_game_path, entry in list(files_map.items()):
        rel_game_path = str(rel_game_path).replace("\\", "/").lstrip("/")
        dst = game_root / rel_game_path

        backup_rel = entry.get("backup") if isinstance(entry, dict) else None

        if backup_rel:
            backup_abs = deploy_dir / str(backup_rel)
            if backup_abs.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                if backup_abs.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(backup_abs, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(backup_abs, dst)
                restored += 1
                log_fn(f"[Restore] Restored: {rel_game_path}")
            else:
                log_fn(f"[Restore] Missing backup (skipped): {rel_game_path}")
        else:
            if dst.exists():
                try:
                    if dst.is_dir():
                        shutil.rmtree(dst, ignore_errors=True)
                    else:
                        dst.unlink()
                    restored += 1
                    log_fn(f"[Restore] Removed created: {rel_game_path}")
                except Exception as e:
                    log_fn(f"[Restore] Failed to remove {rel_game_path}: {e}")

    if clear_receipt:
        _save_asset_receipt(deploy_dir, {"files": {}})
        log_fn("[Restore] Asset receipt cleared.")

    log_fn(f"[Restore] Done. Restored/removed: {restored} item(s).")
    return restored


def detect_enabled_asset_conflicts(mods_root: Path, enabled_mods: List[str]) -> List[dict]:
    writers: Dict[str, List[str]] = {}

    for rel in enabled_mods:
        rel_norm = rel.replace("\\", "/").strip("/")
        mod_dir = (mods_root / rel_norm).resolve()
        if not mod_dir.exists():
            continue

        for p in mod_dir.rglob("*"):
            if not p.is_file():
                continue
            rel_game_path = str(p.relative_to(mod_dir)).replace("\\", "/")
            if not _is_allowed_asset_relpath(rel_game_path):
                continue
            writers.setdefault(rel_game_path, []).append(rel_norm)

    conflicts = []
    for path, mods in writers.items():
        uniq = sorted(set(mods))
        if len(uniq) > 1:
            conflicts.append({"path": path, "mods": uniq})

    conflicts.sort(key=lambda x: x["path"])
    return conflicts


# =========================================================
# Compatibility aliases (OPTION B)
# =========================================================

def deploy_assets_no_manifest(
    project_root: Path,
    mods_root: Path,
    enabled_mods: List[str],
    game_exe: str,
    log_fn,
) -> int:
    return deploy_assets_with_receipt(
        project_root=project_root,
        mods_root=mods_root,
        enabled_mods=enabled_mods,
        game_exe=game_exe,
        log_fn=log_fn,
    )


def restore_assets_no_manifest(
    project_root: Path,
    game_exe: str,
    log_fn,
    clear_receipt: bool = True,
) -> int:
    return restore_assets_with_receipt(
        project_root=project_root,
        game_exe=game_exe,
        log_fn=log_fn,
        clear_receipt=clear_receipt,
    )
