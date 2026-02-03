from __future__ import annotations

import json
import os
import shutil
import subprocess
import ctypes
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListView, QLabel, QPushButton, QTextEdit, QLineEdit, QSplitter,
    QMessageBox, QFileDialog, QAbstractItemView, QStyleOptionViewItem, QStyle,
    QComboBox
)

from launcher.core.config import AppConfig
from launcher.core.mods import ModInfo, scan_mods
from launcher.core.active_pack import build_active
from launcher.core.deploy import (
    deploy_endfield_modsafe,
    restore_endfield_modsafe,
    detect_enabled_path_conflicts,
    detect_enabled_asset_conflicts,
    deploy_assets_no_manifest,
    restore_assets_no_manifest,
    deploy_3dmigoto_folder_mods,
    get_modsafe_paths,
)

# =========================================================
# WinError 740 safe launcher (supports args)
# =========================================================

def launch_exe_windows(exe_path: Path, args: Optional[List[str]] = None) -> None:
    exe_path = Path(exe_path)
    cwd = str(exe_path.parent)
    params = " ".join(args or [])

    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", str(exe_path), params, cwd, 1)
    if rc <= 32:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(exe_path), params, cwd, 1)
        if rc <= 32:
            raise RuntimeError(f"ShellExecute failed (code {rc}).")


# =========================================================
# JSON helpers
# =========================================================

def json_load(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        raise ValueError(f"Empty JSON file: {path}")
    return json.loads(text)


def safe_rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


# =========================================================
# Renderer choice persistence (SELF-CONTAINED)
# =========================================================

RENDERER_FILE = "renderer.json"

def load_renderer_choice(project_root: Path) -> str:
    p = project_root / RENDERER_FILE
    if not p.exists():
        return "auto"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        v = str(d.get("renderer", "auto")).lower()
        return v if v in ("auto", "dx11", "dx12") else "auto"
    except Exception:
        return "auto"

def save_renderer_choice(project_root: Path, value: str) -> None:
    p = project_root / RENDERER_FILE
    p.write_text(json.dumps({"renderer": value}, indent=2), encoding="utf-8")


def build_renderer_args(choice: str) -> List[str]:
    choice = (choice or "auto").lower()
    if choice == "dx11":
        return ["-force-d3d11", "-force-feature-level-11-0"]
    if choice == "dx12":
        return ["-force-d3d12"]
    return []


# =========================================================
# ZIP Import helpers (GameBanana-style)
# =========================================================

_ALLOWED_ASSET_ROOTS = ("Endfield_Data", "resources", "game_files", "translations", "plugins")

def _dir_has_migoto_markers(p: Path) -> bool:
    if (p / "Texture").exists() or (p / "Buffer").exists() or (p / "d3dx.ini").exists():
        return True
    for f in p.rglob("*"):
        if f.is_file():
            n = f.name.lower()
            if n.endswith(".dds") or n.endswith(".buf"):
                return True
    return False

def _dir_has_asset_roots(p: Path) -> bool:
    for root in _ALLOWED_ASSET_ROOTS:
        if (p / root).exists():
            return True
    return False

def _unwrap_single_folder(root: Path) -> Path:
    """If zip extracted into a single top-level folder, descend into it (handles nested packaging)."""
    cur = root
    for _ in range(6):
        entries = [x for x in cur.iterdir() if x.name not in ("__MACOSX",) and not x.name.startswith(".")]
        dirs = [x for x in entries if x.is_dir()]
        files = [x for x in entries if x.is_file()]
        if len(dirs) == 1 and len(files) == 0:
            cur = dirs[0]
            continue
        break
    return cur

def _pick_best_mod_folder(extracted_root: Path) -> Tuple[Path, str]:
    """
    Chooses the folder we should copy into mods/misc/<name>.
    1) Prefer 3DMigoto markers (Texture/Buffer/d3dx.ini/.dds/.buf)
    2) Else prefer asset roots (Endfield_Data/, resources/, ...)
    3) Else fall back to unwrapped root
    """
    base = _unwrap_single_folder(extracted_root)

    if _dir_has_migoto_markers(base) or _dir_has_asset_roots(base):
        return base, base.name

    candidates: List[Path] = []
    for d in base.rglob("*"):
        if d.is_dir() and (_dir_has_migoto_markers(d) or _dir_has_asset_roots(d)):
            candidates.append(d)

    if candidates:
        candidates.sort(key=lambda p: (0 if _dir_has_migoto_markers(p) else 1, len(p.parts)))
        chosen = candidates[0]
        return chosen, chosen.name

    return base, base.name

def _unique_dest(parent: Path, name: str) -> Path:
    """Avoid overwrite by suffixing _1, _2..."""
    safe = "".join(c for c in name if c not in r'<>:"/\|?*').strip() or "ImportedMod"
    dest = parent / safe
    if not dest.exists():
        return dest
    for i in range(1, 1000):
        cand = parent / f"{safe}_{i}"
        if not cand.exists():
            return cand
    return parent / f"{safe}_{os.getpid()}"


# =========================================================
# Qt model/view
# =========================================================

class ModsModel(QAbstractListModel):
    def __init__(self, mods: List[ModInfo], cfg: AppConfig, on_toggle_cb, is_loading_fn, status_fn):
        super().__init__()
        self.mods = mods
        self.cfg = cfg
        self.filter = ""
        self.on_toggle_cb = on_toggle_cb
        self.is_loading_fn = is_loading_fn
        self.status_fn = status_fn
        self._user_toggle_gate = False

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self.visible())

    def visible(self) -> List[ModInfo]:
        if not self.filter:
            return self.mods
        f = self.filter.lower()
        return [m for m in self.mods if f in m.rel_path.lower() or f in m.name.lower()]

    def data(self, index: QModelIndex, role: int):
        m = self.visible()[index.row()]

        if role == Qt.DisplayRole:
            tag = f"[{m.mod_type.upper()}]"
            status = " [ERROR]" if m.errors else (" [WARN]" if m.warnings else "")
            return f"{m.name} {tag} — {m.rel_path}{status}"

        if role == Qt.CheckStateRole:
            return Qt.Checked if self.cfg.is_enabled(m.rel_path) else Qt.Unchecked

        if role == Qt.ToolTipRole:
            tips = [m.rel_path]
            if m.errors:
                tips.append("Errors:\n- " + "\n- ".join(m.errors))
            if m.warnings:
                tips.append("Warnings:\n- " + "\n- ".join(m.warnings))
            return "\n\n".join(tips)

        return None

    def flags(self, index: QModelIndex):
        m = self.visible()[index.row()]
        base = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        if m.errors:
            return base
        return base | Qt.ItemIsUserCheckable

    def setData(self, index: QModelIndex, value, role: int) -> bool:
        if role != Qt.CheckStateRole:
            return False
        if self.is_loading_fn():
            return False
        if not self._user_toggle_gate:
            return False

        m = self.visible()[index.row()]
        if m.errors and value == Qt.Checked:
            self.status_fn("Mod has errors — cannot enable")
            return False

        enabled = (value == Qt.Checked)
        self.cfg.set_enabled(m.rel_path, enabled)
        self.dataChanged.emit(index, index, [Qt.CheckStateRole])

        self.status_fn(f"{'Enabled' if enabled else 'Disabled'}: {m.rel_path}")
        self.on_toggle_cb()
        return True


class ModListView(QListView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)

    def mousePressEvent(self, event):
        idx = self.indexAt(event.pos())
        if idx.isValid():
            opt = QStyleOptionViewItem()
            self.itemDelegate().initStyleOption(opt, idx)
            opt.rect = self.visualRect(idx)

            style = self.style()
            check_rect = style.subElementRect(QStyle.SE_ItemViewItemCheckIndicator, opt, self)

            if check_rect.contains(event.pos()):
                model = self.model()
                current = model.data(idx, Qt.CheckStateRole)
                new_state = Qt.Unchecked if current == Qt.Checked else Qt.Checked

                model._user_toggle_gate = True
                try:
                    model.setData(idx, new_state, Qt.CheckStateRole)
                finally:
                    model._user_toggle_gate = False
                return

        super().mousePressEvent(event)


# =========================================================
# Main window
# =========================================================

class MainWindow(QMainWindow):
    FOLDER_NAME = "EndfieldModSafe"

    def __init__(self, project_root: Path):
        super().__init__()
        self.project_root = project_root
        self.mods_root = project_root / "mods"

        self.cfg = AppConfig.load(project_root)
        self.mods: List[ModInfo] = []

        self.renderer_choice = load_renderer_choice(self.project_root)

        self._loading_ui = False
        self.statusBar().showMessage("Ready")

        self._build_timer = QTimer()
        self._build_timer.setSingleShot(True)
        self._build_timer.timeout.connect(self._do_build_active)

        self.model = ModsModel(
            [],
            self.cfg,
            on_toggle_cb=self.queue_build_active,
            is_loading_fn=lambda: self._loading_ui,
            status_fn=self.set_status
        )

        self.setWindowTitle("Endfield Mod Loader (Safe + Asset Replacement)")
        self.resize(1180, 720)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)

        # ---------------- Top Bar ----------------
        top = QHBoxLayout()

        top.addWidget(QLabel("Actions"))

        self.actions = QComboBox()
        self.actions.addItems([
            "Install Mod Folder",
            "Build Active Pack",
            "Restore (Safe + Assets)",
            "Open Safe Deployed Folder",
        ])
        self.actions.setToolTip("Pick an action, then click Run")
        top.addWidget(self.actions)

        self.btn_run_action = QPushButton("← Run")
        self.btn_run_action.setToolTip("Runs the selected action from the dropdown")
        self.btn_run_action.clicked.connect(self.run_selected_action)
        top.addWidget(self.btn_run_action)

        self.btn_import_zip = QPushButton("Import Mod ZIP")
        self.btn_import_zip.clicked.connect(self.import_mod_zip)
        top.addWidget(self.btn_import_zip)

        self.btn_open_folder = QPushButton("Open Mod Folder")
        self.btn_open_folder.clicked.connect(self.open_selected_mod_folder)
        top.addWidget(self.btn_open_folder)

        top.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mods...")
        self.search.textChanged.connect(self.on_search)
        top.addWidget(self.search)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        top.addWidget(self.btn_refresh)

        self.renderer_combo = QComboBox()
        self.renderer_combo.addItems(["Renderer: Auto", "Renderer: Force DX11", "Renderer: Force DX12"])
        self.renderer_combo.setCurrentIndex(1 if self.renderer_choice == "dx11" else 2 if self.renderer_choice == "dx12" else 0)
        self.renderer_combo.currentIndexChanged.connect(self.on_renderer_changed)
        top.addWidget(self.renderer_combo)

        self.btn_deploy = QPushButton("Deploy Mods")
        self.btn_deploy.clicked.connect(self.deploy_all)
        top.addWidget(self.btn_deploy)

        self.btn_set_game = QPushButton("Set Game EXE")
        self.btn_set_game.clicked.connect(self.pick_game_exe)
        top.addWidget(self.btn_set_game)

        self.btn_launch = QPushButton("Launch Game")
        self.btn_launch.clicked.connect(self.launch_game)
        top.addWidget(self.btn_launch)

        outer.addLayout(top)

        # ---------------- Main Split ----------------
        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter, 1)

        self.list_view = ModListView()
        self.list_view.setModel(self.model)
        self.list_view.clicked.connect(self.on_select)
        splitter.addWidget(self.list_view)

        right = QWidget()
        r = QVBoxLayout(right)

        self.details_title = QLabel("Select a mod")
        self.details_title.setStyleSheet("font-size:16px; font-weight:600;")
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setFixedHeight(260)

        self.active_title = QLabel("Enabled mods")
        self.active_box = QTextEdit()
        self.active_box.setReadOnly(True)
        self.active_box.setFixedHeight(150)

        self.game_title = QLabel("Game EXE")
        self.game_box = QLineEdit()
        self.game_box.setReadOnly(True)

        self.log_title = QLabel("Log")
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        r.addWidget(self.details_title)
        r.addWidget(self.details)
        r.addWidget(self.active_title)
        r.addWidget(self.active_box)
        r.addWidget(self.game_title)
        r.addWidget(self.game_box)
        r.addWidget(self.log_title)
        r.addWidget(self.log, 1)

        splitter.addWidget(right)
        splitter.setSizes([520, 660])

        self.refresh()

    # =========================================================
    # Actions dropdown runner
    # =========================================================
    def run_selected_action(self):
        action = (self.actions.currentText() or "").strip()

        if action == "Install Mod Folder":
            self.install_mod_folder()
            return
        if action == "Build Active Pack":
            self.queue_build_active()
            return
        if action == "Restore (Safe + Assets)":
            self.restore_all()
            return
        if action == "Open Safe Deployed Folder":
            self.open_deployed_folder()
            return

        QMessageBox.information(self, "Unknown action", f"Unhandled action:\n{action}")

    # =========================================================
    # Log validation (red/green)
    # =========================================================
    def log_ok(self, msg: str) -> None:
        self._log_color(msg, color="#22c55e")

    def log_bad(self, msg: str) -> None:
        self._log_color(msg, color="#ef4444")

    def log_warn(self, msg: str) -> None:
        self._log_color(msg, color="#f59e0b")

    def log_info(self, msg: str) -> None:
        self._log_color(msg, color="#e5e7eb")

    def _log_color(self, msg: str, color: str) -> None:
        safe = (msg or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.log.append(f'<span style="color:{color};">{safe}</span>')

    def on_renderer_changed(self, idx: int):
        if idx == 1:
            self.renderer_choice = "dx11"
        elif idx == 2:
            self.renderer_choice = "dx12"
        else:
            self.renderer_choice = "auto"
        save_renderer_choice(self.project_root, self.renderer_choice)
        self.set_status(f"Renderer set: {self.renderer_choice}")

    def _game_root(self) -> Optional[Path]:
        if not self.cfg.game_exe:
            return None
        return Path(self.cfg.game_exe).resolve().parent

    def set_status(self, msg: str):
        count = len(self.cfg.enabled_mods)
        final = f"{msg} | Enabled mods: {count}"
        self.statusBar().showMessage(final)
        self.log_info(f"[Status] {final}")

    def _enabled_mods_have_errors(self) -> bool:
        enabled = {x.replace("\\", "/") for x in self.cfg.enabled_mods}
        by_rel = {m.rel_path.replace("\\", "/"): m for m in self.mods}
        return any(by_rel.get(rel) and by_rel[rel].errors for rel in enabled)

    def _check_conflicts(self) -> List[str]:
        conflicts = detect_enabled_path_conflicts(self.mods_root, self.cfg.enabled_mods)
        if not conflicts:
            return []
        lines: List[str] = []
        for c in conflicts[:50]:
            lines.append(f"{c.get('path','')}  <=  {', '.join(c.get('mods', []))}")
        self.set_status(f"Conflicts: {len(conflicts)} (Deploy blocked)")
        return lines

    def _check_asset_conflicts(self) -> List[str]:
        conflicts = detect_enabled_asset_conflicts(self.mods_root, self.cfg.enabled_mods)
        if not conflicts:
            return []
        lines: List[str] = []
        for c in conflicts[:50]:
            lines.append(f"{c.get('path','')}  <=  {', '.join(c.get('mods', []))}")
        self.set_status(f"Asset Conflicts: {len(conflicts)} (Deploy blocked)")
        return lines

    def on_search(self, text: str):
        self.model.filter = text.strip()
        self.model.layoutChanged.emit()

    def refresh(self):
        self._loading_ui = True
        self.list_view.blockSignals(True)

        self.mods = scan_mods(self.mods_root)
        self.model.beginResetModel()
        self.model.mods = self.mods
        self.model.endResetModel()

        self.list_view.blockSignals(False)
        self._loading_ui = False

        self.update_enabled_box()
        self.game_box.setText(self.cfg.game_exe or "")
        self.set_status(f"Scan: Found {len(self.mods)} mods")

    def update_enabled_box(self):
        enabled = sorted(self.cfg.enabled_mods)
        self.active_box.setText("\n".join(enabled) if enabled else "(none)")

    def on_select(self, index: QModelIndex):
        m = self.model.visible()[index.row()]
        self.details_title.setText(f"{m.name} — {m.rel_path}")

        lines = [
            f"Type: {m.mod_type}",
            f"Version: {m.version}",
            f"Author: {m.author}",
            "",
            m.description or ""
        ]
        if m.errors:
            lines += ["", "Errors:"] + [f"- {e}" for e in m.errors]
        if m.warnings:
            lines += ["", "Warnings:"] + [f"- {w}" for w in m.warnings]
        self.details.setText("\n".join([l for l in lines if l is not None]))

        self.set_status("Mod has errors — cannot enable" if m.errors else f"Selected: {m.rel_path}")

    def queue_build_active(self):
        self.update_enabled_box()
        self._build_timer.start(300)
        self.set_status("Build: queued...")

    def _do_build_active(self):
        active = build_active(self.mods_root, self.cfg.enabled_mods)
        self.set_status("Build: OK")
        self.log_info(f"[Build] Active pack built at: {active}")

    # =========================================================
    # Import Mod ZIP (GameBanana)
    # =========================================================
    def import_mod_zip(self):
        zip_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Mod ZIP",
            filter="ZIP/Archive Files (*.zip *.tar *.gz *.tgz);;All Files (*.*)"
        )
        if not zip_path:
            return

        zip_file = Path(zip_path)
        if not zip_file.exists():
            QMessageBox.warning(self, "Missing file", f"File not found:\n{zip_file}")
            return

        dest_parent = self.mods_root / "misc"
        dest_parent.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.TemporaryDirectory(prefix="endfield_mod_import_") as td:
                extract_root = Path(td)
                shutil.unpack_archive(str(zip_file), str(extract_root))

                chosen_dir, suggested_name = _pick_best_mod_folder(extract_root)

                generic = {"files", "file", "mod", "mods", "data", "release", "download"}
                name = suggested_name if suggested_name.lower() not in generic else zip_file.stem

                dest = _unique_dest(dest_parent, name)
                shutil.copytree(chosen_dir, dest, dirs_exist_ok=True)

                looks_migoto = _dir_has_migoto_markers(dest)
                looks_asset = _dir_has_asset_roots(dest)
                kind = "3DMigoto (Texture/Buffer)" if looks_migoto else ("Asset (Endfield_Data/...)" if looks_asset else "Folder")
                self.log_ok(f"[Import] Imported ZIP -> {dest} ({kind})")

            self.set_status(f"Imported: {zip_file.name}")
            self.refresh()

        except shutil.ReadError:
            QMessageBox.critical(
                self,
                "Import failed",
                "Could not unpack this archive.\n\n"
                "Only .zip/.tar/.gz supported by Python's unpacker.\n"
                "If it's a .rar or .7z, extract it manually first, then use 'Install Mod Folder'."
            )
        except Exception as e:
            QMessageBox.critical(self, "Import failed", str(e))

    # =========================================================
    # Deploy / Restore / Open
    # =========================================================
    def deploy_all(self):
        if not self.cfg.game_exe:
            QMessageBox.warning(self, "No game exe", "Click 'Set Game EXE' first.")
            return

        conflicts = self._check_conflicts()
        if conflicts:
            QMessageBox.warning(self, "Conflicts detected", "Fix these first:\n\n- " + "\n- ".join(conflicts))
            return

        asset_conflicts = self._check_asset_conflicts()
        if asset_conflicts:
            QMessageBox.warning(self, "Asset Conflicts detected", "Fix these first:\n\n- " + "\n- ".join(asset_conflicts))
            return

        if self._enabled_mods_have_errors():
            QMessageBox.warning(self, "Blocked", "One or more enabled mods has errors. Fix that first.")
            return

        if not self._game_root():
            QMessageBox.warning(self, "No game root", "Bad EXE path.")
            return

        try:
            self.set_status("Deploy: running...")
            self._do_build_active()

            result = deploy_endfield_modsafe(
                project_root=self.project_root,
                mods_root=self.mods_root,
                enabled_mods=self.cfg.enabled_mods,
                game_exe=self.cfg.game_exe,
                folder_name=self.FOLDER_NAME,
            )
            self.log_info(f"[SafeDeploy] {getattr(result, 'dest_active', '')}")

            migoto_files = deploy_3dmigoto_folder_mods(
                mods_root=self.mods_root,
                enabled_mods=list(self.cfg.enabled_mods),
                game_exe=self.cfg.game_exe,
                log_fn=self.log_info,
            )

            asset_files = deploy_assets_no_manifest(
                project_root=self.project_root,
                mods_root=self.mods_root,
                enabled_mods=list(self.cfg.enabled_mods),
                game_exe=self.cfg.game_exe,
                log_fn=self.log_info,
            )

            safe_count = int(getattr(result, "file_count", 0) or 0)
            if safe_count > 0:
                self.log_ok(f"[SafeDeploy] OK — {safe_count} file(s) active-mounted")
            else:
                self.log_warn("[SafeDeploy] Built active pack, but 0 files copied")

            if migoto_files > 0:
                self.log_ok(f"[3DMigoto] OK — {migoto_files} file(s) copied into game/Mods/")
            else:
                self.log_bad("[3DMigoto] NOT DEPLOYED — no Texture/Buffer/.dds/.buf/d3dx.ini detected in enabled mod(s)")

            if asset_files > 0:
                self.log_ok(f"[Assets] OK — {asset_files} file(s) replaced in game folder")
            else:
                self.log_warn("[Assets] No asset files deployed (must be under Endfield_Data/resources/game_files/etc).")

            self.set_status(f"Deploy: OK (migoto: {migoto_files}, assets: {asset_files})")

        except PermissionError as e:
            QMessageBox.critical(self, "Deploy failed", f"Permission denied.\n\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "Deploy failed", str(e))

    def restore_all(self):
        if not self.cfg.game_exe:
            QMessageBox.warning(self, "No game exe", "Click 'Set Game EXE' first.")
            return
        try:
            restore_endfield_modsafe(self.cfg.game_exe, folder_name=self.FOLDER_NAME)
            self.log_ok("[SafeDeploy] Restored mounted active folder")

            restored = restore_assets_no_manifest(
                project_root=self.project_root,
                game_exe=self.cfg.game_exe,
                log_fn=self.log_info,
                clear_receipt=True,
            )
            self.log_ok(f"[Assets] Restored/removed: {restored}" if restored > 0 else "[Assets] Nothing restored/removed (receipt empty)")

            self.set_status("Restore: OK")
        except Exception as e:
            QMessageBox.critical(self, "Restore failed", str(e))

    def open_deployed_folder(self):
        if not self.cfg.game_exe:
            QMessageBox.warning(self, "No game exe", "Click 'Set Game EXE' first.")
            return
        backend, safe_root, dest_active = get_modsafe_paths(self.cfg.game_exe, self.FOLDER_NAME)
        if not dest_active.exists():
            QMessageBox.information(self, "Not deployed yet", f"Deployed folder not found:\n{dest_active}\n\nClick Deploy first.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(dest_active)))
        self.set_status(f"Opened deployed folder ({backend})")

    def open_selected_mod_folder(self):
        idx = self.list_view.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self, "No selection", "Select a mod first.")
            return
        m = self.model.visible()[idx.row()]
        folder = (self.mods_root / m.rel_path).resolve()
        if not folder.exists():
            QMessageBox.warning(self, "Missing folder", f"Folder not found:\n{folder}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        self.set_status(f"Opened: {m.rel_path}")

    # =========================================================
    # Install folder / Game EXE / Launch
    # =========================================================
    def install_mod_folder(self):
        src = QFileDialog.getExistingDirectory(self, "Select Mod Folder to Install")
        if not src:
            return

        src_path = Path(src)
        dest_parent = (self.mods_root / "misc")
        dest_parent.mkdir(parents=True, exist_ok=True)

        dest = dest_parent / src_path.name
        if dest.exists():
            res = QMessageBox.question(self, "Overwrite?", f"{dest} already exists.\nOverwrite it?")
            if res != QMessageBox.Yes:
                return
            shutil.rmtree(dest)

        shutil.copytree(src_path, dest)
        self.set_status(f"Installed: {src_path.name}")
        self.refresh()

    def pick_game_exe(self):
        exe, _ = QFileDialog.getOpenFileName(self, "Select Game EXE", filter="EXE Files (*.exe)")
        if not exe:
            return
        self.cfg.set_game_exe(exe)
        self.game_box.setText(exe)
        self.set_status("Game EXE set")

    def launch_game(self):
        exe = self.cfg.game_exe
        if not exe:
            QMessageBox.warning(self, "No game exe", "Click 'Set Game EXE' first.")
            return

        exe_path = Path(exe)
        if not exe_path.exists():
            QMessageBox.warning(self, "Missing exe", f"EXE not found:\n{exe}")
            return

        self.deploy_all()

        args = build_renderer_args(self.renderer_choice)
        self.log_info(f"[Launch] Renderer args: {' '.join(args)}" if args else "[Launch] Renderer args: (none)")

        try:
            if os.name == "nt":
                launch_exe_windows(exe_path, args=args)
            else:
                subprocess.Popen([str(exe_path), *args], cwd=str(exe_path.parent))
            self.set_status("Launch: OK")
        except Exception as e:
            QMessageBox.critical(self, "Launch failed", str(e))


def run():
    app = QApplication([])
    project_root = Path(__file__).resolve().parents[1]
    win = MainWindow(project_root)
    win.show()
    app.exec()
