"""Decorator classification and risk-scoped class widening.

Synthetic coverage and clean-source examples only; no sample failure labels.
"""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from selection import REVISION, SelectionPolicy
from tools.class_evidence import class_risks, classify_decorator

SOURCE = "def f(x):\n    value = x + 1\n    return value\n"
CLASS = "tests/test_a.py::A"


def decorator(text):
    """Parse one decorator expression from its source text."""
    return ast.parse(f"{text}\ndef method(self):\n    pass\n").body[0].decorator_list[0]


class DecoratorClassificationTests(unittest.TestCase):
    def test_skip_family_is_inert_in_bare_and_called_form(self):
        for text in ("@skip", "@unittest.skip", "@unittest.skipIf(True, 'reason')",
                     "@unittest.skipUnless(CONDITION, 'reason')", "@expectedFailure",
                     "@unittest.expectedFailure", "@skipIf(sys.platform == 'win32', 'reason')"):
            with self.subTest(text=text):
                self.assertEqual(classify_decorator(decorator(text)), "inert")

    def test_descriptor_builtins_are_inert(self):
        for text in ("@classmethod", "@staticmethod", "@property"):
            with self.subTest(text=text):
                self.assertEqual(classify_decorator(decorator(text)), "inert")

    def test_patch_with_one_constant_target_is_call_scoped(self):
        for text in ("@patch('sqlglot.parser.logger')", "@mock.patch('sqlglot.generator.logger')",
                     "@unittest.mock.patch('sqlglot.parser.logger')"):
            with self.subTest(text=text):
                self.assertEqual(classify_decorator(decorator(text)), "call_scoped")

    def test_anything_else_is_unknown(self):
        for text in ("@patch", "@mock.patch", "@patch('target', autospec=True)",
                     "@patch('target', NEW)", "@patch(TARGET)", "@cached", "@registry.register('x')",
                     "@patch.object(module, 'name')", "@subject[0]"):
            with self.subTest(text=text):
                self.assertEqual(classify_decorator(decorator(text)), "unknown")

    def test_called_skip_no_longer_raises_the_decorator_risk(self):
        body = ("class A(unittest.TestCase):\n"
                "    @unittest.skipIf(True, 'reason')\n"
                "    def test_skipped(self):\n        pass\n")
        reasons, decorated = class_risks(ast.parse(body).body[0])
        self.assertEqual(reasons, set())
        self.assertEqual(decorated, {"call_scoped": set(), "unknown": set()})

    def test_patch_raises_the_decorator_risk_and_records_the_method(self):
        body = ("class A(unittest.TestCase):\n"
                "    @patch('sqlglot.parser.logger')\n"
                "    def test_logged(self, logger):\n        pass\n"
                "    def test_plain(self):\n        pass\n")
        reasons, decorated = class_risks(ast.parse(body).body[0])
        self.assertEqual(reasons, {"method_decorator"})
        self.assertEqual(decorated, {"call_scoped": {"test_logged"}, "unknown": set()})

    def test_unknown_decorator_is_recorded_separately(self):
        body = ("class A(unittest.TestCase):\n"
                "    @cached\n"
                "    def test_cached(self):\n        pass\n")
        reasons, decorated = class_risks(ast.parse(body).body[0])
        self.assertEqual(reasons, {"method_decorator"})
        self.assertEqual(decorated, {"call_scoped": set(), "unknown": {"test_cached"}})


class ClassWideningTests(unittest.TestCase):
    """One class with a covered seed, a patch-decorated sibling and a plain one."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.base = root / "base"
        self.maps = root / "maps"
        self.base.mkdir()
        self.maps.mkdir()
        self.incoming = [
            {"number": 0, "id": f"{CLASS}::test_seed", "file": "tests/test_a.py", "seconds": 1.0},
            {"number": 1, "id": f"{CLASS}::test_patched", "file": "tests/test_a.py", "seconds": 1.0},
            {"number": 2, "id": f"{CLASS}::test_plain", "file": "tests/test_a.py", "seconds": 1.0},
        ]
        contents = {"pkg/code.py": SOURCE, "tests/test_a.py": "from pkg.code import f\n"}
        self.index = {
            "schema_version": 1, "source_revision": REVISION,
            "tests": [{**t, "incomplete": False} for t in self.incoming],
            # 0 empty, 1 the seed alone, 2 the whole class.
            "test_sets": [[], [[0, 0]], [[0, 2]]],
            "shared_sets": [[]],
            "shared_contexts": [],
            "files": {name: {"sha256": hashlib.sha256(text.encode()).hexdigest(), "lines": []}
                      for name, text in contents.items()},
            "cohorts": {"tests/test_a.py": 2, CLASS: 2},
        }
        self.index["files"]["pkg/code.py"]["lines"] = [[2, 3, 1, 0]]
        for name, text in contents.items():
            path = self.base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        (self.base / "REVISION").write_text(REVISION + "\n")

    def select(self, risks, methods=None, omit_methods=False):
        raw = json.dumps(self.index).encode()
        (self.maps / "index.json").write_bytes(raw)
        (self.maps / "audit.json").write_text(
            json.dumps({"raw_trace_complete": True, "collection_errors": []}))
        (self.maps / "provenance.json").write_text(
            json.dumps({"source_revision": REVISION, "index_sha256": hashlib.sha256(raw).hexdigest()}))
        evidence = {"source_revision": REVISION, "index_sha256": hashlib.sha256(raw).hexdigest(),
                    "class_risks": {CLASS: risks}, "source_inspection_files": []}
        if not omit_methods:
            evidence["class_methods"] = methods or {}
        (self.maps / "class_evidence.json").write_text(json.dumps(evidence))
        policy = SelectionPolicy(self.incoming, self.maps, self.base)
        self.assertIsNone(policy.startup_error)
        patch = ("--- a/pkg/code.py\n+++ b/pkg/code.py\n@@ -1,3 +1,3 @@\n def f(x):\n"
                 "-    value = x + 1\n+    value = x + 2\n     return value\n")
        return policy.select(patch)

    def test_decorator_only_risk_widens_to_the_seed_and_patched_sibling(self):
        selected, reason = self.select(
            ["method_decorator"], {CLASS: {"call_scoped": ["test_patched"], "unknown": []}})
        self.assertEqual(selected, {0, 1})
        self.assertFalse(reason["fallback"])
        self.assertIn("decorator_scoped_class_cohort", reason["reasons"])

    def test_state_risks_keep_the_complete_class_cohort(self):
        for risk in ("class_write", "class_state", "dynamic_class", "dynamic_mutation",
                     "shared_class_lifecycle", "nonlocal_binding", "shared_pytest_fixture",
                     "unresolved_class_base", "shared_module_lifecycle"):
            with self.subTest(risk=risk):
                selected, reason = self.select(
                    ["method_decorator", risk], {CLASS: {"call_scoped": ["test_patched"], "unknown": []}})
                self.assertEqual(selected, {0, 1, 2})
                self.assertIn("test_class_cohorts", reason["reasons"])
                self.assertNotIn("decorator_scoped_class_cohort", reason["reasons"])

    def test_unknown_decorator_forfeits_the_scoped_cohort(self):
        selected, _ = self.select(
            ["method_decorator"], {CLASS: {"call_scoped": ["test_patched"], "unknown": ["test_plain"]}})
        self.assertEqual(selected, {0, 1, 2})

    def test_missing_per_method_detail_keeps_the_complete_class_cohort(self):
        selected, _ = self.select(["method_decorator"], {})
        self.assertEqual(selected, {0, 1, 2})
        selected, _ = self.select(["method_decorator"], omit_methods=True)
        self.assertEqual(selected, {0, 1, 2})

    def test_unknown_class_without_evidence_keeps_the_complete_class_cohort(self):
        selected, _ = self.select([], {})
        self.assertEqual(selected, {0})
        self.index["cohorts"]["unrelated"] = 1
        selected, _ = self.select(["unknown_class"], {})
        self.assertEqual(selected, {0, 1, 2})

    def test_no_recorded_coupling_selects_only_the_covered_seed(self):
        selected, reason = self.select([], {})
        self.assertEqual(selected, {0})
        self.assertNotIn("test_class_cohorts", reason["reasons"])
