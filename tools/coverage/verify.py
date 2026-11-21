"""Validate exported references against the exact clean source and manifest."""

import ast
import hashlib
import json
from pathlib import Path


def unpack(groups, maximum):
    values = set()
    previous = -2
    for first, last in groups:
        assert 0 <= first <= last < maximum
        assert first > previous + 1, "ranges must be sorted, disjoint and merged"
        values.update(range(first, last + 1))
        previous = last
    return values


def verify():
    root = Path("/src")
    artifacts = Path("/artifacts")
    index = json.loads((artifacts / "index.json").read_text())
    audit = json.loads((artifacts / "audit.json").read_text())
    provenance = json.loads((artifacts / "provenance.json").read_text())
    manifest = json.loads(Path("/manifest/tests.json").read_text())
    identities = [test["id"] for test in index["tests"]]
    assert identities == sorted(set(identities))
    assert set(identities) == {test["id"] for test in manifest["tests"]}
    entry_by_id = {test["id"]: test for test in manifest["tests"]}
    for test in index["tests"]:
        entry = entry_by_id[test["id"]]
        assert test["file"] == entry["file"] == test["id"].split("::")[0]
        assert test["manifest_number"] == entry["number"]
        assert (root / test["file"]).is_file()
    tests = [unpack(groups, len(identities)) for groups in index["test_sets"]]
    shared = [unpack(groups, len(index["shared_contexts"])) for groups in index["shared_sets"]]
    assert len({tuple(sorted(s)) for s in tests}) == len(tests)
    assert len({tuple(sorted(s)) for s in shared}) == len(shared)
    for context in index["shared_contexts"]:
        assert 0 <= context["consumers"] < len(tests)
    unbacked = index["unbacked_execution"]
    assert 0 <= unbacked["tests"] < len(tests) and 0 <= unbacked["shared"] < len(shared)
    for name, set_id in index["cohorts"].items():
        assert tests[set_id] == {i for i, identity in enumerate(identities) if identity.startswith(name + "::")}
    line_records = 0
    definitions = 0
    for file, item in index["files"].items():
        source = root / file
        assert not Path(file).is_absolute() and ".." not in Path(file).parts
        assert source.resolve().is_relative_to(root) and source.is_file()
        content = source.read_bytes()
        assert hashlib.sha256(content).hexdigest() == item["sha256"]
        assert len(content.decode("utf-8").splitlines()) == item["line_count"]
        previous = 0
        lines = {}
        for first, last, test_set, shared_set in item["lines"]:
            assert previous < first <= last <= item["line_count"]
            assert 0 <= test_set < len(tests) and 0 <= shared_set < len(shared)
            for line in range(first, last + 1):
                lines[line] = (tests[test_set], shared[shared_set])
            previous = last
            line_records += 1
        valid_ranges = set()
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    first = min([node.lineno] + [d.lineno for d in node.decorator_list])
                    valid_ranges.add((type(node).__name__, first, node.end_lineno))
        except SyntaxError:
            assert any(error["file"] == file for error in audit["ast_errors"])
        for definition in item["definitions"]:
            first, last = definition["start"], definition["end"]
            assert (definition["kind"], first, last) in valid_ranges
            assert 1 <= first <= last <= item["line_count"]
            users, contexts = set(), set()
            for line, (covering, sharing) in lines.items():
                if first <= line <= last:
                    users.update(covering)
                    contexts.update(sharing)
            assert users == tests[definition["tests"]]
            assert contexts == shared[definition["shared"]]
            definitions += 1
    assert provenance["index_sha256"] == hashlib.sha256((artifacts / "index.json").read_bytes()).hexdigest()
    assert provenance["manifest_sha256"] == hashlib.sha256(Path("/manifest/tests.json").read_bytes()).hexdigest()
    assert len(index["tests"]) == audit["manifest_count"]
    assert index["semantics"]["raw_trace_complete"] == audit["raw_trace_complete"] == (not audit["raw_trace_problems"])
    assert set(audit["incomplete_tests"]) == {test["id"] for test in index["tests"] if test["incomplete"]}
    print(json.dumps({"valid": True, "tests": len(identities), "files": len(index["files"]),
                      "line_records": line_records, "ast_definitions": definitions,
                      "test_sets": len(tests), "shared_sets": len(shared)}))


if __name__ == "__main__":
    verify()
