"""Guard the production declaration classifier and clean dependency exporter."""

import ast
import hashlib
from pathlib import Path
import tempfile
import unittest

from declarations import changed_bindings
from tools.declaration_evidence import SourceGraph


class DeclarationClassifierTests(unittest.TestCase):
    def classify(self, old, new):
        return changed_bindings(old, new, ast.parse(old), ast.parse(new))

    def test_same_type_scalar_with_exact_surrounding_source(self):
        source = "COUNT = -3\nclass Dialect:\n    STRICT = False\n"
        changed = source.replace("-3", "-2").replace("False", "True")
        self.assertEqual(self.classify(source, changed),
                         [("COUNT", "module_scalar"), ("Dialect.STRICT", "class_scalar")])
        self.assertEqual(self.classify(source, changed.replace("COUNT", "SIZE")), [])
        self.assertEqual(self.classify(source, changed.replace("-2", "True")), [])
        self.assertEqual(self.classify(source, changed + "# comment\n"), [])
        self.assertEqual(self.classify(source, source + "# comment\n"), [])

    def test_new_or_removed_override_and_mutable_mapping_stay_unsupported(self):
        source = "class Parent:\n    RATE = 1\nclass Child(Parent):\n    RATE = 2\n"
        self.assertEqual(self.classify(source, source.replace("    RATE = 2\n", "    pass\n")), [])
        self.assertEqual(self.classify(source, source + "    NEW_RATE = 3\n"), [])
        old = "class Owner:\n    TABLE = {'x': {'first': True}}\n"
        self.assertEqual(self.classify(old, old.replace("True", "False")), [])

    def test_literal_in_deferred_body_preserves_dispatch_binding(self):
        old = "class Parser:\n    TABLE = {'WORD': lambda p: callback(\n        p, 1\n    )}\n"
        self.assertEqual(self.classify(old, old.replace("p, 1", "p, 2")),
                         [("Parser.TABLE['WORD']", "deferred_lambda")])
        self.assertEqual(self.classify(old, old.replace("callback", "other")), [])
        self.assertEqual(self.classify(old, old.replace("'WORD'", "'OTHER'")), [])
        self.assertEqual(self.classify(old, old.replace("lambda p:", "lambda p=3:")), [])
        inline = "class Parser:\n    TABLE = {'WORD': lambda p: callback(p, 1)}\n"
        self.assertEqual(self.classify(inline, inline.replace("p, 1", "p, 2")), [])


class CleanDependencyGraphTests(unittest.TestCase):
    def graph(self, files):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        source = Path(temporary.name)
        index = {"files": {}}
        for name, text in files.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            index["files"][name] = {"sha256": hashlib.sha256(text.encode()).hexdigest()}
        return SourceGraph(source, index)

    def test_aliases_reexports_and_derived_bindings_propagate_to_fixed_point(self):
        graph = self.graph({
            "sqlglot/settings.py": "CAP = 3\n",
            "sqlglot/facade/__init__.py": "from ..settings import CAP as LIMIT\n",
            "sqlglot/use.py": "from .facade import LIMIT\nSECOND = LIMIT\ndef use():\n    return SECOND\n",
        })
        sites, initialization, aliases = graph.dependent_sites("sqlglot/settings.py", "CAP", "module_scalar")
        self.assertIn(("sqlglot/use.py", 4, ("use", 3, 4)), sites)
        self.assertFalse(initialization)
        self.assertIn("sqlglot/use.py:SECOND", aliases)
        self.assertIn("sqlglot.facade", graph.visibility["sqlglot/use.py"])
        self.assertIn("sqlglot", graph.visibility["sqlglot/use.py"])

    def test_initializer_read_and_inherited_ambiguous_receiver_are_retained(self):
        graph = self.graph({
            "sqlglot/base.py": (
                "class Parent:\n    RATE = 1\n"
                "    def __init_subclass__(cls):\n        cls.DERIVED = cls.RATE * 2\n"
            ),
            "sqlglot/child.py": (
                "from .base import Parent as P\nclass Child(P):\n    pass\n"
                "def read(obj):\n    return obj.RATE\n"
            ),
        })
        hierarchy, unknown = graph.class_family("sqlglot/base.py", "Parent.RATE")
        self.assertFalse(unknown)
        self.assertEqual(hierarchy, {"sqlglot.base.Parent", "sqlglot.child.Child"})
        sites, initialization, _ = graph.dependent_sites("sqlglot/base.py", "Parent.RATE", "class_scalar")
        self.assertIn("sqlglot/base.py:4", initialization)
        self.assertIn(("sqlglot/child.py", 5, ("read", 4, 5)), sites)

    def test_star_import_retains_possible_readers(self):
        graph = self.graph({
            "sqlglot/cfg.py": "LIMIT = 3\n",
            "sqlglot/consumer.py": "from .cfg import *\ndef use():\n    return LIMIT\n",
        })
        sites, initialization, _ = graph.dependent_sites("sqlglot/cfg.py", "LIMIT", "module_scalar")
        self.assertIn(("sqlglot/consumer.py", 3, ("use", 2, 3)), sites)
        self.assertFalse(initialization)

    def test_reflection_and_unresolved_receiver_retain_possible_readers(self):
        graph = self.graph({
            "sqlglot/cfg.py": "LIMIT = 3\n",
            "sqlglot/consumer.py": (
                "def use(module, factory):\n"
                "    first = getattr(module, 'LIMIT')\n"
                "    return first + factory().LIMIT\n"
            ),
        })
        sites, initialization, _ = graph.dependent_sites("sqlglot/cfg.py", "LIMIT", "module_scalar")
        self.assertEqual(sites, {
            ("sqlglot/consumer.py", 2, ("use", 1, 3)),
            ("sqlglot/consumer.py", 3, ("use", 1, 3)),
        })
        self.assertFalse(initialization)


if __name__ == "__main__":
    unittest.main()
