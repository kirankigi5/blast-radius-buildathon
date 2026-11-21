"""Collect observation contexts alongside the existing full-manifest checks."""

import json
import multiprocessing.resource_tracker
from pathlib import Path

import pytest
import sitecustomize

from pytest_contexts import Contexts
from stage5_label import classify


class ObservationContexts:
    def switch_context(self, name):
        sitecustomize.context = name


def main():
    manifest = json.loads(Path("/manifest/tests.json").read_text())
    wanted = [test["id"] for test in manifest["tests"]] + manifest["skipped"]
    plugin = Contexts(ObservationContexts(), wanted)
    status = pytest.main(["-q", "-p", "no:cacheprovider", "--tb=short",
                          "--continue-on-collection-errors", "--timeout=600",
                          "--timeout-method=signal", "tests"], plugins=[plugin])
    multiprocessing.resource_tracker._resource_tracker._stop()
    result = plugin.result()
    result["exit_code"] = int(status)
    report = classify(manifest, result)
    Path("/result/run.json").write_text(json.dumps(result, sort_keys=True))
    Path("/result/completeness.json").write_text(json.dumps(report, sort_keys=True))
    return 0 if report["complete"] and not report["failing_numbers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
