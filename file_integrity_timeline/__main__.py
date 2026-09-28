import sys

if len(sys.argv) == 1:
    from .gui import run_gui

    run_gui()
else:
    from .cli import main

    raise SystemExit(main())
