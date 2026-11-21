"""Collect clean test ownership of file access and process pool submissions."""

from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing.resource_tracker
from pathlib import Path

import pytest
import sitecustomize as access

from pytest_contexts import Contexts


class AccessContexts:
    def switch_context(self, name):
        access.context = name


def main():
    manifest = json.loads(Path("/manifest/tests.json").read_text())
    wanted = [row["id"] for row in manifest["tests"]] + manifest["skipped"]
    plugin = Contexts(AccessContexts(), wanted)
    original_submit = ProcessPoolExecutor.submit

    def submit(self, function, *args, **kwargs):
        # Pools may live across several test methods. Record each submission,
        # independently of which test caused the worker to be spawned.
        access.events.add(("process", "pool_submit", access.context))
        return original_submit(self, function, *args, **kwargs)

    ProcessPoolExecutor.submit = submit
    try:
        status = pytest.main(["-q", "-p", "no:cacheprovider", "--tb=short",
                              "--continue-on-collection-errors", "--timeout=600", "tests"], plugins=[plugin])
    finally:
        ProcessPoolExecutor.submit = original_submit
        multiprocessing.resource_tracker._resource_tracker._stop()
        access.flush()
    result = plugin.result()
    result["exit_code"] = int(status)
    Path("/raw/run.json").write_text(json.dumps(result, sort_keys=True))
    return int(status)


if __name__ == "__main__":
    raise SystemExit(main())
