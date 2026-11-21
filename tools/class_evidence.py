"""Generate test-class coupling evidence from pinned source and clean tracing."""

import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import subprocess

PIN = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"


def immutable(node):
    return isinstance(node, ast.Constant) or (
        isinstance(node, ast.Tuple) and all(immutable(item) for item in node.elts)
    )


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted(node.value)}.{node.attr}"
    return ""


# Decorators that cannot couple one test method to another: the skip family
# selects whether its own method runs, and the descriptor builtins only change
# how that one method is bound.
INERT_DECORATORS = {"skip", "skipIf", "skipUnless", "expectedFailure",
                    "classmethod", "staticmethod", "property"}
# `patch(target)` resolves and restores one module attribute around its own
# call, so it couples its method to the patched module, not to its siblings.
CALL_SCOPED_PATCHES = {"patch", "mock.patch", "unittest.mock.patch"}


def decorator_callee(node):
    """Name the decorator being applied, looking through a decorator call.

    A parameterized decorator is an `ast.Call`, so reading the node itself
    reports no name at all and would misread an inert `@skipIf(...)`.
    """
    return dotted(node.func) if isinstance(node, ast.Call) else dotted(node)


def classify_decorator(node):
    """Classify one test-method decorator as inert, call-scoped or unknown."""
    callee = decorator_callee(node)
    if not callee:
        return "unknown"
    if callee.rsplit(".", 1)[-1] in INERT_DECORATORS:
        return "inert"
    if (isinstance(node, ast.Call) and callee in CALL_SCOPED_PATCHES
            and not node.keywords and len(node.args) == 1
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)):
        return "call_scoped"
    return "unknown"


def empty_decorated():
    return {"call_scoped": set(), "unknown": set()}


def class_risks(node):
    reasons = set()
    decorated = empty_decorated()
    if node.decorator_list or node.keywords:
        reasons.add("dynamic_class")
    for item in node.body:
        if isinstance(item, (ast.Assign, ast.AnnAssign)) and not immutable(item.value):
            reasons.add("class_state")
        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if item.name in {"setUpClass", "tearDownClass", "setup_class", "teardown_class"}:
            reasons.add("shared_class_lifecycle")
        kinds = {classify_decorator(d) for d in item.decorator_list}
        if kinds - {"inert"}:
            reasons.add("method_decorator")
            for kind in ("call_scoped", "unknown"):
                if kind in kinds:
                    decorated[kind].add(item.name)
        for descendant in ast.walk(item):
            if isinstance(descendant, (ast.Global, ast.Nonlocal)):
                reasons.add("nonlocal_binding")
            if isinstance(descendant, ast.Attribute):
                name = dotted(descendant)
                if (isinstance(descendant.ctx, (ast.Store, ast.Del)) and
                        name.startswith(("cls.", "self.__class__.", node.name + "."))):
                    reasons.add("class_write")
            if isinstance(descendant, ast.Call):
                callee = dotted(descendant.func)
                if (callee in {"setattr", "delattr", "exec", "eval", "globals", "locals", "vars"}
                        or callee.endswith(("cache_clear", "cache_update"))):
                    reasons.add("dynamic_mutation")
    return reasons, decorated


def collect(source, index, trace):
    shared = defaultdict(set)
    for fixture, users in trace["fixture_users"].items():
        definition = trace["fixtures"][fixture]
        if definition["scope"] not in {"module", "class", "session", "package"}:
            continue
        name = definition["name"]
        # Pytest's unittest wrapper exists even for inherited no-op hooks.
        # Real overrides are checked in the class AST, including ancestors.
        if name.startswith("_unittest_setUpClass_fixture_"):
            continue
        for identity in users:
            shared[identity.rsplit("::", 1)[0]].add("shared_pytest_fixture")

    modules = {}
    inspection = []
    files = sorted({row["file"] for row in index["tests"]})
    for name in files:
        tree = ast.parse((source / name).read_bytes())
        module = name.removesuffix(".py").replace("/", ".")
        imports = {}
        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.update({alias.asname or alias.name.split(".")[0]: alias.name for alias in node.names})
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.update({alias.asname or alias.name: f"{node.module}.{alias.name}" for alias in node.names})

        classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
        if any(isinstance(node, ast.Call) and dotted(node.func).rsplit(".", 1)[-1]
               in {"getsource", "getsourcelines", "getsourcefile", "read_text", "read_bytes"}
               for node in ast.walk(tree)):
            inspection.append(name)
        modules[module] = (classes, imports, tree)

    def risks(module, cls, visited):
        key = module + "." + cls
        if key == "unittest.TestCase":
            return set(), empty_decorated()
        if key in visited or module not in modules or cls not in modules[module][0]:
            return {"unresolved_class_base"}, empty_decorated()
        classes, imports, tree = modules[module]
        node = classes[cls]
        reasons, decorated = class_risks(node)
        if any(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and
               item.name in {"setUpModule", "tearDownModule", "setup_module", "teardown_module"}
               for item in tree.body):
            reasons.add("shared_module_lifecycle")
        for base in node.bases:
            expression = dotted(base)
            head, dot, tail = expression.partition(".")
            target = imports.get(head, module + "." + head) + dot + tail
            parent, _, name = target.rpartition(".")
            # An inherited method keeps its decorator, so the detail merges
            # along the same resolved chain the risk reasons use.
            base_reasons, base_decorated = risks(parent, name, {*visited, key})
            reasons.update(base_reasons)
            for kind, names in base_decorated.items():
                decorated[kind].update(names)
        return reasons, decorated

    classes = {}
    methods = {}
    for row in index["tests"]:
        parts = row["id"].split("::")
        if len(parts) != 3:
            continue
        cohort = "::".join(parts[:-1])
        if cohort not in classes:
            module = row["file"].removesuffix(".py").replace("/", ".")
            reasons, decorated = risks(module, parts[1], set())
            classes[cohort] = sorted(shared[cohort] | reasons)
            if decorated["call_scoped"] or decorated["unknown"]:
                methods[cohort] = {kind: sorted(names) for kind, names in sorted(decorated.items())}
    return classes, methods, inspection


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("trace", type=Path)
    parser.add_argument("index", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    assert subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip() == PIN
    assert not subprocess.check_output(["git", "-C", str(args.source), "status", "--porcelain", "--untracked-files=all"])
    index_bytes = args.index.read_bytes()
    index = json.loads(index_bytes)
    trace_bytes = args.trace.read_bytes()
    trace = json.loads(trace_bytes)
    assert index["source_revision"] == PIN and trace["exit_code"] == 0
    assert not trace["collection_errors"]
    classes, methods, inspection = collect(args.source, index, trace)
    result = {"source_revision": PIN, "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
              "raw_trace_sha256": hashlib.sha256(trace_bytes).hexdigest(), "class_risks": classes,
              "class_methods": methods, "source_inspection_files": inspection}
    args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
