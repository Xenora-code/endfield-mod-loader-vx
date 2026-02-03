from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from launcher.gui import MainWindow


def main() -> None:
    app = QApplication(sys.argv)

    # Project root = one level above /launcher
    project_root = Path(__file__).resolve().parents[1]

    win = MainWindow(project_root)
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
