"""Record all clean task submissions, pool lifetimes, and child trace identities."""

from concurrent.futures import process
import json
from multiprocessing.process import BaseProcess
import multiprocessing.resource_tracker
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
import sitecustomize

from pytest_contexts import Contexts
from stage5_label import classify


class TestContext:
    def switch_context(self, name):
        self.name = name


def main():
    assert os.getpid() == 1 and os.environ.get("PROCESS_OBSERVATION_TRACE") == "1"
    manifest = json.loads(Path("/manifest/tests.json").read_text())
    wanted = [test["id"] for test in manifest["tests"]] + manifest["skipped"]
    context = TestContext()
    plugin = Contexts(context, wanted)
    executor = process.ProcessPoolExecutor
    original_init, original_submit, original_spawn = executor.__init__, executor.submit, executor._spawn_process
    original_popen = subprocess.Popen.__init__
    original_start = BaseProcess.start
    pools = []
    subprocesses = []
    started_children = []
    launches = []
    owner_thread = threading.get_ident()

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if self._mp_context.get_start_method() != "spawn":
            raise RuntimeError("tracer requires spawned workers")
        pool = {"id": len(pools), "created": context.name, "tasks": [], "workers": [],
                "initializer": None if self._initializer is None else self._initializer.__qualname__}
        self._observation_pool = pool
        pools.append(pool)

    def submit(self, func, *args, **kwargs):
        if threading.get_ident() != owner_thread:
            raise RuntimeError("cannot assign queue IDs from multiple submitter threads")
        next_id = self._queue_count
        owner = context.name
        future = original_submit(self, func, *args, **kwargs)
        if self._queue_count != next_id + 1:
            raise RuntimeError("unexpected process-pool task ID")
        self._observation_pool["tasks"].append([next_id, owner, func.__module__, func.__qualname__])
        return future

    def spawn(self):
        # Same CPython spawn queues, initialization and original work items.
        # The extra pool ID belongs to the worker bootstrap envelope only.
        pool = self._observation_pool
        worker = self._mp_context.Process(
            target=sitecustomize.worker,
            args=(pool["id"], self._call_queue, self._result_queue,
                  self._initializer, self._initargs, self._max_tasks_per_child),
        )
        worker.start()
        self._processes[worker.pid] = worker
        pool["workers"].append(worker.pid)

    def popen(self, *args, **kwargs):
        owner = context.name
        original_popen(self, *args, **kwargs)
        subprocesses.append([self.pid, owner])

    def start_child(self):
        original_start(self)
        started_children.append(self.pid)

    def audit_launches(event, args):
        if event in sitecustomize.LAUNCH_EVENTS:
            launches.append(event)

    executor.__init__, executor.submit, executor._spawn_process = init, submit, spawn
    subprocess.Popen.__init__ = popen
    BaseProcess.start = start_child
    sys.addaudithook(audit_launches)
    start = time.perf_counter()
    try:
        status = pytest.main(["-q", "-p", "no:cacheprovider", "--tb=short",
                              "--continue-on-collection-errors", "--timeout=600",
                              "--timeout-method=signal", "tests"], plugins=[plugin])
    finally:
        executor.__init__, executor.submit, executor._spawn_process = original_init, original_submit, original_spawn
        subprocess.Popen.__init__ = original_popen
        BaseProcess.start = original_start
    tracker = multiprocessing.resource_tracker._resource_tracker
    tracker_pid = tracker._pid
    tracker._stop()
    result = plugin.result()
    result["exit_code"] = int(status)
    report = classify(manifest, result)
    report["wall_seconds"] = time.perf_counter() - start
    Path("/result/pytest.json").write_text(json.dumps(result, sort_keys=True))
    Path("/result/completeness.json").write_text(json.dumps(report, sort_keys=True))
    Path("/result/topology.json").write_text(json.dumps({"pools": pools, "subprocesses": subprocesses,
                                                          "started_children": started_children, "launches": launches,
                                                          "resource_tracker": tracker_pid}, sort_keys=True))
    return 0 if report["complete"] and not report["failing_ids"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
