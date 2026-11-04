"""Start the DC Minifiguren-Checkliste.

    python app.py              -> desktop app
    python app.py --cli ...    -> command line (fetch / pdf / list / smoke)
"""
import sys


def _ensure_streams() -> None:
    # In the packaged Windows/macOS app there is no console: sys.stdout and
    # sys.stderr are None, so send output to a log file in the data folder.
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        from dcchecklist.storage import data_dir
        log = open(data_dir() / "app.log", "a", encoding="utf-8", buffering=1)
    except Exception:
        import io
        log = io.StringIO()
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def run() -> int:
    _ensure_streams()
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        from dcchecklist.cli import main as cli_main
        return cli_main(sys.argv[2:])
    from dcchecklist.gui import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    sys.exit(run())
