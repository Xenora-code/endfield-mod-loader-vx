from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class ModInfo:
    rel_path: str
    folder: Path
    name: str
    version: str
    author: str
    description: str
    mod_type: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def scan_mods(mods_root: Path) -> List[ModInfo]:
    mods_root.mkdir(parents=True, exist_ok=True)
    found: List[ModInfo] = []

    for manifest in mods_root.rglob("manifest.json"):
        # 🚫 Ignore generated active pack
        if "_active" in manifest.parts:
            continue

        folder = manifest.parent
        rel = str(folder.relative_to(mods_root)).replace("\\", "/")
        errors: List[str] = []
        warnings: List[str] = []

        try:
            text = manifest.read_text(encoding="utf-8-sig").strip()
            if not text:
                raise ValueError("manifest.json is empty")
            data = json.loads(text)
            
        except Exception as e:
            found.append(
                ModInfo(
                    rel_path=rel,
                    folder=folder,
                    name=folder.name,
                    version="?",
                    author="",
                    description="",
                    mod_type="unknown",
                    errors=[f"manifest.json parse error: {e}"],
                    warnings=[],
                )
            )
            continue

        name = data.get("name") or folder.name
        version = data.get("version") or "0.0.0"
        author = data.get("author") or ""
        description = data.get("description") or ""
        mod_type = str(data.get("type") or "folder").lower()

        # Validation
        if not data.get("id"):
            warnings.append("Missing 'id' in manifest (recommended).")

        if mod_type == "config":
            copy = data.get("copy", [])
            if not isinstance(copy, list) or len(copy) == 0:
                warnings.append("type=config but 'copy' list is empty.")

        found.append(
            ModInfo(
                rel_path=rel,
                folder=folder,
                name=str(name),
                version=str(version),
                author=str(author),
                description=str(description),
                mod_type=mod_type,
                errors=errors,
                warnings=warnings,
            )
        )

    found.sort(key=lambda m: m.rel_path.lower())
    return found
