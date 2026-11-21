"""Offline full-manifest labeling. Run only in a clean or independently patched test tree."""

import json
import multiprocessing.resource_tracker
from pathlib import Path
import time

import pytest
from pytest_contexts import Contexts


class NullCoverage:
    def switch_context(self, name):
        pass


def classify(manifest, result):
    entries = {test["id"]: test for test in manifest["tests"]}
    reports = {}
    for report in result["reports"]:
        reports.setdefault(report["id"], []).append(report)
    collected = {}
    for item in result["collected"]:
        collected[item["id"]] = collected.get(item["id"], 0) + 1
    import_errors = {error["id"] for error in result["collection_errors"]
                     if error["id"] in {test["file"] for test in entries.values()}}
    errors_unknown = [error["id"] for error in result["collection_errors"] if error["id"] not in import_errors]
    failures = {}
    incomplete = []
    for node, test in entries.items():
        rows = reports.get(node, [])
        bad = [row for row in rows if row["outcome"] == "failed"]
        if test["file"] in import_errors:
            failures[node] = ["file_collection_error"]
            continue
        if bad:
            failures[node] = sorted({
                "timeout" if "Timeout >" in row.get("detail", "") else
                "subtest" if "Subtest" in row["report_type"] else row["phase"] for row in bad
            })
        phases = {row["phase"] for row in rows}
        expected = {"setup", "teardown"}
        if any(row["phase"] == "setup" and row["outcome"] == "passed" for row in rows):
            expected.add("call")
        if (collected.get(node) != 1 or not expected <= phases
                or any(row["outcome"] == "skipped" for row in rows)):
            incomplete.append(node)
    return {"complete": not incomplete and not errors_unknown and result["exit_code"] in (0, 1),
            "numbered_count": len(entries), "incomplete": sorted(incomplete),
            "unknown_collection_errors": sorted(errors_unknown), "file_collection_errors": sorted(import_errors),
            "failing_ids": sorted(failures), "failing_numbers": sorted(entries[node]["number"] for node in failures),
            "failure_types": failures, "exit_code": result["exit_code"],
            "subtest_report_count": sum("Subtest" in row["report_type"] for row in result["reports"])}


def main():
    manifest = json.loads(Path("/manifest/tests.json").read_text())
    wanted = [test["id"] for test in manifest["tests"]] + manifest["skipped"]
    plugin = Contexts(NullCoverage(), wanted)
    start = time.perf_counter()
    exit_code = pytest.main(["-q", "-p", "no:cacheprovider", "--tb=short",
                             "--continue-on-collection-errors", "--timeout=600",
                             "--timeout-method=signal", "tests"], plugins=[plugin])
    multiprocessing.resource_tracker._resource_tracker._stop()
    result = plugin.result()
    result["exit_code"] = int(exit_code)
    report = classify(manifest, result)
    report["wall_seconds"] = time.perf_counter() - start
    Path("/result/raw.json").write_text(json.dumps(result, sort_keys=True))
    Path("/result/labels.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
