"""Entry point: `python main.py` starts the guided setup; `python main.py --help` lists the options."""

import sys

# Checked before importing the package, which uses syntax older Pythons can't parse.
# Keep this block free of newer syntax (no f-strings) so even very old Pythons reach the message.
if sys.version_info < (3, 9):
    sys.stderr.write(
        "This program needs Python 3.9 or newer. You are running Python %d.%d.\n"
        "Download a newer version from https://www.python.org/downloads/\n" % sys.version_info[:2]
    )
    sys.exit(1)

from financial_analyzer.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
