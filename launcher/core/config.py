from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

@dataclass
class AppConfig:
    config_path: Path
    enabled_mods: List[str] = field(default_factory=list)  # e.g. "configs/EstellaMod"

    @staticmethod
    def load(project_root: Path) -> "AppConfig":
        data_dir = project_root / "launcher" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        cfg_path = data_dir / "config.json"

        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            enabled = data.get("enabled_mods", [])
            if not isinstance(enabled, list):
                enabled = []
            return AppConfig(cfg_path, [str(x).replace("\\", "/") for x in enabled])

        cfg = AppConfig(cfg_path, [])
        cfg.save()
        return cfg

    def save(self) -> None:
        self.config_path.write_text(
            json.dumps({"enabled_mods": self.enabled_mods}, indent=2),
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
