"""Run only in the offline Linux preprocessing image, with /src read-only."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
import time

import coverage


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("collect", "pilot", "full"), required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--node")
    args = parser.parse_args()
    target = Path("/raw") / args.name
    target.mkdir(parents=True, exist_ok=False)
    manifest_bytes = Path("/manifest/tests.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    requirements = Path("/opt/requirements.lock").read_bytes()
    for requirement in requirements.decode().splitlines():
        name, expected = requirement.split("==")
        assert importlib.metadata.version(name) == expected, requirement
    wanted = [t["id"] for t in manifest["tests"]] + manifest["skipped"]
    if args.node:
        assert args.node in wanted, args.node
        wanted = [args.node]
    rc = target / "coverage.ini"
    rc.write_text(
        "[run]\nsource = /src\nparallel = True\nconcurrency = multiprocessing,thread\n"
        "patch = subprocess,_exit\nsigterm = True\ncontext = shared:process\n"
        f"data_file = {target}/.coverage\n"
    )
    os.environ["COVERAGE_RCFILE"] = str(rc)
    cov = coverage.Coverage(config_file=str(rc), context="", data_suffix=True)
    start = time.perf_counter()
    cov.start()
    # Start tracing before pytest imports or collects any pinned source.
    from pytest_contexts import Contexts
    import pytest
    plugin = Contexts(cov, wanted, collect_only=args.mode == "collect")
    pytest_args = ["--rootdir=/src", "-p", "no:cacheprovider", "--tb=short", "-q",
                   "--continue-on-collection-errors", "--timeout=600", "tests"]
    if args.mode == "collect":
        pytest_args.insert(0, "--collect-only")
    try:
        exit_code = int(pytest.main(pytest_args, plugins=[plugin]))
    finally:
        # Docker exits when PID 1 exits. Wait for Python's resource tracker so
        # its coverage atexit handler finishes before Docker kills remaining
        # children. Pool workers have already been joined by pytest cleanup.
        import multiprocessing.resource_tracker
        tracker = multiprocessing.resource_tracker._resource_tracker
        tracker_pid = tracker._pid
        with plugin.context("shared:process-cleanup"):
            tracker._stop()
        cov.stop()
        cov.save()
    result = plugin.result()
    result.update({"mode": args.mode, "wanted": wanted, "exit_code": exit_code,
                   "elapsed_seconds": time.perf_counter() - start,
                   "parent_data_file": cov.get_data().data_filename(),
                   "resource_tracker_pid": tracker_pid,
                   "resource_tracker_joined": True,
                   "pytest_args": pytest_args})
    write_json(target / "run.json", result)
    write_json(target / "environment.json", {
        "python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
        "sqlite": sqlite3.sqlite_version, "coverage": coverage.__version__,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "requirements_lock_sha256": hashlib.sha256(requirements).hexdigest(),
        "tool_sha256": {name: hashlib.sha256((Path('/tool') / name).read_bytes()).hexdigest()
                        for name in ("generate.py", "pytest_contexts.py")},
        "packages": dict(sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())),
        "environment": {k: os.environ.get(k) for k in
                        ("SKIP_INTEGRATION", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE",
                         "PYTHONHASHSEED", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")},
    })
    print(json.dumps({"name": args.name, "exit_code": exit_code,
                      "elapsed_seconds": result["elapsed_seconds"]}), flush=True)
    # Test/collection failures are retained for the exporter instead of losing
    # the useful partial data. Infrastructure exceptions still fail the command.


if __name__ == "__main__":
    main()
