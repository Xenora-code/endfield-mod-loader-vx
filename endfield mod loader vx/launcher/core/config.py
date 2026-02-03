from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class AppConfig:
    config_path: Path
    enabled_mods: List[str] = field(default_factory=list)   # e.g. "configs/EstellaMod"
    game_exe: Optional[str] = None                          # full path string
    current_preset: str = "A"                               # "A" / "B" / "C"

    @staticmethod
    def load(project_root: Path) -> "AppConfig":
        data_dir = project_root / "launcher" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = data_dir / "config.json"

        if cfg_path.exists():
            # BOM-safe
            data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            enabled = data.get("enabled_mods", [])
            if not isinstance(enabled, list):
                enabled = []
            enabled = [str(x).replace("\\", "/") for x in enabled]

            game_exe = data.get("game_exe")
            if game_exe is not None:
                game_exe = str(game_exe)

            preset = str(data.get("current_preset") or "A").upper()
            if preset not in ("A", "B", "C"):
                preset = "A"

            return AppConfig(cfg_path, enabled, game_exe, preset)

        cfg = AppConfig(cfg_path, [], None, "A")
        cfg.save()
        return cfg

    def save(self) -> None:
        self.config_path.write_text(
            json.dumps(
                {
                    "enabled_mods": self.enabled_mods,
                    "game_exe": self.game_exe,
                    "current_preset": self.current_preset,
                },
                indent=2
            ),
            encoding="utf-8"
        )

    def is_enabled(self, rel_path: str) -> bool:
        rel_path = rel_path.replace("\\", "/")
        return rel_path in self.enabled_mods

    def set_enabled(self, rel_path: str, enabled: bool) -> None:
        rel_path = rel_path.replace("\\", "/")
        if enabled and rel_path not in self.enabled_mods:
            self.enabled_mods.append(rel_path)
        if (not enabled) and rel_path in self.enabled_mods:
            self.enabled_mods.remove(rel_path)
        self.save()

    def set_game_exe(self, exe_path: str | None) -> None:
        self.game_exe = exe_path
        self.save()

    # ---------- Presets ----------
    def _preset_path(self, name: str) -> Path:
        name = str(name).strip().upper()
        if name not in ("A", "B", "C"):
            name = "A"
        return self.config_path.parent / f"preset_{name}.json"

    def save_preset(self, name: str) -> None:
        name = str(name).strip().upper()
        if name not in ("A", "B", "C"):
            name = "A"
        p = self._preset_path(name)
        payload = {"enabled_mods": [x.replace("\\", "/") for x in self.enabled_mods]}
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.current_preset = name
        self.save()

    def load_preset(self, name: str) -> None:
        name = str(name).strip().upper()
        if name not in ("A", "B", "C"):
            name = "A"
        p = self._preset_path(name)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8-sig"))
            enabled = data.get("enabled_mods", [])
            if not isinstance(enabled, list):
                enabled = []
            self.enabled_mods = [str(x).replace("\\", "/") for x in enabled]
        else:
            self.enabled_mods = []
        self.current_preset = name
        self.save()
