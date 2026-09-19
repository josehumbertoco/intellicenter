#!/usr/bin/env python3
"""Run the whole testbench. No third party dependency required.

    python3 tests/run.py            # everything
    python3 tests/run.py protocol   # only modules matching "protocol"
    python3 tests/run.py -v         # show every check

Tests are plain ``test_*`` functions using ``assert``; the async ones drive
their own event loop, so ``pytest tests/`` also works if you have it, without
needing an asyncio plugin.
"""

import importlib
import pathlib
import sys
import time
import traceback

HERE = pathlib.Path(__file__).resolve().parent
# stubs first: they stand in for a Home Assistant install
sys.path.insert(0, str(HERE / "_stubs"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

GREEN, RED, DIM, BOLD, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = DIM = BOLD = OFF = ""


def main(argv):
    verbose = "-v" in argv or "--verbose" in argv
    filters = [a for a in argv if not a.startswith("-")]

    # several tests deliberately provoke errors the integration logs; keep the
    # output readable unless the run is verbose
    import logging
    logging.disable(logging.NOTSET if verbose else logging.CRITICAL)

    modules = sorted(p.stem for p in HERE.glob("test_*.py"))
    if filters:
        modules = [m for m in modules
                   if any(f.lower() in m.lower() for f in filters)]
    if not modules:
        print("no test modules matched")
        return 1

    passed = failed = 0
    failures = []
    started = time.monotonic()

    for name in modules:
        module = importlib.import_module(name)
        tests = [(n, getattr(module, n)) for n in sorted(vars(module))
                 if n.startswith("test_") and callable(getattr(module, n))]
        if not tests:
            continue
        title = (module.__doc__ or name).strip().splitlines()[0]
        print(f"\n{BOLD}{name}{OFF} {DIM}{title}{OFF}")
        for test_name, fn in tests:
            label = test_name[5:].replace("_", " ")
            try:
                fn()
            except Exception:
                failed += 1
                failures.append((name, test_name, traceback.format_exc()))
                print(f"  {RED}FAIL{OFF}  {label}")
            else:
                passed += 1
                if verbose:
                    print(f"  {GREEN}ok{OFF}    {label}")

        if not verbose:
            done = sum(1 for t, _ in tests if True)
            print(f"  {DIM}{done} checks{OFF}")

    elapsed = time.monotonic() - started
    print()
    if failures:
        for mod, test, tb in failures:
            print(f"{RED}{'=' * 70}{OFF}")
            print(f"{RED}FAILED{OFF} {mod}.{test}\n")
            print(tb)
        print(f"{RED}{failed} failed{OFF}, {passed} passed in {elapsed:.2f}s")
        return 1

    print(f"{GREEN}{passed} passed{OFF} in {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
