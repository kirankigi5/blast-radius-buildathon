"""Run statically selected tests against each patched tree and drop the ones that pass.

The static selector (selection.py) decides which tests *might* fail. When running
those tests is cheaper than scheduling them, this module applies the patch to an
in-/tmp symlink overlay of the pinned sqlglot tree, forks a child from a parent
that already imported the heavy third-party libraries, runs the tests with
unittest and reports the ones that passed cleanly. Only observed clean passes are
removed: failures, errors, timeouts, skips, unimported modules, class/module
fixture errors and anything not reached before the deadline stay selected.
"""

import os
import re
import select
import shutil
import signal
import sys
import time
from pathlib import Path, PurePosixPath

SRC = Path("/app/src")
WORK = Path("/tmp/br")
HUNK = re.compile(rb"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# run_costs.json holds per-test cost measured on the clean tree; scale it up a
# little and recalibrate from the CPU finished children actually used.
INITIAL_SCALE = 1.4
CHILD_OVERHEAD = 0.8  # seconds of CPU to fork, import sqlglot and test modules
WORKERS = 2
# One-off class costs a child pays: the optimizer class starts a spawn pool
# whose workers import sqlglot, duckdb and pandas; the executor class loads
# the TPC CSV data.
CLASS_SETUP = {"tests/test_optimizer.py::TestOptimizer": 4.0,
               "tests/test_executor.py::TestExecutor": 1.2}


class PatchError(ValueError):
    pass


def _path(raw: bytes):
    value = raw.decode("utf-8").split("\t")[0].strip()
    if value == "/dev/null":
        return None
    if value.startswith('"'):
        raise PatchError("quoted path")
    if value.startswith(("a/", "b/")):
        value = value[2:]
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in value or "\0" in value:
        raise PatchError("unsafe path")
    return str(path)


def apply_patch(patch: bytes, root: Path = None):
    """Return {relative path: new bytes or None (deleted)} for a unified diff."""
    root = SRC if root is None else root
    lines = patch.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    lines = [line + b"\n" for line in lines]
    files = []  # (old, new, hunks)
    current = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(b"diff --git "):
            current = {"old": None, "new": None, "hunks": [], "seen": False}
            files.append(current)
            parts = line[11:].rstrip(b"\n").split(b" ")
            if len(parts) == 2:
                current["old"], current["new"] = _path(parts[0]), _path(parts[1])
        elif line.startswith(b"--- ") and i + 1 < len(lines) and lines[i + 1].startswith(b"+++ "):
            if current is None or current["seen"]:
                current = {"old": None, "new": None, "hunks": [], "seen": False}
                files.append(current)
            current["old"] = _path(line[4:].rstrip(b"\n"))
            current["new"] = _path(lines[i + 1][4:].rstrip(b"\n"))
            current["seen"] = True
            i += 1
        elif line.startswith(b"@@"):
            match = HUNK.match(line)
            if current is None or not match:
                raise PatchError("hunk header")
            a, b, c, d = match.groups()
            old_start, new_start = int(a), int(c)
            old_count = int(b) if b is not None else 1
            new_count = int(d) if d is not None else 1
            body = []
            used_old = used_new = 0
            i += 1
            while i < len(lines):
                part = lines[i]
                if part.startswith(b"\\"):
                    if not body:
                        raise PatchError("no newline marker")
                    mark, content = body[-1]
                    body[-1] = (mark, content[:-1] if content.endswith(b"\n") else content)
                    i += 1
                    continue
                if used_old == old_count and used_new == new_count:
                    break
                mark = part[:1]
                if mark not in (b" ", b"+", b"-"):
                    if part == b"\n":  # some generators drop the space on empty context
                        mark, part = b" ", b" \n"
                    else:
                        raise PatchError("hunk line")
                used_old += mark != b"+"
                used_new += mark != b"-"
                body.append((mark, part[1:]))
                i += 1
            if (used_old, used_new) != (old_count, new_count):
                raise PatchError("hunk counts")
            current["hunks"].append((old_start, old_count, body))
            line_no, prev, spans = old_start if old_count else old_start + 1, None, []
            for mark, _ in body:
                if mark == b" ":
                    line_no += 1
                elif mark == b"-":
                    spans.append((line_no, line_no))
                    line_no += 1
                else:
                    spans.append((line_no - 1, line_no))
            current.setdefault("ranges", []).extend(spans)
            continue
        elif line.startswith((b"Binary files", b"GIT binary patch")):
            raise PatchError("binary")
        elif current is not None and line.startswith(b"rename from "):
            current["old"] = _path(b"a/" + line[12:].rstrip(b"\n"))
        elif current is not None and line.startswith(b"rename to "):
            current["new"] = _path(b"b/" + line[10:].rstrip(b"\n"))
        elif current is not None and line.startswith(b"new file mode"):
            current["old"] = None
            current["created"] = True
        elif current is not None and line.startswith(b"deleted file mode"):
            current["deleted"] = True
        i += 1
    result = {}
    ranges = {}
    for entry in files:
        old, new = entry["old"], entry["new"]
        if entry.get("created"):
            old = None
        if entry.get("deleted"):
            new = None
        if old is None and new is None:
            raise PatchError("no paths")
        if old is not None:
            source = root / old
            if not source.is_file():
                raise PatchError("missing base file")
            base = source.read_bytes().split(b"\n")
            base = [line + b"\n" for line in base[:-1]] + ([base[-1]] if base[-1] else [])
        else:
            base = []
        output, cursor = [], 0
        for old_start, old_count, body in entry["hunks"]:
            position = old_start - 1 if old_count else old_start
            if position < cursor or position > len(base):
                raise PatchError("offset")
            output.extend(base[cursor:position])
            cursor = position
            for mark, content in body:
                if mark != b"+":
                    if cursor >= len(base) or base[cursor] != content:
                        raise PatchError("context mismatch")
                    cursor += 1
                if mark != b"-":
                    output.append(content)
        output.extend(base[cursor:])
        if old is not None:
            ranges[old] = entry.get("ranges", []) if old == new else None
        if new is not None and new != old:
            ranges[new] = None
        if old is not None and old != new:
            result.setdefault(old, None)
        if new is not None:
            result[new] = b"".join(output)
    return result, ranges


def build_overlay(changes: dict, target: Path, root: Path = None):
    """Mirror root into target with symlinks, materializing only patched paths."""
    root = SRC if root is None else root
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    real_dirs = set()
    for rel in changes:
        parts = PurePosixPath(rel).parts
        for depth in range(1, len(parts)):
            real_dirs.add(PurePosixPath(*parts[:depth]).as_posix())

    def mirror(rel_dir: str):
        src_dir = root / rel_dir if rel_dir else root
        dst_dir = target / rel_dir if rel_dir else target
        if not src_dir.is_dir():
            return
        for entry in os.scandir(src_dir):
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            if rel in changes:
                continue
            if rel in real_dirs and entry.is_dir(follow_symlinks=False):
                (dst_dir / entry.name).mkdir()
                mirror(rel)
            else:
                os.symlink(entry.path, dst_dir / entry.name)

    mirror("")
    for rel, content in changes.items():
        if content is None:
            continue
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _module_parts(test_id: str):
    path, cls, method = test_id.split("::")
    if not path.endswith(".py"):
        return None
    return path[:-3].replace("/", "."), cls, method


class _Timeout(BaseException):
    pass


def _child(workdir: Path, tests: list, wfd: int, probes=(), probe_base=None):
    """Runs inside the forked child; never returns."""
    try:
        os.setpgid(0, 0)
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        os.chdir(workdir)
        sys.path.insert(0, str(workdir))
        sys.dont_write_bytecode = True
        import types
        # Spawned pool workers re-run __main__; give them nothing to re-run.
        sys.modules["__main__"] = types.ModuleType("__main__")
        # The container has 2 CPUs; default-sized pools would spawn one
        # interpreter per host core and burn CPU importing sqlglot in each.
        os.cpu_count = lambda: WORKERS
        if hasattr(os, "process_cpu_count"):
            os.process_cpu_count = lambda: WORKERS
        import importlib
        import unittest

        def _alarm(signum, frame):
            raise _Timeout()

        signal.signal(signal.SIGALRM, _alarm)
        suite = unittest.TestSuite()
        meta = {}
        critical_numbers = set()
        for number, test_id, timeout, critical in tests:
            if critical:
                critical_numbers.add(number)
            parts = _module_parts(test_id)
            if parts is None:
                continue
            module_name, cls_name, method = parts
            try:
                module = importlib.import_module(module_name)
                case = getattr(module, cls_name)(method)
            except BaseException:
                continue
            meta[id(case)] = (number, timeout, f"{module_name}.{cls_name}")
            suite.addTest(case)

        out = os.fdopen(wfd, "w", buffering=1)
        pending = {}
        bad_groups = set()
        timings = []
        state = {"group": None, "bad": False}

        def flush(group):
            numbers = pending.pop(group, [])
            if numbers and group not in bad_groups:
                out.write("".join(f"{n}\n" for n in numbers))

        class Result(unittest.TestResult):
            def startTest(self, test):
                info = meta.get(id(test))
                group = info[2] if info else None
                if state["group"] is not None and group != state["group"]:
                    flush(state["group"])
                state["group"] = group
                state["bad"] = False
                state["ok"] = False
                super().startTest(test)
                state["t0"] = time.perf_counter()
                if info:
                    signal.setitimer(signal.ITIMER_REAL, info[1])

            def stopTest(self, test):
                signal.setitimer(signal.ITIMER_REAL, 0)
                info = meta.get(id(test))
                if info and info[0] in critical_numbers and (state["bad"] or not state.get("ok")):
                    os._exit(0)
                timings.append((time.perf_counter() - state["t0"], str(test)))
                super().stopTest(test)

            def addSubTest(self, test, subtest, err):
                if err is not None:
                    state["bad"] = True
                super().addSubTest(test, subtest, err)

            def addSuccess(self, test):
                info = meta.get(id(test))
                if info and not state["bad"]:
                    state["ok"] = True
                    pending.setdefault(info[2], []).append(info[0])
                super().addSuccess(test)

            def _holder(self, test):
                if not hasattr(test, "_testMethodName"):
                    description = str(test)
                    for group in list(pending) + [state["group"]]:
                        if group and group.rsplit(".", 1)[-1] in description:
                            bad_groups.add(group)
                    if state["group"]:
                        # conservatively poison the current group as well
                        bad_groups.add(state["group"])

            def addError(self, test, err):
                self._holder(test)
                super().addError(test, err)

            def addFailure(self, test, err):
                self._holder(test)
                super().addFailure(test, err)

        debug = os.environ.get("BR_DEBUG_DIR")
        # Probes first: when a dominant test cannot be shown to pass, nothing
        # else in this commit can lower its cost, so stop spending CPU.
        if probes:
            import tpc_probe
            for number, test_id, critical in probes:
                ok = False
                try:
                    ok = tpc_probe.run_probe(tpc_probe.EXEC_TESTS[test_id], probe_base)
                except BaseException:
                    if debug:
                        import traceback
                        with open(os.path.join(debug, f"probe-{os.getpid()}.txt"), "a") as handle:
                            handle.write(traceback.format_exc())
                if debug:
                    with open(os.path.join(debug, f"probe-{os.getpid()}.txt"), "a") as handle:
                        handle.write(f"{test_id} ok={ok} critical={critical} t={time.perf_counter()}\n")
                if ok:
                    out.write(f"{number}\n")
                    out.flush()
                elif critical:
                    out.flush()
                    os._exit(0)
        result = Result()
        suite.run(result)
        if debug:
            import traceback
            with open(os.path.join(debug, f"{os.getpid()}.txt"), "w") as handle:
                for test, err in result.errors + result.failures:
                    handle.write(f"== {test}\n{err[-1500:]}\n")
                handle.write(f"bad_groups {sorted(bad_groups)}\n")
                handle.write(f"loaded {len(meta)} of {len(tests)}\n")
                for spent, name in sorted(timings, reverse=True)[:25]:
                    handle.write(f"T {spent:.3f} {name}\n")
        signal.setitimer(signal.ITIMER_REAL, 0)
        for group in list(pending):
            flush(group)
        out.flush()
    except BaseException:
        pass
    os._exit(0)


def preload():
    """Import heavy third-party modules once so forked children share them."""
    for name in ("unittest", "unittest.mock", "concurrent.futures", "multiprocessing",
                 "decimal", "datetime", "typing", "dataclasses", "inspect", "json",
                 "numpy", "pandas", "duckdb"):
        try:
            __import__(name)
        except BaseException:
            pass
    if any(name == "sqlglot" or name.startswith("sqlglot.") or name == "tests" or name.startswith("tests.")
           for name in sys.modules):
        raise RuntimeError("preload imported sqlglot")


def partition_cost(numbers, seconds_by_test, schedule):
    workers = schedule(numbers, seconds_by_test)
    loads = [sum(int(seconds_by_test[n] * 1000 + 0.5) for n in w) for w in workers if w]
    return (max(loads, default=0) + 2000 * len(loads)) / 1000.0


def _load_costs():
    try:
        import json
        return json.loads((Path(__file__).resolve().parent / "coverage_index" / "run_costs.json").read_text())["tests"]
    except Exception:
        return {}


def verify_all(jobs, tests_by_number, seconds_by_test, schedule, deadline, log):
    """jobs: list of (commit, patch_bytes, frozenset selected). Returns {commit: passed set}."""
    if not SRC.is_dir():
        log({"verify": "skipped", "reason": "no_source_tree"})
        return {}
    costs = _load_costs()
    scale = {"value": INITIAL_SCALE}
    probe_base = None
    try:
        import pickle
        import tpc_probe
        probe_path = Path(os.environ.get("BR_PROBE_BASE", str(Path(__file__).resolve().parent / "tpc_base.pkl")))
        if probe_path.is_file():
            with open(probe_path, "rb") as handle:
                probe_base = pickle.load(handle)
    except Exception as error:
        log({"verify": "probe_unavailable", "reason": repr(error)})
        probe_base = None
    probe_cost = {"tpcds": 2.5, "tpch": 0.8, "optimized_tpch": 0.4}

    def est(number, job=None):
        test = tests_by_number[number]
        if job is not None and number in job["probes"]:
            return probe_cost[tpc_probe.EXEC_TESTS[test["id"]]] * scale["value"]
        return costs.get(test["id"], test["seconds"] * 1.5) * scale["value"]

    planned = []
    for commit, patch, selected in jobs:
        if not selected:
            continue
        static = partition_cost(sorted(selected), seconds_by_test, schedule)
        try:
            changes, ranges = apply_patch(patch)
        except (PatchError, UnicodeError, OSError) as error:
            log({"commit": commit, "verify": "unpatchable", "reason": str(error)})
            continue
        probes = set()
        if probe_base is not None:
            try:
                if tpc_probe.guard_ok(probe_base, ranges, SRC):
                    probes = {n for n in selected if tests_by_number[n]["id"] in tpc_probe.EXEC_TESTS}
            except Exception:
                probes = set()
        planned.append({"commit": commit, "changes": changes, "selected": selected, "static": static,
                        "probes": frozenset(probes)})
    if not planned:
        return {}

    def plan(job):
        run = frozenset(n for n in job["selected"] if est(n, job) <= 0.8 * seconds_by_test[n] + 0.02)
        unrun = job["selected"] - run
        after = partition_cost(sorted(unrun), seconds_by_test, schedule)
        # If everything passes the commit costs nothing; if something fails we
        # pay roughly one small worker. Treat it as a coin flip.
        after += 0.3 if unrun else 1.1
        files = {tests_by_number[n]["file"] for n in run}
        groups = {tests_by_number[n]["id"].rsplit("::", 1)[0] for n in run if n not in job["probes"]}
        setup = sum(CLASS_SETUP.get(g, 0.0) for g in groups) * scale["value"]
        cpu = sum(est(n, job) for n in run) + CHILD_OVERHEAD + 0.03 * len(files) + setup
        job["run"] = run
        return job["static"] - after - 1.2 * cpu, cpu

    for job in planned:
        job["score"], job["cpu"] = plan(job)
    planned.sort(key=lambda job: -job["score"] / job["cpu"])
    if not any(job["score"] > 0 and job["run"] for job in planned):
        return {}
    preload()
    WORK.mkdir(parents=True, exist_ok=True)
    passed = {}
    running = {}  # pid -> (job, fd, buffer, start)
    queue = list(planned)
    cpu_used = est_done = 0.0
    serial = 0

    def launch(job):
        nonlocal serial
        serial += 1
        workdir = WORK / str(serial)
        try:
            build_overlay(job["changes"], workdir)
        except OSError as error:
            log({"commit": job["commit"], "verify": "overlay_failed", "reason": str(error)})
            shutil.rmtree(workdir, ignore_errors=True)
            return
        job["est_run"] = sum(est(n, job) for n in job["run"]) / scale["value"]
        items = []
        for number in job["run"]:
            test = tests_by_number[number]
            items.append((number, test["id"], max(6.0, 3.0 * test["seconds"] + 3.0),
                          test["seconds"], number in job["probes"]))
        # Cheap classes first so the most passes land before any deadline.
        group_cost = {}
        for number, test_id, _, sec, _ in items:
            key = test_id.rsplit("::", 1)[0]
            group_cost[key] = group_cost.get(key, 0.0) + sec
        unrun = sorted(job["selected"] - job["run"])
        critical = set()
        total_cpu = sum(est(n, job) for n in job["run"])
        for number in job["run"]:
            if seconds_by_test[number] < 0.5:
                continue
            kept = sorted(set(unrun) | {number})
            gain_if_fail = job["static"] - partition_cost(kept, seconds_by_test, schedule) - 1.0
            if gain_if_fail < 1.2 * (total_cpu - est(number, job)):
                critical.add(number)
        # Critical classes first (abort early), then cheap classes.
        group_critical = {item[1].rsplit("::", 1)[0] for item in items if item[0] in critical}
        items.sort(key=lambda item: (item[1].rsplit("::", 1)[0] not in group_critical,
                                     group_cost[item[1].rsplit("::", 1)[0]], item[1]))
        rfd, wfd = os.pipe()
        sys.stdout.flush()
        sys.stderr.flush()
        pid = os.fork()
        if pid == 0:
            os.close(rfd)
            _child(workdir, [(n, i, t, n in critical) for n, i, t, _, p in items if not p], wfd,
                   [(n, i, n in critical) for n, i, _, _, p in items if p], probe_base)
        os.close(wfd)
        os.set_blocking(rfd, False)
        running[pid] = {"job": job, "fd": rfd, "buf": b"", "start": time.monotonic(), "dir": workdir}

    def drain(info):
        while True:
            try:
                chunk = os.read(info["fd"], 65536)
            except BlockingIOError:
                return False
            if not chunk:
                return True
            info["buf"] += chunk

    def finish(pid, info, rusage, killed):
        nonlocal cpu_used, est_done
        drain(info)
        os.close(info["fd"])
        good = set()
        for line in info["buf"].decode().split("\n"):
            if line.strip().isdigit():
                good.add(int(line))
        good &= info["job"]["selected"]
        passed[info["job"]["commit"]] = good
        cpu = rusage.ru_utime + rusage.ru_stime if rusage else 0.0
        if not killed and cpu > 0:
            cpu_used += max(0.0, cpu - CHILD_OVERHEAD)
            est_done += info["job"]["est_run"]
            if est_done > 2.0:
                # Only ever raise the scale: aborted children use less CPU
                # than planned and would otherwise make big jobs look cheap.
                scale["value"] = min(4.0, max(scale["value"], cpu_used / est_done))
        log({"commit": info["job"]["commit"], "verify": "killed" if killed else "done",
             "selected": len(info["job"]["selected"]), "passed": len(good),
             "child_cpu": round(cpu, 3), "wall": round(time.monotonic() - info["start"], 3),
             "scale": round(scale["value"], 3)})
        shutil.rmtree(info["dir"], ignore_errors=True)

    while queue or running:
        now = time.monotonic()
        while queue and len(running) < WORKERS:
            job = queue.pop(0)
            score, cpu = plan(job)
            if score <= 0 or not job["run"]:
                log({"commit": job["commit"], "verify": "not_worth", "static": job["static"],
                     "est_cpu": round(cpu, 3)})
                continue
            if now + 1.5 * cpu > deadline:
                log({"commit": job["commit"], "verify": "no_time", "est_cpu": round(cpu, 3)})
                continue
            launch(job)
        if not running:
            continue
        fds = {info["fd"]: pid for pid, info in running.items()}
        timeout = max(0.0, min(0.5, deadline - time.monotonic()))
        try:
            ready, _, _ = select.select(list(fds), [], [], timeout)
        except InterruptedError:
            ready = []
        for fd in ready:
            drain(running[fds[fd]])
        for pid in list(running):
            try:
                done_pid, status, rusage = os.wait4(pid, os.WNOHANG)
            except ChildProcessError:
                done_pid, rusage = pid, None
            if done_pid:
                finish(pid, running.pop(pid), rusage, False)
        if time.monotonic() >= deadline:
            for pid, info in list(running.items()):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except OSError:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
                try:
                    _, _, rusage = os.wait4(pid, 0)
                except ChildProcessError:
                    rusage = None
                finish(pid, running.pop(pid), rusage, True)
            for job in queue:
                log({"commit": job["commit"], "verify": "no_time"})
            queue.clear()
    shutil.rmtree(WORK, ignore_errors=True)
    return passed
