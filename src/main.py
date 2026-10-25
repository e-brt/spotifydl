"""Entry point: the application window, or the spotDL worker (--spotdl-worker)
or the packaged build check (--self-check) when started with those options."""

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from main_window import APP_NAME, MainWindow
from resources import resource_path
from version import __version__


def run_spotdl_worker():
    """Run spotDL in a child process so the GUI can capture logs and stop it."""
    import worker

    worker.run(sys.argv[2:])


def main():
    if "--spotdl-worker" in sys.argv:
        run_spotdl_worker()
        return
    if "--self-check" in sys.argv:
        import worker

        sys.exit(worker.self_check())

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)

    icon_path = resource_path("assets", "spotifydownloader.ico")
    icon = QIcon(str(icon_path))

    if icon.isNull():
        print(f"ERROR: Icon could not be loaded: {icon_path}")
    else:
        app.setWindowIcon(icon)

    window = MainWindow()
    window.setWindowIcon(icon)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
