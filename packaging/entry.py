"""Entry point of the frozen (PyInstaller) viewer.

The Windows build has no console window, so output goes to a log file, and a startup
failure is shown in a message box instead of disappearing silently.
"""

import sys
import traceback
from pathlib import Path


def _log_file() -> Path:
    import platformdirs

    d = Path(platformdirs.user_log_dir("lbd", appauthor=False, ensure_exists=True))
    log = d / "viewer.log"
    if log.exists() and log.stat().st_size > 1_000_000:
        log.replace(d / "viewer.old.log")
    return log


def _show_error(text: str) -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "LBD Viewer", 0x10)
    else:
        print(text, file=sys.stderr)


def main() -> int:
    log_path = None
    if sys.stdout is None or sys.stderr is None:
        log_path = _log_file()
        stream = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives for the process
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    try:
        from lbd_viewer.cli import main as cli_main

        return cli_main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - last-resort report for a windowed app
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        where = f"\n\nDetails were written to {log_path}" if log_path else ""
        _show_error(f"LBD Viewer could not start.\n\n{tb.strip().splitlines()[-1]}{where}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
