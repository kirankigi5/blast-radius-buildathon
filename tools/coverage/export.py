"""Audit isolated contexts and export deterministic maps from raw coverage."""

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from coverage import CoverageData
from coverage.exceptions import DataError

from generate import write_json

SRC = Path("/src")
RAW = Path("/raw")
REVISION = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
RAW_PROBLEMS = []


def databases(directory):
    run = json.loads((directory / "run.json").read_text())
    for path in sorted(directory.glob(".coverage.*")):
        if path.name.endswith(("-journal", "-wal", "-shm")):
            continue
        data = CoverageData(basename=str(path))
        try:
            data.read()
        except DataError:
            if str(path) == run["parent_data_file"]:
                raise
            RAW_PROBLEMS.append({"run": directory.name, "file": path.name,
                                 "kind": "unreadable_child_database", "bytes": path.stat().st_size})
            continue
        yield path, data, str(path) == run["parent_data_file"]


def pilot_audit():
    checks = []
    for directory in sorted(p for p in RAW.glob("pilot-*") if p.is_dir()):
        run = json.loads((directory / "run.json").read_text())
        assert len(run["wanted"]) == 1
        nodeid = run["wanted"][0]
        file, *names = nodeid.split("::")
        tree = ast.parse((SRC / file).read_text())
        parent = tree
        for name in names:
            matches = [node for node in parent.body if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name.split("[")[0]]
            assert len(matches) == 1, (nodeid, name)
            parent = matches[0]
        body_lines = set(range(parent.body[0].lineno, parent.end_lineno + 1))
        own_call = set()
        wrong_contexts = set()
        phase_lines = Counter()
        child_files = 0
        for _, data, is_parent in databases(directory):
            if not is_parent:
                child_files += 1
                continue
            for filename in data.measured_files():
                for line, contexts in data.contexts_by_lineno(filename).items():
                    for context in contexts:
                        if context.startswith("test|"):
                            _, identity, phase = context.rsplit("|", 2)
                            if identity != nodeid:
                                wrong_contexts.add(context)
                            phase_lines[phase] += 1
                            if filename == str(SRC / file) and phase == "call" and line in body_lines:
                                own_call.add(line)
        assert own_call, f"No test-body call context for {nodeid}"
        assert not wrong_contexts, wrong_contexts
        assert set(run["phases"].get(nodeid, [])) == {"setup", "call", "teardown"}
        assert not run["collection_errors"], run["collection_errors"]
        checks.append({"id": nodeid, "own_body_call_lines": sorted(own_call),
                       "phase_line_counts": dict(phase_lines), "child_databases": child_files,
                       "pytest_exit_code": run["exit_code"]})
    assert len(checks) == 4, "All four isolated pilots must finish"
    assert checks[-1]["child_databases"] > 0, "Process-pool pilot did not save child coverage"
    result = {"passed": True, "isolated_tests": checks}
    write_json(RAW / "pilot-audit.json", result)
    return result


def ranges(values):
    result = []
    for value in sorted(set(values)):
        if result and value == result[-1][1] + 1:
            result[-1][1] = value
        else:
            result.append([value, value])
    return result


class Sets:
    def __init__(self):
        self.values = []
        self.lookup = {}
        self.add([])

    def add(self, values):
        key = tuple(sorted(set(values)))
        if key not in self.lookup:
            self.lookup[key] = len(self.values)
            self.values.append(ranges(key))
        return self.lookup[key]


def source_ranges(tree):
    found = []

    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            next_prefix = prefix
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
                first = min([child.lineno] + [d.lineno for d in child.decorator_list])
                found.append({"name": name, "kind": type(child).__name__, "start": first, "end": child.end_lineno})
                next_prefix = name
            walk(child, next_prefix)

    walk(tree)
    return sorted(found, key=lambda row: (row["start"], row["end"], row["name"]))


def export():
    manifest_raw = Path("/manifest/tests.json").read_bytes()
    manifest = json.loads(manifest_raw)
    full = json.loads((RAW / "full/run.json").read_text())
    collected = defaultdict(list)
    for item in full["collected"]:
        collected[item["id"]].append(item)
    manifest_ids = [test["id"] for test in manifest["tests"]]
    assert len(manifest_ids) == len(set(manifest_ids)), "Duplicate manifest identities"
    canonical = sorted(set(manifest_ids))
    ordinal = {identity: i for i, identity in enumerate(canonical)}
    tests = []
    ambiguous = []
    unmatched = []
    failures = sorted({r["id"] for r in full["reports"] if r["outcome"] == "failed"})
    skipped = sorted({r["id"] for r in full["reports"] if r["outcome"] == "skipped"})
    reports_by_id = defaultdict(list)
    for report in full["reports"]:
        reports_by_id[report["id"]].append(report)
    for entry in sorted(manifest["tests"], key=lambda e: e["id"]):
        identity = entry["id"]
        matches = collected[identity]
        status = "matched" if len(matches) == 1 and matches[0]["file"] == entry["file"] else "unmatched"
        if len(matches) > 1:
            status = "ambiguous"
            ambiguous.append(identity)
        elif status != "matched":
            unmatched.append(identity)
        passed_call = any(r["phase"] == "call" and r["outcome"] == "passed" for r in reports_by_id[identity])
        incomplete = status != "matched" or identity in failures or identity in skipped or not passed_call or set(full["phases"].get(identity, [])) != {"setup", "call", "teardown"}
        tests.append({"id": identity, "file": entry["file"], "manifest_number": entry["number"],
                      "match": status, "phases": full["phases"].get(identity, []),
                      "incomplete": incomplete})

    # Each observed line retains both individual test users and shared-context
    # identifiers. Child-process lines are always conservative shared execution.
    line_tests = defaultdict(lambda: defaultdict(set))
    line_shared = defaultdict(lambda: defaultdict(set))
    shared_info = {}
    invalid_paths = set()
    invalid_lines = []
    child_databases = 0
    direct_phase_counts = Counter()
    test_phase_counts = defaultdict(Counter)
    source_paths = {str(p): p for p in SRC.rglob("*.py") if ".git" not in p.parts}
    virtual_files = set()
    virtual_observations = set()
    virtual_tests = set()
    virtual_shared = set()
    for directory in [RAW / "collect", *sorted(p for p in RAW.glob("pilot-*") if p.is_dir()), RAW / "full"]:
        run = json.loads((directory / "run.json").read_text())
        for path, data, is_parent in databases(directory):
            if not is_parent:
                child_databases += 1
            for filename in sorted(data.measured_files()):
                source = Path(filename)
                if not source.is_relative_to(SRC):
                    invalid_paths.add(filename)
                    continue
                physical = filename in source_paths
                if not physical:
                    # SQLGlot eval/compile uses generated expressions as code
                    # filenames. They aren't repository paths (some exceed OS
                    # filename limits). Retain their contexts as unbacked code.
                    virtual_files.add(filename)
                file = str(source.relative_to(SRC))
                length = len(source.read_text().splitlines()) if physical else 0
                for line, contexts in sorted(data.contexts_by_lineno(filename).items()):
                    if physical and not 1 <= line <= length:
                        invalid_lines.append([file, line])
                        continue
                    for context in sorted(contexts):
                        if is_parent and context.startswith("test|"):
                            _, identity, phase = context.rsplit("|", 2)
                            assert identity in ordinal, identity
                            if physical:
                                line_tests[file][line].add(ordinal[identity])
                            else:
                                virtual_tests.add(ordinal[identity])
                            direct_phase_counts[phase] += 1
                            test_phase_counts[identity][phase] += 1
                        else:
                            key = context if is_parent else "shared:process"
                            if not key:
                                key = "shared:unattributed"
                            consumers = []
                            kind = "global"
                            if is_parent and key.startswith("fixture|"):
                                _, fixture_key, phase = key.rsplit("|", 2)
                                consumers = [ordinal[n] for n in run["fixture_users"].get(fixture_key, []) if n in ordinal]
                                kind = "fixture"
                                if physical:
                                    line_tests[file][line].update(consumers)
                                else:
                                    virtual_tests.update(consumers)
                            info = shared_info.setdefault(key, {"kind": kind, "consumers": set()})
                            info["consumers"].update(consumers)
                            if physical:
                                line_shared[file][line].add(key)
                            else:
                                virtual_shared.add(key)
                        if not physical:
                            virtual_observations.add((filename, line, context if is_parent else "shared:process"))
    assert not invalid_paths, sorted(invalid_paths)
    # Coverage can report synthetic line zero for empty modules. Preserve it in
    # the audit; it is not a valid selectable source line.
    assert all(line == 0 for _, line in invalid_lines), invalid_lines
    shared_names = sorted(shared_info)
    shared_ordinals = {name: i for i, name in enumerate(shared_names)}
    test_sets = Sets()
    shared_sets = Sets()
    files = {}
    ast_errors = []
    for source in sorted(source_paths.values()):
        file = str(source.relative_to(SRC))
        content = source.read_bytes()
        text = content.decode("utf-8")
        length = len(text.splitlines())
        rows = []
        all_lines = sorted(set(line_tests[file]) | set(line_shared[file]))
        for line in all_lines:
            covering = test_sets.add(line_tests[file][line])
            sharing = shared_sets.add(shared_ordinals[k] for k in line_shared[file][line])
            if rows and rows[-1][1] == line - 1 and rows[-1][2:] == [covering, sharing]:
                rows[-1][1] = line
            else:
                rows.append([line, line, covering, sharing])
        definitions = []
        try:
            definitions = source_ranges(ast.parse(text, filename=file))
        except SyntaxError as error:
            ast_errors.append({"file": file, "error": str(error)})
        for definition in definitions:
            users = set()
            contexts = set()
            for line in all_lines:
                if definition["start"] <= line <= definition["end"]:
                    users.update(line_tests[file][line])
                    contexts.update(shared_ordinals[k] for k in line_shared[file][line])
            definition["tests"] = test_sets.add(users)
            definition["shared"] = shared_sets.add(contexts)
        files[file] = {"sha256": hashlib.sha256(content).hexdigest(), "line_count": length,
                       "lines": rows, "definitions": definitions,
                       "observed": bool(rows)}
    shared_contexts = [
        {"id": key, "kind": shared_info[key]["kind"],
         "consumers": test_sets.add(shared_info[key]["consumers"])} for key in shared_names
    ]
    cohorts = defaultdict(set)
    for identity, index in ordinal.items():
        cohorts[identity.split("::")[0]].add(index)
        if len(identity.split("::")) > 2:
            cohorts[identity.rsplit("::", 1)[0]].add(index)
    cohort_map = {key: test_sets.add(value) for key, value in sorted(cohorts.items())}
    unbacked = {"kind": "generated_or_unbacked_python_code", "virtual_files": len(virtual_files),
                "line_context_observations": len(virtual_observations),
                "tests": test_sets.add(virtual_tests),
                "shared": shared_sets.add(shared_ordinals[key] for key in virtual_shared),
                "policy": "No fabricated source paths; changes to dynamic code or uncertain dependencies require conservative fallback."}
    for test in tests:
        test["phase_line_observations"] = {
            phase: test_phase_counts[test["id"]][phase] for phase in ("setup", "call", "teardown")
        }
        if test["phase_line_observations"]["call"] == 0:
            test["incomplete"] = True
    audit = {
        "manifest_count": len(tests), "matched_count": sum(t["match"] == "matched" for t in tests),
        "ambiguous": ambiguous, "unmatched": unmatched,
        "collected_count": len(full["collected"]),
        "unexpected_collected": sorted(set(collected) - set(canonical) - set(manifest["skipped"])),
        "declared_skipped": manifest["skipped"], "observed_skipped": skipped,
        "collection_errors": full["collection_errors"], "clean_test_failures": failures,
        "pytest_exit_code": full["exit_code"],
        "incomplete_tests": [t["id"] for t in tests if t["incomplete"]],
        "source_files": len(files), "observed_source_files": sum(f["observed"] for f in files.values()),
        "unobserved_source_files": [file for file, item in files.items() if not item["observed"]],
        "ast_errors": ast_errors, "synthetic_line_zero": sorted({tuple(row) for row in invalid_lines}),
        "child_databases": child_databases, "phase_observations": dict(direct_phase_counts),
        "raw_trace_problems": RAW_PROBLEMS,
        "raw_trace_complete": not RAW_PROBLEMS,
        "unbacked_execution": unbacked,
        "pilot": json.loads((RAW / "pilot-audit.json").read_text()),
        "limitations": ["Dynamic executed-line evidence is not proof of absence of dependencies.",
                        "Subprocess coverage is shared globally rather than attributed to tasks.",
                        "Shared mutable state and caches require class/file cohort widening.",
                        "Non-Python fixture/data reads and native-library internals are not line traced.",
                        "Untaken branches, new/deleted code, import changes and unsupported paths require fallback."],
    }
    index = {"schema_version": 1, "source_revision": REVISION,
             "semantics": {"identity_table": "Canonical pytest node IDs; table offsets are not manifest numbers.",
                           "line_record": ["start_inclusive", "end_inclusive", "test_set", "shared_set"],
                           "sets": "Sorted inclusive ranges of identity/shared-context table offsets.",
                           "absence_means_safe_to_skip": False,
                           "coverage_kind": "Observed Python lines, not exhaustive dependency evidence.",
                           "raw_trace_complete": not RAW_PROBLEMS,
                           "global_shared_policy": "Select all incoming tests if affected.",
                           "fixture_shared_policy": "Select all recorded consumers; empty or uncertain consumers require all tests."},
             "tests": tests,
             "test_sets": test_sets.values, "shared_contexts": shared_contexts,
             "shared_sets": shared_sets.values, "files": files, "cohorts": cohort_map,
             "unbacked_execution": unbacked}
    destination = Path("/artifacts")
    write_json(destination / "index.json", index)
    write_json(destination / "audit.json", audit)
    environment = json.loads((RAW / "full/environment.json").read_text())
    tools = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path("/tool").glob("*.py"))}
    write_json(destination / "provenance.json", {
        "source_revision": REVISION, "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "base_image": "python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90",
        "environment": environment, "tool_sha256": tools,
        "generation_command": "python3 tools/coverage/run.py --work .local/coverage-final",
        "numeric_id_contract": "Numbers are contiguous within tests.json; cross-batch identity stability is not promised. Resolve exact canonical IDs against each incoming manifest.",
        "index_sha256": hashlib.sha256((destination / "index.json").read_bytes()).hexdigest(),
    })
    print(json.dumps({k: v for k, v in audit.items() if k not in ("pilot", "limitations")}, indent=2))
    print("Artifact bytes:", {p.name: p.stat().st_size for p in sorted(destination.glob("*.json"))})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-only", action="store_true")
    args = parser.parse_args()
    if args.pilot_only:
        print(json.dumps(pilot_audit(), indent=2))
    else:
        export()
