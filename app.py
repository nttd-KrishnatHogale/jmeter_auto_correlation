from __future__ import annotations

import sys

from jmeter_auto_correlation.self_test import run_self_test
from jmeter_auto_correlation.ui import main


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        run_self_test()
    else:
        main()
