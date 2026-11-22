"""Measure per-test run cost on the clean pinned tree (evaluation-free timing map).

Usage: python tools/measure_costs.py <sqlglot tree> <tests.json> <out.json>
Runs every numbered test with unittest in one process, with the same pool-size
cap the runtime verifier uses. A test's cost is its own CPU plus two pool
workers' worth of the time it spent waiting. The gap before a class's first
test (setUpClass, module import) is recorded per class.
"""

import json
import os
import sys
import time
import types
import unittest
import importlib


def main():
    tree, manifest, out = sys.argv[1:4]
    os.chdir(tree)
    sys.path.insert(0, tree)
    sys.modules["__main__"] = types.ModuleType("__main__")
    os.cpu_count = lambda: 2
    os.process_cpu_count = lambda: 2
    tests = json.load(open(manifest))["tests"]
    suite = unittest.TestSuite()
    names = {}
    order = sorted(tests, key=lambda t: t["id"])
    for test in order:
        path, cls, method = test["id"].split("::")
        module = importlib.import_module(path[:-3].replace("/", "."))
        case = getattr(module, cls)(method)
        names[id(case)] = test["id"]
        suite.addTest(case)
    costs, setup = {}, {}
    failed = []
    state = {"last": time.perf_counter(), "group": None}

    class Result(unittest.TestResult):
        def startTest(self, test):
            now = time.perf_counter()
            group = names.get(id(test), "").rsplit("::", 1)[0]
            if group != state["group"]:
                setup[group] = round(now - state["last"], 4)
                state["group"] = group
            state["t0"], state["c0"] = now, time.process_time()
            super().startTest(test)

        def stopTest(self, test):
            wall = time.perf_counter() - state["t0"]
            cpu = time.process_time() - state["c0"]
            costs[names.get(id(test))] = round(cpu + 2 * max(0.0, wall - cpu), 4)
            state["last"] = time.perf_counter()
            super().stopTest(test)

        def addError(self, test, err):
            failed.append(str(test)); super().addError(test, err)

        def addFailure(self, test, err):
            failed.append(str(test)); super().addFailure(test, err)

        def addSubTest(self, test, sub, err):
            if err is not None:
                failed.append(str(sub))
            super().addSubTest(test, sub, err)

    suite.run(Result())
    json.dump({"tests": costs, "class_setup": setup, "clean_failures": sorted(set(failed))},
              open(out, "w"), indent=0, sort_keys=True)


if __name__ == "__main__":
    main()
