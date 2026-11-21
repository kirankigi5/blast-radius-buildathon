"""Focused checks for encoding and pytest fixture-context ownership."""

from pathlib import Path
import tempfile
import unittest

import coverage
import pytest

from export import Sets, ranges, source_ranges
from pytest_contexts import Contexts
import ast


class EncodingTests(unittest.TestCase):
    def test_sorted_range_deduplication(self):
        self.assertEqual(ranges([7, 2, 1, 2, 6, 5, 10]), [[1, 2], [5, 7], [10, 10]])
        sets = Sets()
        self.assertEqual(sets.add([]), 0)
        self.assertEqual(sets.add([2, 1, 2]), sets.add([1, 2]))

    def test_ast_ranges_include_decorators_and_nested_definitions(self):
        definitions = source_ranges(ast.parse(
            "@decorator\nclass C:\n    def method(self):\n        def nested():\n            return 1\n        return nested()\n"
        ))
        self.assertEqual([(r["name"], r["start"], r["end"]) for r in definitions],
                         [("C", 1, 6), ("C.method", 3, 6), ("C.method.nested", 4, 5)])

    def test_shared_setup_teardown_and_dynamic_fixture_consumers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "test_context_probe.py"
            source.write_text(
                "import pytest\n"
                "def helper():\n    return 7\n"
                "@pytest.fixture(scope='session')\n"
                "def shared():\n    value = helper()\n    yield value\n    helper()\n"
                "@pytest.fixture\n"
                "def dynamic(request):\n    return request.getfixturevalue('shared')\n"
                "def test_a(dynamic):\n    assert dynamic == helper()\n"
                "def test_b(shared):\n    assert shared == helper()\n"
            )
            wanted = ["test_context_probe.py::test_a", "test_context_probe.py::test_b"]
            cov = coverage.Coverage(source=[str(root)], config_file=False, data_file=None)
            cov.start()
            plugin = Contexts(cov, wanted)
            result = pytest.main(["-q", "-p", "no:cacheprovider", f"--rootdir={root}", str(source)], plugins=[plugin])
            cov.stop()
            self.assertEqual(result, 0)
            observed = cov.get_data().contexts_by_lineno(str(source))
            key = next(key for key, info in plugin.fixture_info.items() if info["name"] == "shared")
            self.assertEqual(plugin.fixture_users[key], set(wanted))
            self.assertIn(f"fixture|{key}|setup", observed[6])
            self.assertIn(f"fixture|{key}|teardown", observed[8])
            self.assertEqual(observed[13], [f"test|{wanted[0]}|call"])
            self.assertEqual(observed[15], [f"test|{wanted[1]}|call"])
            self.assertIn("shared:collection", observed[1])


if __name__ == "__main__":
    unittest.main()
