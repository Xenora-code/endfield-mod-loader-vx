from __future__ import annotations
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListView, QLabel, QPushButton, QTextEdit, QLineEdit, QSplitter, QMessageBox
)

from launcher.core.config import AppConfig
from launcher.core.mods import ModInfo, scan_mods
from launcher.core.active_pack import build_active


class ModsModel(QAbstractListModel):
    def __init__(self, mods: List[ModInfo], cfg: AppConfig):
        super().__init__()
        self.mods = mods
        self.cfg = cfg
        self.filter = ""

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
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable

    def setData(self, index: QModelIndex, value, role: int) -> bool:
        if role == Qt.CheckStateRole:
            m = self.visible()[index.row()]
            self.cfg.set_enabled(m.rel_path, value == Qt.Checked)
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False


class MainWindow(QMainWindow):
    def __init__(self, project_root: Path):
        super().__init__()
        self.project_root = project_root
        self.mods_root = project_root / "mods"

        self.cfg = AppConfig.load(project_root)
        self.mods: List[ModInfo] = []
        self.model = ModsModel([], self.cfg)

        self.setWindowTitle("Endfield Mod Loader (Safe)")
        self.resize(1020, 680)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)

        # top bar
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mods...")
        self.search.textChanged.connect(self.on_search)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)

        self.btn_build = QPushButton("Build Active Pack")
        self.btn_build.clicked.connect(self.build_active_pack)

        top.addWidget(QLabel("Mods"))
        top.addStretch(1)
        top.addWidget(self.search)
        top.addWidget(self.btn_refresh)
        top.addWidget(self.btn_build)
        outer.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter, 1)

        # left list
        self.list_view = QListView()
        self.list_view.setModel(self.model)
        self.list_view.clicked.connect(self.on_select)
        splitter.addWidget(self.list_view)

        # right details
        right = QWidget()
        r = QVBoxLayout(right)

        self.details_title = QLabel("Select a mod")
        self.details_title.setStyleSheet("font-size:16px; font-weight:600;")
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setFixedHeight(240)

        self.active_title = QLabel("Enabled mods")
        self.active_box = QTextEdit()
        self.active_box.setReadOnly(True)
        self.active_box.setFixedHeight(140)

        self.log_title = QLabel("Log")
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        r.addWidget(self.details_title)
        r.addWidget(self.details)
        r.addWidget(self.active_title)
        r.addWidget(self.active_box)
        r.addWidget(self.log_title)
        r.addWidget(self.log, 1)

        splitter.addWidget(right)
        splitter.setSizes([480, 540])

        self.refresh()

    def on_search(self, text: str):
        self.model.filter = text.strip()
        self.model.layoutChanged.emit()

    def refresh(self):
        self.mods = scan_mods(self.mods_root)
        self.model.beginResetModel()
        self.model.mods = self.mods
        self.model.endResetModel()
        self.update_enabled_box()
        self.log.append(f"[Scan] Found {len(self.mods)} mods.")

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

    def build_active_pack(self):
        self.refresh()
        active = build_active(self.mods_root, self.cfg.enabled_mods)
        self.log.append(f"[Build] Active pack built at: {active}")
        QMessageBox.information(self, "Built", f"Active pack built:\n{active}")
        self.update_enabled_box()


def run():
    app = QApplication([])
    project_root = Path(__file__).resolve().parents[1]  # folder containing launcher/ and mods/
    win = MainWindow(project_root)
    win.show()
    app.exec()
