"""Cheap equivalence probe for the TPC-H / TPC-DS executor tests.

Build time (``python tpc_probe.py build <tree> <out>``, clean pinned tree):
for every TPC query, record the DuckDB SQL, the parse/pickle/optimize/plan
fingerprints the executor test depends on, every (expression, Python code)
pair the executor generates, and every sqlglot function that runs during
execution outside optimize / planning / code generation.

Runtime (inside a verify child, patched tree on sys.path): if the patch leaves
those execution-time functions and the executor package untouched, recompute
the fingerprints and regenerate the recorded code. Queries whose inputs all
match behave exactly as on the clean tree, where the tests pass. Only queries
that differ are executed for real with the test's own helpers.
"""

import ast
import hashlib
import os
import pickle
import sys

EXEC_TESTS = {
    "tests/test_executor.py::TestExecutor::test_execute_tpcds": "tpcds",
    "tests/test_executor.py::TestExecutor::test_execute_tpch": "tpch",
    "tests/test_executor.py::TestExecutor::test_optimized_tpch": "optimized_tpch",
}
# Any change under these paths disables the probe.
GUARDED_PREFIXES = ("sqlglot/executor/", "tests/test_executor.py", "tests/helpers.py",
                    "tests/fixtures/optimizer/tpc-h/", "tests/fixtures/optimizer/tpc-ds/",
                    "tests/__init__.py")
FIXTURE_SQL = {"tpch": "tests/fixtures/optimizer/tpc-h/tpc-h.sql",
               "tpcds": "tests/fixtures/optimizer/tpc-ds/tpc-ds.sql"}


def _h(value) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()[:24]


def _fp_obj(value, seen=None):
    from sqlglot import exp
    from sqlglot.planner import Step
    if isinstance(value, exp.Expr if hasattr(exp, "Expr") else exp.Expression):
        return "E" + repr(value)
    if isinstance(value, Step):
        return "S" + value.name
    if isinstance(value, dict):
        return "{" + ",".join(f"{_fp_obj(k)}:{_fp_obj(v)}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_fp_obj(v) for v in value) + "]"
    if isinstance(value, (set, frozenset)):
        return "<" + ",".join(sorted(_fp_obj(v) for v in value)) + ">"
    return type(value).__name__ + ":" + repr(value)


def plan_fingerprint(plan) -> str:
    seen, order, stack = set(), [], [plan.root]
    while stack:
        step = stack.pop()
        if id(step) in seen:
            continue
        seen.add(id(step))
        order.append(step)
        stack.extend(sorted(step.dependencies, key=lambda s: s.name, reverse=True))
    parts = []
    for step in order:
        fields = sorted(vars(step).items())
        parts.append(type(step).__name__ + "|" + "|".join(f"{k}={_fp_obj(v)}" for k, v in fields))
    # Steps can share names and dependencies are sets, so traversal order is
    # not stable across processes; compare the multiset of step descriptions.
    return _h("\n".join(sorted(parts)))


def main_fingerprints(kind, sqls):
    """What the test's main process computes: DuckDB SQL and the parsed tree.

    Returns (per-query hashes, pickled parsed expressions or None)."""
    from sqlglot import parse_one, transpile
    hashes, blobs = [], []
    for meta, sql, optimized_sql in sqls:
        try:
            duck = transpile(sql, write="duckdb")[0]
            if kind == "optimized_tpch":
                hashes.append(_h(duck + "\0" + transpile(optimized_sql, write="duckdb")[0]))
                blobs.append(None)
                continue
            parsed = parse_one(sql)
            hashes.append(_h(duck + "\0" + repr(parsed)))
            # The test submits every query to the pool, executed or not.
            blobs.append((pickle.dumps(parsed), bool(meta.get("execute"))))
        except BaseException as error:  # noqa: BLE001
            hashes.append("error:" + type(error).__name__)
            blobs.append(None)
    return hashes, blobs


def _worker_main():
    """Fresh interpreter, like a spawn pool worker: unpickle, optimize, plan, codegen."""
    import io
    kind, blobs, codegen = pickle.load(sys.stdin.buffer)
    sys.path.insert(0, os.getcwd())
    from sqlglot.optimizer import optimize
    from sqlglot.planner import Plan
    from sqlglot.schema import ensure_schema
    from sqlglot.executor.python import Python
    from tests.helpers import TPCDS_SCHEMA, TPCH_SCHEMA
    schema = TPCDS_SCHEMA if kind == "tpcds" else TPCH_SCHEMA
    out = []
    for i, item in enumerate(blobs):
        if item is None:
            out.append(("none", True))
            continue
        blob, executes = item
        try:
            round_trip = pickle.loads(blob)
            if not executes:
                out.append((_h("noexec\n" + repr(round_trip)), True))
                continue
            optimized = optimize(round_trip, ensure_schema(schema), leave_tables_isolated=True, dialect=None)
            fp = _h(repr(round_trip) + "\n" + repr(optimized) + "\n" + plan_fingerprint(Plan(optimized)))
        except BaseException as error:  # noqa: BLE001
            fp = "error:" + type(error).__name__
        ok = True
        if codegen is not None:
            generator = Python().generator(identify=True, comments=False)
            try:
                for record, code in codegen[i]:
                    if generator.generate(pickle.loads(record)) != code:
                        ok = False
                        break
            except BaseException:  # noqa: BLE001
                ok = False
        out.append((fp, ok))
    sys.stdout.buffer.write(pickle.dumps(out))


def worker_fingerprints(kind, blobs, codegen, tree="."):
    import subprocess
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    proc = subprocess.run([sys.executable, "-c",
                           "import sys; sys.path.insert(0, sys.argv[1]); import tpc_probe; tpc_probe._worker_main()",
                           os.path.dirname(os.path.abspath(__file__))],
                          input=pickle.dumps((kind, blobs, codegen)), capture_output=True,
                          cwd=tree, env=env, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError("probe worker failed")
    return pickle.loads(proc.stdout)


def _load(kind):
    from tests.helpers import TPCDS_SCHEMA, TPCH_SCHEMA, load_sql_fixture_pairs
    if kind == "tpcds":
        return list(load_sql_fixture_pairs("optimizer/tpc-ds/tpc-ds.sql")), TPCDS_SCHEMA
    return list(load_sql_fixture_pairs("optimizer/tpc-h/tpc-h.sql")), TPCH_SCHEMA


# --------------------------------------------------------------------- build

def build(tree, out_path):
    os.chdir(tree)
    sys.path.insert(0, tree)
    import sqlglot.executor as executor_pkg
    from sqlglot.executor import python as executor_python
    from sqlglot import exp, find_tables
    from sqlglot.executor.table import Table
    import tests.test_executor as te

    root = os.path.join(os.path.abspath(tree), "sqlglot") + os.sep
    state = {"active": False}
    exec_functions = set()
    mon = sys.monitoring
    tool = mon.OPTIMIZER_ID
    mon.use_tool_id(tool, "tpc_probe")

    def on_start(code, offset):
        filename = code.co_filename
        if filename.startswith(root):
            lines = [line for _, _, line in code.co_lines() if line is not None]
            exec_functions.add(("sqlglot/" + filename[len(root):].replace(os.sep, "/"),
                                code.co_firstlineno, max(lines, default=code.co_firstlineno)))
        return mon.DISABLE

    mon.register_callback(tool, mon.events.PY_START, on_start)

    def set_active(flag):
        state["active"] = flag
        mon.set_events(tool, mon.events.PY_START if flag else 0)

    def suspended(function):
        def wrapper(*args, **kwargs):
            previous = state["active"]
            set_active(False)
            try:
                return function(*args, **kwargs)
            finally:
                set_active(previous)
        return wrapper

    codegen = []
    real_optimize, real_plan = executor_pkg.optimize, executor_pkg.Plan
    executor_pkg.optimize = suspended(real_optimize)
    executor_pkg.Plan = suspended(real_plan)
    original_generate = executor_python.PythonExecutor.generate

    def generate(self, expression):
        if not expression:
            return None
        expression = self._replace_subqueries(expression)
        previous = state["active"]
        set_active(False)
        try:
            blob = pickle.dumps(expression)
            code = self.generator.generate(expression)
        finally:
            set_active(previous)
        codegen.append((blob, code))
        return compile(code, code, "eval", optimize=2)

    executor_python.PythonExecutor.generate = generate

    te.TestExecutor.setUpClass()
    result = {"queries": {}, "codegen": {}}
    for kind in ("tpch", "tpcds"):
        sqls, schema = _load(kind)
        tables = te.TestExecutor.tpch_tables if kind == "tpch" else te.TestExecutor.tpcds_tables
        hashes, blobs = main_fingerprints(kind, sqls)
        worker = worker_fingerprints(kind, blobs, None, tree)
        result["queries"][kind] = list(zip(hashes, [fp for fp, _ in worker]))
        records = []
        for meta, sql, _ in sqls:
            del codegen[:]
            if meta.get("execute"):
                expression = pickle.loads(pickle.dumps(sqlglot_parse(sql)))
                needed = {t.name: tables[t.name] for t in find_tables(expression)}
                set_active(True)
                try:
                    executor_pkg.execute(expression, schema=schema, tables=needed)
                finally:
                    set_active(False)
            records.append(list(codegen))
        result["codegen"][kind] = records
    result["queries"]["optimized_tpch"] = [(h, "") for h in main_fingerprints("optimized_tpch", _load("tpch")[0])[0]]
    mon.set_events(tool, 0)
    mon.free_tool_id(tool)
    executor_python.PythonExecutor.generate = original_generate
    executor_pkg.optimize, executor_pkg.Plan = real_optimize, real_plan
    result["exec_functions"] = sorted(exec_functions)
    with open(out_path, "wb") as handle:
        pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"tpc_probe: {len(exec_functions)} exec functions, "
          f"{sum(len(r) for k in result['codegen'] for r in result['codegen'][k])} codegen records",
          file=sys.stderr)


def sqlglot_parse(sql):
    from sqlglot import parse_one
    return parse_one(sql)


# ------------------------------------------------------------------- runtime

def guard_ok(base, changed_ranges, src="/app/src"):
    """changed_ranges: {path: [(old_start, old_end)]} for every changed path."""
    for path in changed_ranges:
        if path.startswith(GUARDED_PREFIXES):
            return False
    by_file = {}
    for path, first, last in base["exec_functions"]:
        by_file.setdefault(path, []).append((first, last))
    for path, ranges in changed_ranges.items():
        spans = by_file.get(path)
        if not spans:
            continue
        if ranges is None:
            return False
        # An edit in a file that runs at execution time must sit inside a
        # function body that does not run at execution time.
        try:
            with open(os.path.join(str(src), path), encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
        except Exception:
            return False
        functions = [(node.lineno, node.end_lineno) for node in ast.walk(tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for start, end in ranges:
            hosts = [f for f in functions if f[0] < start and end <= f[1]]
            if not hosts:
                return False
            for first, last in spans:
                if not (end < first or start > last):
                    return False
            # also refuse when the host function contains an exec-time function
            for host in hosts:
                for first, last in spans:
                    if host[0] <= first and last <= host[1]:
                        return False
    return True


def _exec_main():
    """Fresh interpreter standing in for a spawn pool worker: execute queries."""
    kind, items = pickle.load(sys.stdin.buffer)
    sys.path.insert(0, os.getcwd())
    import tests.test_executor as te
    te.TestExecutor.setUpClass()
    tpch = kind == "tpch"
    tables = te.TestExecutor.tpch_tables if tpch else te.TestExecutor.tpcds_tables
    # The test ships schema and tables to its workers through initargs.
    schema, tables = pickle.loads(pickle.dumps((te.TPCH_SCHEMA if tpch else te.TPCDS_SCHEMA, tables)))
    te.initializer(schema, tables)
    out = []
    for i, blob, meta in items:
        try:
            table = te.mp_execute(pickle.loads(blob), meta)
            out.append((i, pickle.dumps(table)))
        except BaseException as error:  # noqa: BLE001
            out.append((i, None))
    sys.stdout.buffer.write(pickle.dumps(out))


def _execute_in_worker(kind, items, timeout):
    import subprocess
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    proc = subprocess.run([sys.executable, "-c",
                           "import sys; sys.path.insert(0, sys.argv[1]); import tpc_probe; tpc_probe._exec_main()",
                           os.path.dirname(os.path.abspath(__file__))],
                          input=pickle.dumps((kind, items)), capture_output=True, env=env, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError("probe executor failed")
    return pickle.loads(proc.stdout)


def run_probe(kind, base, full=False):
    """Return True only when the test is shown to pass.

    full=False: the guard held, so queries whose executor inputs match the
    clean tree are known to pass and only the others are executed.
    full=True: the guard failed (e.g. executor code changed); execute every
    query, in a fresh interpreter like the test's spawn pool."""
    import tests.test_executor as te
    real_kind = "tpch" if kind == "optimized_tpch" else kind
    sqls, schema = _load(real_kind)
    expected = base["queries"][kind]
    hashes, blobs = main_fingerprints(kind, sqls)
    if len(hashes) != len(expected):
        return False
    if any(h.startswith("error") for h in hashes):
        return False  # the test's main process would raise too
    if full:
        mismatched = list(range(len(sqls)))
    elif kind == "optimized_tpch":
        mismatched = [i for i, h in enumerate(hashes) if (h, "") != tuple(expected[i])]
    else:
        worker = worker_fingerprints(kind, blobs, base["codegen"][kind])
        mismatched = [i for i, (h, (fp, ok)) in enumerate(zip(hashes, worker))
                      if (h, fp) != tuple(expected[i]) or not ok or fp.startswith("error")]
    if not mismatched:
        return True
    te.TestExecutor.setUpClass()
    case = te.TestExecutor("test_execute_tpch")
    try:
        if kind == "optimized_tpch":
            for i in mismatched:
                _, sql, optimized = sqls[i]
                a = case.cached_execute(sql, tpch=True)
                b = case.tpch_conn.execute(te.transpile(optimized, write="duckdb")[0]).fetchdf()
                case.rename_anonymous(b, a)
                te.assert_frame_equal(a, b)
            return True
        # Every query goes through the pool in the test, executed or not.
        items = [(i, blobs[i][0], sqls[i][0]) for i in mismatched]
        results = _execute_in_worker(kind, items, timeout=240)
        if len(results) != len(items):
            return False
        for i, table_blob in results:
            if table_blob is None:
                return False
            table = pickle.loads(table_blob)
            if table is not None:
                case.subtestHelper(i, table, tpch=kind == "tpch")
        return True
    finally:
        te.TestExecutor.tearDownClass()


if __name__ == "__main__":
    if sys.argv[1] == "build":
        build(sys.argv[2], sys.argv[3])
