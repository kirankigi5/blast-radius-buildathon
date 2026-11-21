"""Synthetic coverage and clean-source examples; no sample failure labels."""

import ast
import difflib
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from patch_analysis import UncertainPatch, affected_functions, analyze, parse_patch, reconstruct
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

    def test_zero_context_insertion_and_scope_boundary(self):
        new = SOURCE.replace("    return value\n", "    return value\n    unreachable = True\n")
        removed, added = self.check_patch(SOURCE, new)
        affected = affected_functions(analyze(SOURCE), analyze(new), removed, added)
        self.assertEqual(affected, {("f",)})
        patch = "--- a/pkg/code.py\n+++ b/pkg/code.py\n@@ -0,0 +1 @@\n+# preface\n"
        self.assertEqual(reconstruct(SOURCE, parse_patch(patch)[0])[0], "# preface\n" + SOURCE)

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

    def test_class_cohort_widening(self):
        self.index["cohorts"][self.incoming[0]["id"].rsplit("::", 1)[0]] = 4
        selected, reason = self.policy().select(diff(SOURCE, SOURCE.replace("x + 1", "x + 2")))
        self.assertEqual(selected, {0, 1})
        self.assertIn("test_class_cohorts", reason["reasons"])

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
