"""Synthetic coverage and clean-source examples; no sample failure labels."""

import ast
import difflib
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from patch_analysis import (
    UncertainPatch, affected_functions, analyze, import_comment_insertion, localized_statement,
    observer_sensitive_edits, parse_patch, reconstruct, shifted_line,
)
from selection import REVISION, SelectionPolicy
from selector import schedule

SOURCE = "def f(x):\n    value = x + 1\n    return value\n\ndef g(x):\n    return x - 1\n"


def diff(old, new, file="pkg/code.py"):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        fromfile=f"a/{file}", tofile=f"b/{file}"))


class PatchTests(unittest.TestCase):
    def check_patch(self, old, new):
        change = parse_patch(diff(old, new))[0]
        actual, removed, added = reconstruct(old, change)
        self.assertEqual(actual, new)
        return removed, added

    def test_multiple_shifted_hunks(self):
        old = "".join(f"line {i}\n" for i in range(30))
        new = old.replace("line 1\n", "line 1\ninserted\n").replace("line 25\n", "changed\n")
        self.check_patch(old, new)

    def test_statement_precision_rejects_new_paths_bindings_and_decorated_bodies(self):
        old = "def choose(flag):\n    if flag:\n        return 1\n    return 2\n"

        def eligible(before, after):
            removed, added = self.check_patch(before, after)
            original, changed = analyze(before), analyze(after)
            affected = affected_functions(original, changed, removed, added)
            return localized_statement(original, changed, affected, removed, added)

        self.assertTrue(eligible(old, old.replace("return 1", "return 3")))
        self.assertFalse(eligible(old, old.replace("if flag", "if not flag")))
        self.assertFalse(eligible(old, old.replace("    return 2", "    if flag is None:\n        return 3\n    return 2")))
        self.assertFalse(eligible("@cached\n" + old, "@cached\n" + old.replace("return 1", "return 3")))
        self.assertTrue(eligible("def f():\n    pass\n    return 1\n", "def f():\n    return 1\n"))
        self.assertFalse(eligible("def f():\n    x = 1\n    return x\n", "def f():\n    return x\n"))

    def test_zero_context_insertion_and_scope_boundary(self):
        new = SOURCE.replace("    return value\n", "    return value\n    unreachable = True\n")
        removed, added = self.check_patch(SOURCE, new)
        affected = affected_functions(analyze(SOURCE), analyze(new), removed, added)
        self.assertEqual(affected, {("f",)})
        patch = "--- a/pkg/code.py\n+++ b/pkg/code.py\n@@ -0,0 +1 @@\n+# preface\n"
        self.assertEqual(reconstruct(SOURCE, parse_patch(patch)[0])[0], "# preface\n" + SOURCE)

    def test_import_gap_comment_keeps_original_text_and_line_offset(self):
        old = "import a\n\nimport b\n"
        new = "import a\n# Import order is intentional\n\nimport b\n"
        removed, added = self.check_patch(old, new)
        self.assertEqual(import_comment_insertion(old, new, ast.parse(new), removed, added), 2)
        patch = "--- a/pkg/code.py\n+++ b/pkg/code.py\n@@ -1,0 +2 @@\n+# Import order is intentional\n"
        self.assertEqual(shifted_line(parse_patch(patch)[0]), 2)

    def test_import_gap_directives_strings_and_mixed_file_content_stay_unmatched(self):
        old = "import a\n\nimport b\nVALUE = 1\n"
        changed = [old.replace("\n\n", f"\n{line}\n\n") for line in (
            "# coding: utf-8", "# type: ignore", "# Ruff ignore here", "# fmt: off", "#!/bin/python",
        )] + [
            '"Module docs"\n' + old,
            "# Import order is intentional\n" + old,
            old.replace("\n\n", "\n# Import order is intentional\n\n").replace("VALUE = 1", "VALUE = 2"),
        ]
        for new in changed:
            removed, added = self.check_patch(old, new)
            with self.subTest(new=new):
                self.assertIsNone(import_comment_insertion(old, new, ast.parse(new), removed, added))
        triple = '"""Example\nimport a\n\nimport b\n"""\n'
        new = triple.replace("\n\n", "\n# This belongs to the string\n\n")
        removed, added = self.check_patch(triple, new)
        self.assertIsNone(import_comment_insertion(triple, new, ast.parse(new), removed, added))

    def test_companion_guard_catches_source_inspection_and_metadata(self):
        self.assertTrue(observer_sensitive_edits("value = fn.__code__.co_firstlineno\n", {1}))
        self.assertTrue(observer_sensitive_edits("value = 1  # type: ignore\n", {1}))
        self.assertTrue(observer_sensitive_edits("value = Path(path).read_bytes()\n", {1}))
        self.assertFalse(observer_sensitive_edits("value = 1  # An ordinary explanation\n", {1}))

    def test_no_final_newline(self):
        patch = "--- a/pkg/code.py\n+++ b/pkg/code.py\n@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n"
        self.assertEqual(reconstruct("old", parse_patch(patch)[0])[0], "new")

    def test_multiple_independent_files(self):
        patches = parse_patch(diff(SOURCE, SOURCE.replace("x + 1", "x + 2")) + diff("a\n", "b\n", "pkg/other.py"))
        self.assertEqual(len(patches), 2)
        self.assertEqual(reconstruct("a\n", patches[1])[0], "b\n")

    def test_offsets_context_and_truncation_fail_closed(self):
        valid = diff(SOURCE, SOURCE.replace("x + 1", "x + 2"))
        with self.assertRaises(UncertainPatch):
            reconstruct(SOURCE.replace("value =", "changed ="), parse_patch(valid)[0])
        with self.assertRaises(UncertainPatch):
            parse_patch(valid.rsplit("\n", 2)[0] + "\n")
        with self.assertRaises(UncertainPatch):
            parse_patch("--- a/../../escape.py\n+++ b/../../escape.py\n")

    def test_addition_deletion_and_rename(self):
        added = parse_patch("--- /dev/null\n+++ b/new.py\n@@ -0,0 +1,2 @@\n+def f():\n+    return 1\n")[0]
        self.assertIsNone(added.old)
        self.assertEqual(reconstruct("", added)[0], "def f():\n    return 1\n")
        deleted = parse_patch("--- a/old.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n")[0]
        self.assertEqual(reconstruct("old\n", deleted)[0], "")
        renamed = parse_patch("diff --git a/old.py b/new.py\nsimilarity index 100%\nrename from old.py\nrename to new.py\n")[0]
        self.assertEqual((renamed.old, renamed.new), ("old.py", "new.py"))
        renamed = parse_patch("diff --git a/a/old.py b/b/new.py\nrename from a/old.py\nrename to b/new.py\n")[0]
        self.assertEqual((renamed.old, renamed.new), ("a/old.py", "b/new.py"))

    def test_repeated_names_pair_by_occurrence(self):
        old = "class C:\n    def f(self):\n        return 1\n    def f(self):\n        return 2\n"
        new = old.replace("return 2", "return 3")
        removed, added = self.check_patch(old, new)
        self.assertEqual(affected_functions(analyze(old), analyze(new), removed, added), {("C", "f#2")})

    def test_adjacent_comment_is_routed_to_a_method(self):
        old = "class C:\n    def f(self):\n        return 1\n"
        new = old.replace("    def f", "    # explanation\n    def f")
        removed, added = self.check_patch(old, new)
        self.assertEqual(affected_functions(analyze(old), analyze(new), removed, added), {("C", "f")})


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.base = self.root / "base"
        self.maps = self.root / "maps"
        self.base.mkdir(); self.maps.mkdir()
        self.incoming = [{"number": n, "id": f"tests/test_{name}.py::{name.upper()}::test_value",
                          "file": f"tests/test_{name}.py", "seconds": 1.0}
                         for n, name in enumerate("abc")]
        contents = {"pkg/code.py": SOURCE, **{t["file"]: "from pkg.code import f\n" for t in self.incoming}}
        self.index = {
            "schema_version": 1, "source_revision": REVISION,
            "tests": [{**t, "incomplete": False} for t in self.incoming],
            "test_sets": [[], [[0, 0]], [[1, 1]], [[2, 2]], [[0, 1]]],
            "shared_sets": [[], [[0, 0]], [[1, 1]], [[2, 2]]],
            "shared_contexts": [{"id": "shared:collection", "kind": "global", "consumers": 0},
                                {"id": "shared:process", "kind": "global", "consumers": 0},
                                {"id": "fixture:shared", "kind": "fixture", "consumers": 2}],
            "files": {name: {"sha256": hashlib.sha256(text.encode()).hexdigest(), "lines": []}
                      for name, text in contents.items()},
            "cohorts": {key: i + 1 for i, t in enumerate(self.incoming)
                        for key in (t["file"], t["id"].rsplit("::", 1)[0])},
        }
        self.index["files"]["pkg/code.py"]["lines"] = [[1, 1, 0, 1], [2, 3, 1, 0], [5, 5, 0, 1], [6, 6, 2, 0]]
        for name, text in contents.items():
            p = self.base / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        (self.base / "REVISION").write_text(REVISION + "\n")

    def policy(self, incoming=None):
        raw = json.dumps(self.index).encode()
        (self.maps / "index.json").write_bytes(raw)
        (self.maps / "audit.json").write_text(json.dumps({"raw_trace_complete": True, "collection_errors": []}))
        (self.maps / "provenance.json").write_text(json.dumps({"source_revision": REVISION,
                                                               "index_sha256": hashlib.sha256(raw).hexdigest()}))
        return SelectionPolicy(self.incoming if incoming is None else incoming, self.maps, self.base)

    def test_body_edit_ignores_import_only_definition_lines(self):
        selected, reason = self.policy().select(diff(SOURCE, SOURCE.replace("x + 1", "x + 2")))
        self.assertEqual(selected, {0})
        self.assertFalse(reason["fallback"])

    def comment_evidence(self, unresolved=None):
        comment_path = "sqlglot/comment.py"
        comment_source = "import math\nimport re\ndef position():\n    return 7\n"
        body_path = "sqlglot/behavior.py"
        for name, source, ranges in (
            (comment_path, comment_source, [[1, 2, 0, 1], [4, 4, 3, 0]]),
            (body_path, SOURCE, [[2, 3, 1, 0]]),
        ):
            path = self.base / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(source)
            self.index["files"][name] = {"sha256": hashlib.sha256(source.encode()).hexdigest(), "lines": ranges}
        resources = json.dumps({"schema_version": 1, "source_revision": REVISION, "manifest_sha256": None}).encode()
        (self.maps / "resources.json").write_bytes(resources)
        evidence = {"schema_version": 1, "source_revision": REVISION, "manifest_sha256": None,
                    "index_sha256": hashlib.sha256(json.dumps(self.index).encode()).hexdigest(),
                    "resources_sha256": hashlib.sha256(resources).hexdigest(), "static_unresolved": [],
                    "static_tests": [], "tests_by_file": {comment_path: [1]}, "unresolved": unresolved or {}}
        (self.maps / "source_observers.json").write_text(json.dumps(evidence))
        change = diff(comment_source, comment_source.replace("import re", "# This import follows math\nimport re"), comment_path)
        return change, body_path

    def test_import_comment_adds_observers_and_shifted_execution_to_behavior(self):
        change, file = self.comment_evidence()
        selected, reason = self.policy().select(change + diff(SOURCE, SOURCE.replace("x + 1", "x + 2"), file))
        self.assertEqual(selected, {0, 1, 2})
        self.assertFalse(reason["fallback"])
        self.assertIn("source_observers:sqlglot/comment.py", reason["reasons"])
        self.assertIn("shifted_python_execution:sqlglot/comment.py", reason["reasons"])
        self.assertIn("function:sqlglot/behavior.py:f", reason["reasons"])

    def test_comment_fallbacks_for_shared_source_reads_or_companion_observers(self):
        change, _ = self.comment_evidence({"sqlglot/comment.py": ["shared:collection"]})
        _, reason = self.policy().select(change)
        self.assertIn("fallback:unattributed_source_or_position_observation", reason["reasons"])
        change, file = self.comment_evidence()
        for companion in (SOURCE.replace("return value", "return f.__code__.co_firstlineno"),
                          SOURCE.replace("    value =", '    "A new docstring"\n    value =', 1)):
            _, reason = self.policy().select(change + diff(SOURCE, companion, file))
            self.assertIn("fallback:unresolved_companion_source_observation", reason["reasons"])

    def test_manifest_renumbering_and_unknown_incoming(self):
        incoming = [{**test, "number": (test["number"] + 1) % 3} for test in self.incoming]
        incoming.append({"number": 3, "id": "new_test", "file": "tests/new.py", "seconds": 1.0})
        selected, reason = self.policy(incoming).select(diff(SOURCE, SOURCE.replace("x + 1", "x + 2")))
        self.assertEqual(selected, {1, 3})
        workers = schedule(selected, {t["number"]: t["seconds"] for t in incoming})
        flattened = [number for worker in workers for number in worker]
        self.assertCountEqual(flattened, selected)
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertLessEqual(len(workers), 8)

    def test_ambiguous_and_file_mismatched_incoming_are_mandatory(self):
        incoming = self.incoming + [{**self.incoming[0], "number": 3}]
        selected, _ = self.policy(incoming).select(diff(SOURCE, SOURCE.replace("x + 1", "x + 2")))
        self.assertEqual(selected, {0, 3})
        incoming = [{**t, "file": "different.py"} if t["number"] == 2 else t for t in self.incoming]
        selected, _ = self.policy(incoming).select(diff(SOURCE, SOURCE.replace("x + 1", "x + 2")))
        self.assertEqual(selected, {0, 2})

    def test_insertions_and_shifted_functions(self):
        new = SOURCE.replace("    value =", "    extra = 3\n    value =").replace("return x - 1", "return x - 2")
        selected, reason = self.policy().select(diff(SOURCE, new))
        self.assertEqual(selected, {0, 1})
        self.assertFalse(reason["fallback"])

    def test_function_comment_edit_is_not_skipped(self):
        new = SOURCE.replace("    value =", "    # comment\n    value =")
        selected, reason = self.policy().select(diff(SOURCE, new))
        self.assertEqual(selected, {0})
        self.assertFalse(reason["fallback"])

    def test_new_deleted_function_and_global_initialization_fallback(self):
        for new in (SOURCE + "\ndef h():\n    return 0\n", SOURCE[:SOURCE.index("\ndef g")],
                    "FLAG = True\n" + SOURCE, "class C:\n    FLAG = True\n" + SOURCE,
                    "# module comment\n" + SOURCE):
            with self.subTest(new=new):
                selected, reason = self.policy().select(diff(SOURCE, new))
                self.assertEqual(selected, {0, 1, 2})
                self.assertTrue(reason["fallback"])

    def test_imports_and_dynamic_or_shared_state_additions_fallback(self):
        for statement in ("import math", "eval('1')", "global STATE"):
            new = SOURCE.replace("    value =", f"    {statement}\n    value =")
            with self.subTest(statement=statement):
                selected, reason = self.policy().select(diff(SOURCE, new))
                self.assertEqual(selected, {0, 1, 2})
                self.assertTrue(reason["fallback"])

    def test_removed_override_and_class_header_or_decorator_change(self):
        old = "class C(Base):\n    FLAG = 1\n    def f(self):\n        return 1\n"
        for new in (old.replace("    def f(self):\n        return 1\n", ""),
                    old.replace("Base", "Other"), old.replace("FLAG = 1", "FLAG = 2"),
                    old.replace("    def f", "    @decorator\n    def f")):
            removed, added = self.check_scope_change(old, new)
            with self.assertRaises(UncertainPatch):
                affected_functions(analyze(old), analyze(new), removed, added)

    def check_scope_change(self, old, new):
        result, removed, added = reconstruct(old, parse_patch(diff(old, new))[0])
        self.assertEqual(result, new)
        return removed, added

    def test_shared_fixture_and_process_execution(self):
        self.index["files"]["pkg/code.py"]["lines"][1][3] = 3
        selected, reason = self.policy().select(diff(SOURCE, SOURCE.replace("x + 1", "x + 2")))
        self.assertEqual(selected, {0, 1})
        self.assertIn("shared_fixture_consumers", reason["reasons"])
        self.index["files"]["pkg/code.py"]["lines"][1][3] = 2
        selected, reason = self.policy().select(diff(SOURCE, SOURCE.replace("x + 1", "x + 2")))
        self.assertEqual(selected, {0, 1, 2})
        self.assertTrue(reason["fallback"])

    def process_evidence(self, rows):
        file, source = "sqlglot/worker.py", "def worker():\n    return 1\n"
        path = self.base / file
        path.parent.mkdir(exist_ok=True)
        path.write_text(source)
        self.index["files"][file] = {
            "sha256": hashlib.sha256(source.encode()).hexdigest(), "lines": [[2, 2, 0, 2]],
        }
        data = {"schema_version": 1, "source_revision": REVISION, "manifest_sha256": None,
                "process": {"complete": True, "tests": [t["id"] for t in self.incoming]}}
        raw = json.dumps(data).encode()
        (self.maps / "resources.json").write_bytes(raw)
        trace = {"schema_version": 1, "source_revision": REVISION, "manifest_sha256": None,
                 "index_sha256": hashlib.sha256(json.dumps(self.index).encode()).hexdigest(),
                 "resources_sha256": hashlib.sha256(raw).hexdigest(), "corpus": {"numbered_tests": 3},
                 "pool_tests": [[0, 1]], "paths": {file: rows}}
        (self.maps / "process_tasks.json").write_text(json.dumps(trace))
        return file, source

    def test_attributed_task_keeps_all_pool_owners_and_resolves_renumbered_ids(self):
        file, source = self.process_evidence([[2, 2, 1, False]])
        incoming = [{**t, "number": (t["number"] + 1) % 3} for t in self.incoming]
        selected, reasons = self.policy(incoming).select(diff(source, source.replace("1", "2"), file))
        self.assertEqual(selected, {1, 2})
        self.assertIn("clean_task_lines_pool_owners", reasons["reasons"])

    def test_incomplete_or_out_of_task_coverage_keeps_the_coarse_process_cohort(self):
        for rows in ([], [[2, 2, 0, True]], [[2, 2, 1, True]]):
            with self.subTest(rows=rows):
                file, source = self.process_evidence(rows)
                selected, reasons = self.policy().select(diff(source, source.replace("1", "2"), file))
                self.assertEqual(selected, {0, 1, 2})
                self.assertIn("clean_process_owner_cohorts", reasons["reasons"])

    def test_unmodeled_body_behavior_does_not_narrow_process_owners(self):
        file, source = self.process_evidence([[2, 2, 1, False]])
        selected, reasons = self.policy().select(diff(source, source.replace("1", "external()"), file))
        self.assertEqual(selected, {0, 1, 2})
        self.assertIn("clean_process_owner_cohorts", reasons["reasons"])

    def test_class_cohort_widening(self):
        self.index["cohorts"][self.incoming[0]["id"].rsplit("::", 1)[0]] = 4
        selected, reason = self.policy().select(diff(SOURCE, SOURCE.replace("x + 1", "x + 2")))
        self.assertEqual(selected, {0, 1})
        self.assertIn("test_class_cohorts", reason["reasons"])

    def test_class_widening_depends_on_shared_state_evidence(self):
        class_name = self.incoming[0]["id"].rsplit("::", 1)[0]
        self.index["cohorts"][class_name] = 4
        patch = diff(SOURCE, SOURCE.replace("x + 1", "x + 2"))
        policy = self.policy()
        policy.class_risks[class_name] = []
        self.assertEqual(policy.select(patch)[0], {0})
        policy.class_risks[class_name] = ["shared_class_lifecycle"]
        self.assertEqual(policy.select(patch)[0], {0, 1})

    def test_call_only_resource_can_skip_unrelated_members_of_stateful_class(self):
        file = "tests/fixtures/simple.sql"
        resource = self.base / file
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_text("SELECT 1\n")
        identity = self.incoming[0]["id"]
        name = identity.rsplit("::", 1)[0]
        self.index["cohorts"][name] = 4
        policy = self.policy()
        policy.class_risks[name] = ["shared_class_lifecycle"]
        entry = {"sha256": hashlib.sha256(resource.read_bytes()).hexdigest(),
                 "readers": [identity], "unresolved": [], "contexts": [f"test|{identity}|call"]}
        policy.resources = {"files": {file: entry}, "directories": {}}
        plain = diff("SELECT 1\n", "SELECT 2\n", file)
        self.assertEqual(policy.select(plain)[0], {0})
        self.assertEqual(policy.select(diff("SELECT 1\n", "CREATE TABLE t AS SELECT 2\n", file))[0], {0, 1})
        entry["contexts"] = [f"test|{identity}|setup"]
        self.assertEqual(policy.select(plain)[0], {0, 1})

    def test_observed_statement_routes_without_other_branches_but_preserves_shared_context(self):
        file = "pkg/code.py"
        old = "def choose(flag):\n    if flag:\n        return 1\n    return 2\n"
        (self.base / file).write_text(old)
        record = self.index["files"][file]
        record["sha256"] = hashlib.sha256(old.encode()).hexdigest()
        record["lines"] = [[2, 2, 4, 0], [3, 3, 1, 3], [4, 4, 3, 0]]
        patch = diff(old, old.replace("return 1", "return 3"))
        policy = self.policy()
        self.assertEqual(policy.select(patch)[0], {0, 1})
        policy.precise_body = False
        self.assertEqual(policy.select(patch)[0], {0, 1, 2})
        policy.precise_body = True
        record["lines"] = [[2, 2, 4, 0], [4, 4, 3, 0]]
        self.assertEqual(self.policy().select(patch)[0], {0, 1, 2})

    def test_fallback_graph_is_only_built_in_diagnostic_mode(self):
        policy = self.policy()
        patch = diff(SOURCE, "FLAG = True\n" + SOURCE)
        self.assertTrue(policy.select(patch)[1]["fallback"])
        self.assertIsNone(policy.reverse_imports)
        policy.diagnostic_imports = True
        self.assertTrue(policy.select(patch)[1]["fallback"])
        self.assertIsNotNone(policy.reverse_imports)

    def test_syntax_binary_unknown_source_and_empty_coverage_fallback(self):
        for patch in (diff(SOURCE, SOURCE.replace("x + 1", "(")), "GIT binary patch\n",
                      diff(SOURCE, SOURCE.replace("x + 1", "x + 2"), "unknown.py")):
            with self.subTest(patch=patch):
                selected, reason = self.policy().select(patch)
                self.assertEqual(selected, {0, 1, 2})
                self.assertTrue(reason["fallback"])
        self.index["files"]["pkg/code.py"]["lines"] = []
        selected, reason = self.policy().select(diff(SOURCE, SOURCE.replace("x + 1", "x + 2")))
        self.assertEqual(selected, {0, 1, 2})
        self.assertTrue(reason["fallback"])

    def test_patches_independently_use_the_immutable_base(self):
        policy = self.policy()
        a = diff(SOURCE, SOURCE.replace("x + 1", "x + 2"))
        b = diff(SOURCE, SOURCE.replace("x - 1", "x - 2"))
        self.assertEqual(policy.select(a)[0], {0})
        self.assertEqual(policy.select(b)[0], {1})
        self.assertEqual(policy.select(a)[0], {0})
        self.assertEqual((self.base / "pkg/code.py").read_text(), SOURCE)

    def test_resource_modification_ignores_unresolved_directory_membership(self):
        file = "tests/fixtures/simple.sql"
        resource = self.base / file
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_text("SELECT 1\n")
        policy = self.policy()
        policy.resources = {
            "files": {file: {"sha256": hashlib.sha256(resource.read_bytes()).hexdigest(),
                             "readers": [self.incoming[0]["id"]], "unresolved": []}},
            "directories": {"tests/fixtures": {"readers": [], "unresolved": ["shared:collection"]}},
        }
        patch = diff("SELECT 1\n", "SELECT 2\n", file)
        self.assertEqual(policy.select(patch)[0], {0})
        multi = patch + diff(SOURCE, SOURCE.replace("x - 1", "x - 2"))
        self.assertEqual(policy.select(multi)[0], {0, 1})
        deletion = f"--- a/{file}\n+++ /dev/null\n@@ -1 +0,0 @@\n-SELECT 1\n"
        self.assertTrue(policy.select(deletion)[1]["fallback"])
        addition = "--- /dev/null\n+++ b/tests/fixtures/new.sql\n@@ -0,0 +1 @@\n+SELECT 1\n"
        self.assertTrue(policy.select(addition)[1]["fallback"])
        policy.resources["files"][file]["unresolved"] = ["shared:child"]
        self.assertTrue(policy.select(patch)[1]["fallback"])

    def test_known_child_owner_cohort_is_unioned(self):
        self.index["files"]["pkg/code.py"]["lines"][1][3] = 2
        policy = self.policy()
        policy.resources = {"process": {"tests": [self.incoming[1]["id"]], "complete": True}}
        patch = diff(SOURCE, SOURCE.replace("x + 1", "x + 2"))
        self.assertEqual(policy.select(patch)[0], {0, 1})
        policy.resources["process"]["complete"] = False
        self.assertTrue(policy.select(patch)[1]["fallback"])

    def test_local_test_declarations_include_known_importers(self):
        file = self.incoming[0]["file"]
        old = "import unittest\n\nclass A(unittest.TestCase):\n    VALUE = 1\n    def test_value(self):\n        assert self.VALUE == 1\n"
        importer = self.incoming[1]["file"]
        for path, content in ((file, old), (importer, "from tests.test_a import A\n")):
            (self.base / path).write_text(content)
            self.index["files"][path]["sha256"] = hashlib.sha256(content.encode()).hexdigest()
        policy = self.policy()
        self.assertEqual(policy.select(diff(old, old.replace("VALUE = 1", "VALUE = 2"), file))[0], {0, 1})
        changed = old.replace("VALUE = 1", "VALUE = calculate()")
        self.assertTrue(policy.select(diff(old, changed, file))[1]["fallback"])


if __name__ == "__main__":
    unittest.main()
