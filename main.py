"""入口：python main.py"""
import sys

from PySide6.QtWidgets import QApplication

from investapp.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("投资年化收益计算")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
