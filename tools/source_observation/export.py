"""Export canonical clean-test cohorts for observed Python source and position reads."""

import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess

from patch_analysis import SOURCE_OBSERVER_NAMES
from selection import REVISION


def static_evidence(source, index):
    names = SOURCE_OBSERVER_NAMES - {"__file__", "__doc__"} | {"read_text", "read_bytes"}
    sets = index["test_sets"]
    global_tests = set()
    inventory = []
    unresolved = []
    standalone = []
    for file, metadata in index["files"].items():
        raw = (source / file).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == metadata["sha256"]
        for node in ast.walk(ast.parse(raw, filename=file)):
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.alias):
                name = node.name.rsplit(".", 1)[-1]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                name = node.value
            else:
                continue
            if name not in names:
                continue
            site = [file, node.lineno, name]
            if not file.startswith(("sqlglot/", "tests/")) and not metadata["lines"]:
                standalone.append(site)
                continue
            inventory.append(site)
            cohort = sets[index["cohorts"].get(file, 0)] if file.startswith("tests/") else []
            if not cohort:
                unresolved.append(site)
            for start, end in cohort:
                global_tests.update(range(start, end + 1))
    return global_tests, sorted(inventory), sorted(unresolved), sorted(standalone)


def contextual_tests(context, ordinals, fixture_users, process_tests):
    if context.startswith("test|"):
        identity, _ = context[5:].rsplit("|", 1)
        return {ordinals[identity]} if identity in ordinals else set()
    if context.startswith("fixture|"):
        fixture, _ = context[8:].rsplit("|", 1)
        return {ordinals[t] for t in fixture_users.get(fixture, []) if t in ordinals}
    if context == "shared:child":
        return process_tests
    return set()


def sha(content):
    return hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("index", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("trace", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    assert subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip() == REVISION
    assert not subprocess.check_output(["git", "-C", str(args.source), "status", "--porcelain", "--untracked-files=all"])
    index_bytes = args.index.read_bytes()
    index = json.loads(index_bytes)
    provenance = json.loads(args.index.with_name("provenance.json").read_bytes())
    manifest = json.loads(args.manifest.read_bytes())
    resources_bytes = args.index.with_name("resources.json").read_bytes()
    resources = json.loads(resources_bytes)
    report = json.loads((args.trace / "completeness.json").read_bytes())
    raw = json.loads((args.trace / "run.json").read_bytes())
    assert report["complete"] and not report["failing_ids"] and raw["exit_code"] == 0
    assert not raw["collection_errors"] and provenance["index_sha256"] == sha(index_bytes)
    assert index["source_revision"] == resources["source_revision"] == REVISION
    ordinals = {test["id"]: ordinal for ordinal, test in enumerate(index["tests"])}
    assert len(ordinals) == report["numbered_count"] == len(manifest["tests"])
    assert ordinals.keys() == {t["id"] for t in manifest["tests"]}
    assert sha(args.manifest.read_bytes()) == provenance["manifest_sha256"] == resources["manifest_sha256"]
    process = resources["process"]
    process_tests = {ordinals[t] for t in process["tests"]} if process["complete"] else set()
    events = {tuple(json.loads(line)) for log in args.trace.glob("observers-*.jsonl")
              for line in log.read_text().splitlines()}
    assert events and any(kind == "source_read" for kind, _, _ in events)
    cohorts = defaultdict(set)
    unresolved = defaultdict(set)
    for kind, file, context in sorted(events):
        assert kind in {"source_read", "__code__", "f_code", "tb_frame"} and file in index["files"]
        tests = contextual_tests(context, ordinals, raw["fixture_users"], process_tests)
        if tests:
            cohorts[file].update(tests)
        elif not context.startswith("test|") or context[5:].rsplit("|", 1)[0] not in manifest["skipped"]:
            unresolved[file].add(context)
    static_tests, static_sites, static_unresolved, standalone_sites = static_evidence(args.source, index)
    artifact = {
        "schema_version": 1,
        "source_revision": REVISION,
        "index_sha256": sha(index_bytes),
        "resources_sha256": sha(resources_bytes),
        "manifest_sha256": provenance["manifest_sha256"],
        "event_sha256": sha(json.dumps(sorted(events), separators=(",", ":")).encode()),
        "tool_sha256": {path.name: sha(path.read_bytes()) for path in sorted(Path(__file__).parent.glob("*.py"))},
        "static_tests": sorted(static_tests),
        "static_sites": static_sites,
        "static_unresolved": static_unresolved,
        "standalone_sites": standalone_sites,
        "tests_by_file": {file: sorted(tests) for file, tests in cohorts.items()},
        "unresolved": {file: sorted(contexts) for file, contexts in unresolved.items()},
    }
    args.output.write_text(json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"{len(events)} observations, {len(cohorts)} files with attributed cohorts, "
          f"{len(unresolved)} files with unresolved contexts, {len(static_tests)} static tests")
    print(f"{len(static_sites)} static sites, {len(static_unresolved)} unresolved static sites")


if __name__ == "__main__":
    main()
