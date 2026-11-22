"""Record, per test, which (expression class, argument) pairs were validated while
the argument was missing, on the clean pinned tree.

Usage: python tools/record_validation.py <sqlglot tree> <tests.json> <out.json>

An arg_types flag only matters where an instance is validated without that
argument: flipping False -> True makes that validation fail, True -> False makes
an expected failure disappear. Worker pools are run in-process (arguments are
still pickled) so validations done "in the pool" are credited to the test that
submitted the work. Work done outside a test (class/module setup) is credited
to the whole class.
"""

import concurrent.futures
import concurrent.futures.process
import importlib
import json
import os
import pickle
import sys
import types
import unittest


class InlineExecutor(concurrent.futures.Executor):
    def __init__(self, max_workers=None, mp_context=None, initializer=None, initargs=(), **kwargs):
        if initializer is not None:
            initializer(*pickle.loads(pickle.dumps(initargs)))

    def submit(self, fn, /, *args, **kwargs):
        future = concurrent.futures.Future()
        try:
            args, kwargs = pickle.loads(pickle.dumps((args, kwargs)))
            future.set_result(pickle.loads(pickle.dumps(fn(*args, **kwargs))))
        except BaseException as error:  # noqa: BLE001
            future.set_exception(error)
        return future

    def shutdown(self, wait=True, *, cancel_futures=False):
        return None


def main():
    tree, manifest, out = sys.argv[1:4]
    os.chdir(tree)
    sys.path.insert(0, tree)
    sys.modules["__main__"] = types.ModuleType("__main__")
    concurrent.futures.ProcessPoolExecutor = InlineExecutor
    concurrent.futures.process.ProcessPoolExecutor = InlineExecutor

    from sqlglot.expressions import core

    state = {"current": None}
    pairs = {}

    def wrap(original):
        def error_messages(self, args=None):
            owner = state["current"]
            if owner is not None:
                cls = type(self)
                for key in cls.arg_types:
                    value = self.args.get(key)
                    if value is None or (isinstance(value, list) and not value):
                        pairs.setdefault(f"{cls.__name__}|{key}", set()).add(owner)
            return original(self, args)
        return error_messages

    for value in vars(core).values():
        if isinstance(value, type) and "error_messages" in vars(value):
            value.error_messages = wrap(vars(value)["error_messages"])

    tests = json.load(open(manifest))["tests"]
    suite = unittest.TestSuite()
    names = {}
    for test in sorted(tests, key=lambda t: t["id"]):
        path, cls, method = test["id"].split("::")
        state["current"] = "file:" + path  # import-time work belongs to the file
        module = importlib.import_module(path[:-3].replace("/", "."))
        case = getattr(module, cls)(method)
        names[id(case)] = test["id"]
        suite.addTest(case)

    gaps = {}  # gap number -> classes on either side
    order = {"gap": 0, "prev": None}

    class Result(unittest.TestResult):
        def startTest(self, test):
            identity = names.get(id(test))
            group = identity.rsplit("::", 1)[0] if identity else None
            gaps[order["gap"]] = (order["prev"], group)
            state["current"] = identity
            super().startTest(test)

        def stopTest(self, test):
            super().stopTest(test)
            identity = names.get(id(test))
            order["prev"] = identity.rsplit("::", 1)[0] if identity else None
            order["gap"] += 1
            # Work between tests is class/module setup or teardown of the
            # classes on either side.
            state["current"] = f"gap:{order['gap']}"

    state["current"] = "gap:0"
    suite.run(Result())
    gaps.setdefault(order["gap"], (order["prev"], None))
    for key, owners in pairs.items():
        expanded = set()
        for owner in owners:
            if owner.startswith("file:"):
                expanded.add(owner)
            elif owner.startswith("gap:"):
                for group in gaps.get(int(owner[4:]), ()):
                    if group:
                        expanded.add("class:" + group)
            else:
                expanded.add(owner)
        pairs[key] = expanded
    json.dump({"pairs": {k: sorted(v) for k, v in sorted(pairs.items())}}, open(out, "w"),
              separators=(",", ":"))
    print(f"recorded {len(pairs)} pairs", file=sys.stderr)


if __name__ == "__main__":
    main()
