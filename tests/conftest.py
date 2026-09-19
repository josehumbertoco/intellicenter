"""Make the testbench importable under pytest as well as tests/run.py."""

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
for path in (HERE / "_stubs", HERE.parent, HERE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
