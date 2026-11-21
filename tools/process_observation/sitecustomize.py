"""Offline child-process coverage for the pinned CPython pytest image."""

import atexit
from concurrent.futures import process
import gzip
import inspect
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading


TOOL_ID = 3
pool_id = None
boundaries = {}
task_id = None
started = []
ended = []
phase = None
launches = []
background_threads = []
LAUNCH_EVENTS = {"subprocess.Popen", "os.fork", "os.forkpty", "os.posix_spawn", "os.exec", "os.system"}


def audit_launches(event, args):
    if event in LAUNCH_EVENTS:
        launches.append(event)


def change_phase(context):
    global phase
    if phase != context:
        coverage.switch_context(context)
        phase = context


def observe_worker_line(code, line):
    global task_id
    boundary = boundaries.get(line)
    if boundary is None:
        return sys.monitoring.DISABLE
    if boundary == "task":
        current = sys._getframe(1).f_locals["call_item"].work_id
        if task_id is not None:
            if current != task_id:
                raise RuntimeError("overlapping tasks inside one worker")
            return
        task_id = current
        started.append(current)
        change_phase(f"task:{current}")
    elif boundary in {"result", "exception"}:
        # The opening line of a multiline call can be revisited by PEP 669.
        current = sys._getframe(1).f_locals["call_item"].work_id
        if task_id is not None:
            if current != task_id:
                raise RuntimeError("task result has a different work ID")
            ended.append([current, boundary])
            task_id = None
        elif not ended or ended[-1] != [current, boundary]:
            raise RuntimeError("task result without matching entry")
        change_phase(boundary)
    else:
        change_phase(boundary)


def flush():
    coverage.stop()
    data = coverage.get_data()
    data.write()
    observations = {}
    # The pinned coverage schema stores an integer bitmap of each line set,
    # split by file and context. This avoids expanding every line/test pair.
    with sqlite3.connect(f"file:{data.data_filename()}?mode=ro", uri=True) as db:
        for path, context, numbits in db.execute("""
            SELECT f.path, c.context, lb.numbits FROM line_bits lb
            JOIN file f ON lb.file_id = f.id JOIN context c ON lb.context_id = c.id
        """):
            if not path.startswith("/src/"):
                raise RuntimeError(f"unexpected child coverage path: {path}")
            observations.setdefault(context, {})[path.removeprefix("/src/")] = format(int.from_bytes(numbits, "little"), "x")
    output = {
        "pid": os.getpid(), "pool": pool_id,
        "resource_tracker": any("multiprocessing.resource_tracker" in arg for arg in sys.orig_argv),
        "started": started, "ended": ended, "active_at_exit": task_id,
        "launches": launches, "background_threads": background_threads,
        "coverage": observations,
    }
    destination = Path(f"/result/child-{os.getpid()}.json.gz")
    temporary = destination.with_suffix(".partial")
    with gzip.open(temporary, "wt", encoding="utf-8") as stream:
        json.dump(output, stream, sort_keys=True, separators=(",", ":"))
    temporary.replace(destination)


def worker(pool, *args):
    global pool_id
    if pool_id is not None:
        raise RuntimeError("duplicate process-pool attachment")
    pool_id = pool
    original = process._process_worker
    source, start = inspect.getsourcelines(original)
    markers = {
        "initializer(*initargs)": "initializer",
        "call_item = call_queue.get(block=True)": "deserialize",
        "if call_item is None:": "worker",
        "r = call_item.fn(*call_item.args, **call_item.kwargs)": "task",
        "exc = _ExceptionWithTraceback(e, e.__traceback__)": "exception",
        "_sendback_result(result_queue, call_item.work_id, result=r,": "result",
    }
    boundaries.update({start + i: markers[line.strip()] for i, line in enumerate(source)
                       if line.strip() in markers})
    if len(boundaries) != len(markers):
        raise RuntimeError("unsupported CPython worker implementation")
    sys.monitoring.set_local_events(TOOL_ID, original.__code__, sys.monitoring.events.LINE)
    change_phase("initialization")
    try:
        return original(*args)
    finally:
        change_phase("shutdown")


if os.environ.get("PROCESS_OBSERVATION_TRACE") == "1" and os.getpid() != 1:
    from coverage import Coverage

    original_thread_start = threading.Thread.start

    def start_thread(self):
        background_threads.append(self.name)
        return original_thread_start(self)

    threading.Thread.start = start_thread
    sys.addaudithook(audit_launches)
    sys.monitoring.use_tool_id(TOOL_ID, "clean_process_observation")
    sys.monitoring.register_callback(TOOL_ID, sys.monitoring.events.LINE, observe_worker_line)
    coverage = Coverage(source=["/src"], data_file=f"/tmp/coverage-child-{os.getpid()}", config_file=False)
    coverage.start()
    change_phase("bootstrap")
    atexit.register(flush)
