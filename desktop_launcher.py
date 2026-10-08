"""Frozen entry point: multiprocessing capture workers must not open a window."""

import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from fulcrum.desktop import main
    raise SystemExit(main())
