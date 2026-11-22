"""Guards for the deferred factory declaration family.

Synthetic clean-source examples only; no sample failure labels.
"""
import ast
import unittest

from declarations import bindings, changed_bindings
from tools.declaration_evidence import closure_factory, key_only_read

FACTORY = (
    "def _show(*args, **kwargs):\n"
    "    def _parse(self):\n"
    "        return self._show(*args, **kwargs)\n"
    "    return _parse\n"
)
TABLE = (
    "class Parser(Base):\n"
    '    SHOW_PARSERS = {\n'
    '        "USERS": _show("USERS", target=True),\n'
    '        "ROLES": _show("ROLES"),\n'
    "    }\n"
    '    SHOW_TRIE = new_trie(key.split(" ") for key in SHOW_PARSERS)\n'
)


def changed(old, new):
    return changed_bindings(old, new, ast.parse(old), ast.parse(new))


class BindingTests(unittest.TestCase):
    def test_a_factory_call_in_a_class_table_is_a_candidate(self):
        found = {(key, kind) for key, kind, _ in bindings(ast.parse(TABLE))}
        self.assertIn(("Parser.SHOW_PARSERS['USERS']", "deferred_factory"), found)
        self.assertIn(("Parser.SHOW_PARSERS['ROLES']", "deferred_factory"), found)

    def test_a_changed_constant_argument_is_detected(self):
        new = TABLE.replace('_show("USERS", target=True)', '_show("USERS", target=False)')
        self.assertEqual(changed(TABLE, new),
                         [("Parser.SHOW_PARSERS['USERS']", "deferred_factory")])

    def test_a_changed_positional_argument_is_detected(self):
        new = TABLE.replace('_show("USERS", target=True)', '_show("USER", target=True)')
        self.assertEqual(changed(TABLE, new),
                         [("Parser.SHOW_PARSERS['USERS']", "deferred_factory")])

    def test_structural_edits_are_rejected(self):
        for new in (
            TABLE.replace('_show("USERS", target=True)', '_other("USERS", target=True)'),
            TABLE.replace('_show("USERS", target=True)', '_show("USERS")'),
            TABLE.replace('_show("USERS", target=True)', '_show("USERS", target=True, extra=1)'),
            TABLE.replace('"USERS":', '"USER":'),
            TABLE.replace('        "ROLES": _show("ROLES"),\n', ''),
            TABLE.replace('_show("USERS", target=True)', '_show("USERS", target=1)'),
            TABLE.replace('    }', '        "NEW": _show("NEW"),\n    }'),
        ):
            with self.subTest(new=new):
                self.assertEqual(changed(TABLE, new), [])

    def test_an_unrelated_byte_outside_the_value_blocks_the_route(self):
        new = TABLE.replace('_show("USERS", target=True)', '_show("USERS", target=False)')
        new = new.replace("class Parser(Base):", "class Parser(Other):")
        self.assertEqual(changed(TABLE, new), [])


class FactoryPurityTests(unittest.TestCase):
    def factory(self, text):
        return ast.parse(text).body[0]

    def test_a_closure_factory_is_accepted(self):
        inner = closure_factory(self.factory(FACTORY))
        self.assertIsNotNone(inner)
        self.assertEqual(inner.name, "_parse")

    def test_effectful_or_opaque_factories_are_rejected(self):
        for text in (
            "def _show(*a):\n    REGISTRY.append(a)\n    def _p(self):\n        return a\n    return _p\n",
            "def _show(*a):\n    global SEEN\n    def _p(self):\n        return a\n    return _p\n",
            "def _show(*a):\n    Base.PATCHED = a\n    def _p(self):\n        return a\n    return _p\n",
            "def _show(*a):\n    return lambda self: a\n",
            "def _show(*a):\n    import os\n    def _p(self):\n        return a\n    return _p\n",
            "def _show(*a):\n    def _p(self):\n        return a\n    return other(_p)\n",
            "@wrapped\ndef _show(*a):\n    def _p(self):\n        return a\n    return _p\n",
            "def _show(*a):\n    setattr(Base, 'x', a)\n    def _p(self):\n        return a\n    return _p\n",
        ):
            with self.subTest(text=text):
                self.assertIsNone(closure_factory(self.factory(text)))


class KeyOnlyReadTests(unittest.TestCase):
    def check(self, body, owner="Parser", attribute="SHOW_PARSERS"):
        text = f"class Parser(Base):\n    SHOW_PARSERS = {{}}\n    {body}\n"
        tree = ast.parse(text)
        line = len(text.rstrip("\n").splitlines())
        return key_only_read(tree, line, attribute, owner, {"Parser", "Other"})

    def test_key_only_forms_are_accepted(self):
        for body in ('TRIE = new_trie(key for key in SHOW_PARSERS)',
                     'PRESENT = "USERS" in SHOW_PARSERS',
                     'ABSENT = "USERS" not in SHOW_PARSERS',
                     'NAMES = sorted(SHOW_PARSERS.keys())',
                     'COUNT = len(SHOW_PARSERS)'):
            with self.subTest(body=body):
                self.assertTrue(self.check(body))

    def test_value_observing_forms_are_rejected(self):
        for body in ('MERGED = {**SHOW_PARSERS}',
                     'VALUES = list(SHOW_PARSERS.values())',
                     'PAIRS = {v: k for k, v in SHOW_PARSERS.items()}',
                     'ONE = SHOW_PARSERS["USERS"]',
                     'COPY = dict(SHOW_PARSERS)',
                     'SELF = cls.SHOW_PARSERS.copy()'):
            with self.subTest(body=body):
                self.assertFalse(self.check(body))

    def test_another_class_binding_of_the_same_name_is_skipped(self):
        self.assertTrue(self.check('MERGED = {**Other.SHOW_PARSERS}'))

    def test_an_unresolvable_receiver_is_treated_as_observing(self):
        self.assertFalse(self.check('MERGED = {**mystery.SHOW_PARSERS}'))
