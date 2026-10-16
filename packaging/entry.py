"""Entry point of the frozen (PyInstaller) viewer.

The Windows build has no console window, so output goes to a log file, and a startup
failure is shown in a message box instead of disappearing silently (an alert on macOS).
The macOS app, started by Finder, runs lbd_viewer.macapp; with arguments it is the usual CLI.
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
    elif sys.platform == "darwin" and getattr(sys, "frozen", False):
        import subprocess

        quoted = text.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display alert "LBD Viewer" message "{quoted}" as critical'])
    else:
        print(text, file=sys.stderr)


def finder_launch() -> bool:
    """True when Finder or the Dock started the macOS app: it then gets its files as "open
    documents" events, not as arguments (macapp.py). Older macOS adds a "-psn_..." argument."""
    real_args = [a for a in sys.argv[1:] if not a.startswith("-psn_")]
    return sys.platform == "darwin" and bool(getattr(sys, "frozen", False)) and not real_args


def main() -> int:
    log_path = None
    # Apps without a console (Windows, or the macOS app started by Finder) write to a log file.
    if sys.stdout is None or sys.stderr is None or finder_launch():
        log_path = _log_file()
        stream = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives for the process
        # Finder connects the app's output to nothing visible, so replace it there too.
        sys.stdout = stream if finder_launch() or sys.stdout is None else sys.stdout
        sys.stderr = stream if finder_launch() or sys.stderr is None else sys.stderr
    try:
        if finder_launch():
            from lbd_viewer import macapp

            return macapp.run()
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
