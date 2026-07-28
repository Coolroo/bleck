"""Allow `python -m bleck`, and serve as the frozen binary's entry point.

⚠️ The import is absolute rather than `from .cli import main`. PyInstaller runs
this file as a top-level script, where a relative import has no parent package
and fails with "attempted relative import with no known parent package" — a
message that says nothing about packaging. `python -m bleck` works either way.
"""

from bleck.cli import main

raise SystemExit(main())
