"""Run a unittest suite against a baseline of known failures (SDLC kit: baselines only shrink).

    python tools/run_suite.py core       # core/tests
    python tools/run_suite.py win_app    # win_app/tests

Each test file runs in its own process, four at a time, with MODULE_SECONDS to finish, so one
test that hangs (some upstream GUI tests do on some desktops) is reported by name instead of
stopping the run. Exits 0 when every failure is listed in .sdlc/known-failures.txt for that suite,
1 on any failure not listed. A listed failure that now passes is printed so its line can go.
"""

import concurrent.futures
import glob
import json
import os
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, ".sdlc", "known-failures.txt")
MODULE_SECONDS = 900  # test_crossing_e2e alone takes about 280 s on the LOQ
WORKERS = 4


def known(suite):
    entries = set()
    try:
        with open(BASELINE, encoding="utf-8") as source:
            for line in source:
                line = line.split("#", 1)[0].strip()
                if line.startswith(suite + ":"):
                    entries.add(line[len(suite) + 1:].strip())
    except FileNotFoundError:
        pass
    return entries


def modules(suite):
    folder = os.path.join(ROOT, "core" if suite == "core" else "win_app", "tests")
    return sorted(os.path.splitext(os.path.basename(path))[0] for path in glob.glob(os.path.join(folder, "test_*.py")))


def run_one(suite, module):
    """In the child: run one test file and print its failing test ids as JSON on the last line."""
    if suite == "core":
        os.chdir(ROOT)
        sys.path.insert(0, ROOT)
        tests = unittest.defaultTestLoader.loadTestsFromName(f"core.tests.{module}")
    else:
        os.chdir(os.path.join(ROOT, "win_app"))
        sys.path.insert(0, ROOT)
        sys.path.insert(0, os.getcwd())
        tests = unittest.defaultTestLoader.discover("tests", pattern=f"{module}.py")
    # UTF-8: a failure message with a non-ANSI character must not crash the report on Windows.
    with open(os.devnull, "w", encoding="utf-8", errors="replace") as sink:
        result = unittest.TextTestRunner(stream=sink, verbosity=0).run(tests)
    problems = result.failures + result.errors
    failed = sorted({test.id().split(" ")[0] for test, _ in problems})
    details = {test.id().split(" ")[0]: trace for test, trace in problems}
    print(json.dumps({"ran": result.testsRun, "skipped": len(result.skipped), "failed": failed, "details": details}))
    return 0


def spawn(suite, module):
    started = time.monotonic()
    try:
        completed = subprocess.run([sys.executable, os.path.abspath(__file__), "--one", suite, module],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=MODULE_SECONDS)
    except subprocess.TimeoutExpired:
        name = f"{module} (timed out after {MODULE_SECONDS} s)"
        return module, {"ran": 0, "skipped": 0, "failed": [name], "details": {}}, MODULE_SECONDS
    lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
    if not lines:
        name = f"{module} (did not load)"
        return module, {"ran": 0, "skipped": 0, "failed": [name], "details": {name: (completed.stderr or "")[-3000:]}}, \
            time.monotonic() - started
    return module, json.loads(lines[-1]), time.monotonic() - started


def main(argv):
    if len(argv) == 4 and argv[1] == "--one":
        return run_one(argv[2], argv[3])
    if len(argv) != 2 or argv[1] not in ("core", "win_app"):
        print(__doc__)
        return 2
    suite = argv[1]
    started = time.monotonic()
    ran = skipped = 0
    failed, details = set(), {}
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        for module, outcome, seconds in pool.map(lambda name: spawn(suite, name), modules(suite)):
            ran += outcome["ran"]
            skipped += outcome["skipped"]
            failed.update(outcome["failed"])
            details.update(outcome["details"])
            if seconds > 120:
                print(f"slow: {module} took {seconds:.0f} s", flush=True)
    expected = known(suite)
    new = sorted(name for name in failed if name not in expected)
    fixed = sorted(name for name in expected if name not in failed)
    for name in new:
        print(f"NEW FAILURE {suite}: {name}\n{details.get(name, '')}")
    for name in fixed:
        print(f"NOW PASSES OR GONE (remove from .sdlc/known-failures.txt): {suite}: {name}")
    print(f"{suite}: ran {ran} tests in {time.monotonic() - started:.0f} s; {len(failed)} failing, "
          f"{len(failed) - len(new)} of them known, {len(new)} new, {skipped} skipped")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
