"""Entry point for `python -m bleck` and the frozen binary.

⚠️ The import must stay absolute: PyInstaller runs this as a top-level script,
where a relative import has no parent package and fails.
"""

from bleck.cli import main

raise SystemExit(main())
