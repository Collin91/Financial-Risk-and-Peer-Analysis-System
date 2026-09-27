"""Entry point: `python main.py` starts the guided setup; `python main.py --help` lists the options."""

import sys

from financial_analyzer.cli import main

if __name__ == "__main__":
    sys.exit(main())
