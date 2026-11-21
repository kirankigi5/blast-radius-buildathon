"""Export audited readers from clean access records, without sample labels."""

import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess

REVISION = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("raw", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.source
    manifest = json.loads(args.manifest.read_text())
    run = json.loads((args.raw / "run.json").read_text())
    environment = json.loads((args.raw / "environment.json").read_text())
    ids = {test["id"] for test in manifest["tests"]}
    files = {test["file"] for test in manifest["tests"]}
    assert run["exit_code"] == 0 and not run["collection_errors"]
    assert {item["id"] for item in run["collected"]} == ids | set(manifest["skipped"])
    assert {row["id"] for row in run["reports"] if row["outcome"] == "skipped"} == set(manifest["skipped"])
    assert not any(row["outcome"] == "failed" for row in run["reports"])
    assert ids <= {report["id"] for report in run["reports"] if report["phase"] == "call" and report["outcome"] == "passed"}
    assert subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() == REVISION
    assert not subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"])
    loaders = {"tests/helpers.py"}
    process_files = set()
    for file in sorted(files):
        tree = ast.parse((source / file).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {alias.name for alias in node.names}
                if names & {"subprocess", "multiprocessing", "ProcessPoolExecutor", "get_context"}:
                    process_files.add(file)
                if names & {"FIXTURES_DIR", "load_sql_fixtures", "load_sql_fixture_pairs"}:
                    loaders.add(file)

    def resolve(context):
        if context.startswith("test|"):
            return {context.rsplit("|", 1)[0].split("|", 1)[1]} & ids
        if context.startswith("fixture|"):
            key = context.rsplit("|", 1)[0].split("|", 1)[1]
            return set(run["fixture_users"].get(key, ())) & ids
        return set()

    groups = defaultdict(set)
    spawn_events = set()
    for path in sorted(args.raw.glob("access-*.json")):
        for kind, name, context in json.loads(path.read_text()):
            if kind == "process":
                spawn_events.add((name, context))
            else:
                groups[kind, name].add(context)
    assert (args.raw / "access-1.json").is_file()
    process_users = set().union(*(resolve(context) for _, context in spawn_events))
    process_classes = {identity.rsplit("::", 1)[0] for identity in process_users}
    # Include the complete observed owning classes and every manifest file
    # importing the known process APIs, even if a method did not spawn alone.
    process_users.update(identity for identity in ids if identity.rsplit("::", 1)[0] in process_classes
                         or identity.split("::", 1)[0] in process_files)
    unresolved_spawns = sorted({context for _, context in spawn_events
                                if context != "shared:child" and not resolve(context)})
    process_complete = bool(process_users) and not unresolved_spawns

    resources, directories = {}, {}
    for (kind, name), contexts in sorted(groups.items()):
        readers = set()
        unresolved = set()
        for context in contexts:
            matched = process_users if context == "shared:child" and process_complete else resolve(context)
            if not matched:
                unresolved.add(context)
            readers.update(matched)
        entry = {"readers": sorted(readers), "contexts": sorted(contexts), "unresolved": sorted(unresolved)}
        if kind == "read":
            file = source / name
            if file.is_file():
                entry["sha256"] = sha(file)
                resources[name] = entry
        else:
            directories[name] = entry
    assert resources
    index = {"schema_version": 1, "source_revision": REVISION,
             "manifest_sha256": sha(args.manifest), "files": resources, "directories": directories,
             "process": {"complete": process_complete, "tests": sorted(process_users),
                         "static_files": sorted(process_files), "unresolved": unresolved_spawns,
                         "contexts": sorted({context for _, context in spawn_events})},
             "provenance": {"method": "clean pytest Python audit events and process pool submit contexts; no line tracing",
                            "environment": environment,
                            "loader_source_hashes": {file: sha(source / file) for file in sorted(loaders)},
                            "tool_hashes": {p.name: sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                            "command": "sh tools/resources/run.sh"}}
    args.output.write_text(json.dumps(index, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"{len(resources)} files, {len(directories)} directory records, {len(process_users)} process cohort tests")


if __name__ == "__main__":
    main()
