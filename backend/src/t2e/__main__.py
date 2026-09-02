"""Allow `python -m t2e` as an equivalent to the `t2e` console script."""

import sys

from t2e.cli import main

if __name__ == "__main__":
    sys.exit(main())
