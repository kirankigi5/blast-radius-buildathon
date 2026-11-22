"""Create a clean-source reference index for existing declaration edits."""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from declarations import bindings
from selection import REVISION, decode_set, members


def module_name(file):
    return file.removesuffix(".py").replace("/", ".").removesuffix(".__init__")


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted(node.value)
        return f"{parent}.{node.attr}" if parent else ""
    return ""


def spans(value):
    result = []
    for i in members(value):
        if result and result[-1][1] == i - 1:
            result[-1][1] = i
        else:
            result.append([i, i])
    return result


class SourceGraph:
    def __init__(self, source, index):
        self.trees = {}
        self.module_paths = {}
        self.imports = defaultdict(lambda: defaultdict(set))
        self.visibility = defaultdict(set)
        self.classes = defaultdict(dict)
        self.declarations = {}
        self.references = defaultdict(list)
        self.dynamic = defaultdict(list)
        self.opaque_attributes = []
        self.registry_functions = set()
        self.elements = defaultdict(set)
        for file in sorted(index["files"]):
            if not file.startswith(("sqlglot/", "tests/")):
                continue
            raw = (source / file).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == index["files"][file]["sha256"]
            tree = ast.parse(raw)
            mod = module_name(file)
            self.trees[file] = tree
            self.module_paths[mod] = file
            self.declarations[file] = list(bindings(tree))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    self.add_import(file, mod, node)
            self.visit(file, tree, (), None, None)
        self.class_locations = {f"{module_name(file)}.{name}": (file, node)
                                for file, classes in self.classes.items() for name, node in classes.items()}
        self.parents = {}
        self.children = defaultdict(set)
        for qualified, (file, node) in self.class_locations.items():
            bases = set()
            for base in node.bases:
                name = dotted(base)
                first, dot, tail = name.partition(".")
                options = self.imports[file].get(first, ())
                targets = {f"{module_name(file)}.{name}"}
                for option in options:
                    targets.update(self.resolve_import(option + dot + tail))
                matching = targets & self.class_locations.keys()
                if not matching and name not in {"object", "type"}:
                    bases.add("?")
                bases.update(matching)
            self.parents[qualified] = bases
            for base in bases - {"?"}:
                self.children[base].add(qualified)

    def add_visibility(self, file, module):
        parts = module.split(".")
        self.visibility[file].update(".".join(parts[:i]) for i in range(1, len(parts) + 1))

    def add_import(self, file, mod, node):
        for alias in node.names:
            if isinstance(node, ast.Import):
                local = alias.asname or alias.name.split(".")[0]
                path = alias.name if alias.asname else local
                self.add_visibility(file, alias.name)
            else:
                prefix = node.module or ""
                if node.level:
                    package = mod.split(".")
                    if not file.endswith("/__init__.py"):
                        package.pop()
                    prefix = ".".join(package[:len(package) - node.level + 1] + ([prefix] if prefix else []))
                local, path = alias.asname or alias.name, f"{prefix}.{alias.name}"
                self.add_visibility(file, prefix)
                self.add_visibility(file, path)
            self.imports[file][local].add(path)

    def visit(self, file, node, owner, function, assignment):
        if isinstance(node, ast.ClassDef):
            self.classes[file][".".join((*owner, node.name))] = node
            for expression in (*node.bases, *node.keywords, *node.decorator_list):
                self.visit(file, expression, owner, function, assignment)
            for item in node.body:
                self.visit(file, item, (*owner, node.name), function, None)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dep in (*node.decorator_list, node.args, node.returns):
                if dep is not None:
                    self.visit(file, dep, owner, function, None)
            name = ".".join((*owner, node.name))
            self.elements[file].add(name)
            for item in node.body:
                self.visit(file, item, owner, (name, node.lineno, node.end_lineno), None)
            return
        if isinstance(node, ast.Lambda):
            self.visit(file, node.args, owner, function, assignment)
            self.visit(file, node.body, owner, (f"<lambda@{node.lineno}>", node.lineno, node.end_lineno), None)
            return
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and function is None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            target = targets[0] if len(targets) == 1 else None
            if isinstance(target, ast.Name) and node.value is not None:
                self.elements[file].add(".".join((*owner, target.id)))
            if isinstance(target, ast.Name) and isinstance(node.value, (ast.Name, ast.Attribute)):
                # Bare aliases introduce no computation while passing a scalar on.
                self.visit(file, node.value, owner, function, ".".join((*owner, target.id)))
                return
        if isinstance(node, (ast.Attribute, ast.Name)) and isinstance(node.ctx, ast.Load):
            name = node.attr if isinstance(node, ast.Attribute) else node.id
            self.references[name].append((file, node.lineno, function, dotted(node), assignment))
        if isinstance(node, ast.Call):
            callee = dotted(node.func)
            if function and callee.rsplit(".", 1)[-1] in {"entry_points", "exec", "eval", "register"}:
                self.registry_functions.add((file, function[0]))
            if callee in {"getattr", "hasattr", "setattr", "delattr"} and len(node.args) >= 2:
                arg = node.args[1]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self.references[arg.value].append((file, node.lineno, function, "", None))
                else:
                    receiver = dotted(node.args[0])
                    self.dynamic[callee].append((file, node.lineno, receiver))
                    self.opaque_attributes.append((file, node.lineno, receiver, owner, function))
            if callee in {"importlib.import_module", "__import__"} and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self.add_visibility(file, arg.value)
                else:
                    self.dynamic["import"].append((file, node.lineno, ""))
                    if function:
                        self.registry_functions.add((file, function[0]))
            if (isinstance(node.func, ast.Attribute)
                    and dotted(node.func.value).endswith(".__dict__") and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                self.references[node.args[0].value].append((file, node.lineno, function, "", None))
        for child in ast.iter_child_nodes(node):
            self.visit(file, child, owner, function, assignment)

    @lru_cache(maxsize=None)
    def resolve_import(self, name):
        pending = [name]
        resolved = {name}
        while pending:
            candidate = pending.pop()
            mod, _, attr = candidate.rpartition(".")
            file = self.module_paths.get(mod)
            if not file:
                continue
            for path in self.imports.get(file, {}).get(attr, ()):
                if path not in resolved:
                    pending.append(path)
                    resolved.add(path)
        return resolved

    def dependent_sites(self, file, qualifier, kind):
        pending = [(file, qualifier, kind)]
        seen = set()
        sites = set()
        init = set()
        aliases = set()
        while pending:
            origin, binding, category = pending.pop()
            if (origin, binding, category) in seen:
                continue
            seen.add((origin, binding, category))
            name = binding.split(".")[-1]
            targets = {f"{module_name(origin)}.{binding}"}
            for ref_file, refs in self.imports.items():
                if category != "module_scalar":
                    continue
                for alias, paths in refs.items():
                    direct = any(targets & self.resolve_import(path) for path in paths)
                    star = alias == "*" and f"{module_name(origin)}.*" in paths
                    if direct or star:
                        local = name if star else alias
                        aliases.add(f"{ref_file}:{local}")
                        pending.append((ref_file, local, "module_scalar"))

            for src, line, function, expression, derived in self.references[name]:
                if category == "module_scalar":
                    if expression == name and src != origin:
                        continue
                    # Retain attribute reads by spelling when a receiver can
                    # be rebound locally, including imported aliases.
                if derived:
                    pending.append((src, derived, "class_scalar" if "." in derived else "module_scalar"))
                    aliases.add(f"{src}:{derived}")
                elif function is None or function[0].split(".")[-1] in {
                    "__new__", "__init_subclass__", "__set_name__", "__prepare__", "__getattr__",
                }:
                    init.add(f"{src}:{line}")
                else:
                    sites.add((src, line, function))
        return sites, init, aliases

    def class_family(self, file, binding):
        owner = f"{module_name(file)}.{binding.rsplit('.', 1)[0]}"
        visited = set()
        for graph in (self.parents, self.children):
            pending = [owner]
            through = set()
            while pending:
                name = pending.pop()
                if name not in through:
                    through.add(name)
                    pending.extend(graph.get(name, set()) - through)
            visited.update(through)
        unknown = False
        for name in visited:
            if name not in self.class_locations:
                unknown = True
                continue
            src, node = self.class_locations[name]
            if node.decorator_list:
                unknown = True
            for keyword in node.keywords:
                # The audited _Dialect metaclass reads selected names and may
                # mutate component registries. Keep all its reads as barriers.
                if not (keyword.arg == "metaclass" and dotted(keyword.value) == "_Dialect"
                        and any(key.endswith("._Dialect") and key.startswith(module_name(src) + ".")
                                for key in self.class_locations)):
                    unknown = True
        return visited, unknown


def resolve_factory(graph, file, name):
    """Find a module-level function reached by a bare local name."""
    candidates = [f"{module_name(file)}.{name}"]
    for path in graph.imports.get(file, {}).get(name, ()):
        candidates.extend(graph.resolve_import(path))
    for candidate in candidates:
        module, _, attribute = candidate.rpartition(".")
        target = graph.module_paths.get(module)
        if not target:
            continue
        for node in graph.trees[target].body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == attribute:
                return target, node
    return None


def closure_factory(node):
    """Return the closure a pure factory hands back, or None.

    Every statement must be a nested definition or a return of one of those
    definitions, so calling the factory cannot touch module or class state.
    """
    if node.decorator_list or isinstance(node, ast.AsyncFunctionDef):
        return None
    defined = {}
    returned = None
    for statement in node.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined[statement.name] = statement
        elif isinstance(statement, ast.Return):
            if not isinstance(statement.value, ast.Name) or statement.value.id not in defined:
                return None
            returned = statement.value.id
        elif isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue  # a docstring
        else:
            return None
    if returned is None:
        return None
    for descendant in ast.walk(node):
        if isinstance(descendant, (ast.Global, ast.Nonlocal, ast.Import, ast.ImportFrom)):
            return None
        if isinstance(descendant, (ast.Attribute, ast.Subscript)) and isinstance(
                descendant.ctx, (ast.Store, ast.Del)):
            return None
        if isinstance(descendant, ast.Call) and dotted(descendant.func) in {
                "setattr", "delattr", "exec", "eval", "compile", "__import__", "globals", "vars"}:
            return None
    return defined[returned]


def parents_of(tree):
    table = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            table[child] = node
    return table


def key_only_read(tree, line, attribute, owner, known_classes):
    """Decide whether reads of `owner.attribute` on one line observe a value.

    Membership tests, key iteration and `keys()` only look at the key set, so
    a value-only edit under an unchanged key set is invisible to them. A read
    qualified by a different class names a different binding and is skipped; an
    unresolvable receiver is treated as observing.
    """
    table = parents_of(tree)
    enclosing = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for descendant in ast.walk(node):
                enclosing.setdefault(descendant, node.name)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Name, ast.Attribute)) or node.lineno != line:
            continue
        name = node.id if isinstance(node, ast.Name) else node.attr
        if name != attribute or not isinstance(node.ctx, ast.Load):
            continue
        if isinstance(node, ast.Attribute):
            receiver = dotted(node.value).rsplit(".", 1)[-1]
            if receiver not in {owner, "cls", "klass", "self"}:
                if receiver in known_classes:
                    continue  # a different class's binding of the same name
                return False
        elif enclosing.get(node) != owner:
            continue  # a bare name inside another class body
        parent = table.get(node)
        if isinstance(parent, ast.Compare) and parent.comparators and parent.comparators[0] is node \
                and len(parent.ops) == 1 and isinstance(parent.ops[0], (ast.In, ast.NotIn)):
            continue
        if isinstance(parent, (ast.For, ast.AsyncFor, ast.comprehension)) and parent.iter is node:
            continue
        if isinstance(parent, ast.Attribute) and parent.attr == "keys":
            continue
        if isinstance(parent, ast.Call) and dotted(parent.func) == "len" and node in parent.args:
            continue
        return False
    return True


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("source", type=Path)
    cli.add_argument("coverage", type=Path)
    cli.add_argument("resources", type=Path)
    cli.add_argument("output", type=Path)
    cli.add_argument("--audit", type=Path)
    args = cli.parse_args()
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    assert subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip() == REVISION
    assert not subprocess.check_output(["git", "-C", str(args.source), "status", "--porcelain", "--untracked-files=all"])
    index = json.loads(args.coverage.read_bytes())
    resources = json.loads(args.resources.read_bytes())
    assert index["source_revision"] == resources["source_revision"] == REVISION
    graph = SourceGraph(args.source, index)
    test_sets = list(map(decode_set, index["test_sets"]))
    shared_sets = list(map(decode_set, index["shared_sets"]))
    ordinals = {t["id"]: i for i, t in enumerate(index["tests"])}
    process = resources["process"]
    process_bits = sum(1 << ordinals[i] for i in set(process["tests"])) if process["complete"] else 0
    inspection = 0
    evidence = json.loads(args.coverage.with_name("class_evidence.json").read_bytes())
    for name in evidence["source_inspection_files"]:
        inspection |= test_sets[index["cohorts"].get(name, 0)]

    def coverage_for(file, start, end):
        bits, shared = 0, 0
        for a, b, tests, contexts in index["files"][file]["lines"]:
            if a <= end and b >= start:
                bits |= test_sets[tests]
                shared |= shared_sets[contexts]
        for ordinal in members(shared):
            context = index["shared_contexts"][ordinal]
            if context["kind"] != "global":
                bits |= test_sets[context["consumers"]]
            elif context["id"] == "shared:process" and process_bits:
                bits |= process_bits
            else:
                return 0, context["id"]
        return bits, None

    routes, audit = {}, {}
    for file, entries in sorted(graph.declarations.items()):
        if not file.startswith("sqlglot/"):
            continue
        duplicates = Counter(key for key, _, _ in entries)
        for key, kind, node in entries:
            label = f"{file}::{key}"
            if duplicates[key] != 1:
                continue
            factory_reason = None
            if kind == "deferred_lambda":
                sites = {(file, node.lineno + 1, ("<lambda>", node.lineno + 1, node.end_lineno))}
                init, aliases = set(), set()
            elif kind == "deferred_factory":
                container = key.split("[")[0]
                attribute = container.rsplit(".", 1)[-1]
                sites, init, aliases = graph.dependent_sites(file, container, "class_scalar")
                # A read during class creation only blocks the route when it
                # can observe a value rather than the key set.
                owner = container.rsplit(".", 1)[0].rsplit(".", 1)[-1]
                known = {name.rsplit(".", 1)[-1] for name in graph.class_locations}
                for site in sorted(init):
                    src, _, line = site.rpartition(":")
                    tree = graph.trees.get(src)
                    if tree is None or not key_only_read(tree, int(line), attribute, owner, known):
                        factory_reason = f"value_observing_initializer:{site}"
                        break
                else:
                    init = set()
                resolved = resolve_factory(graph, file, node.func.id)
                if resolved is None:
                    factory_reason = factory_reason or f"unresolved_factory:{node.func.id}"
                elif closure_factory(resolved[1]) is None:
                    factory_reason = factory_reason or f"impure_factory:{node.func.id}"
                else:
                    target, definition = resolved
                    inner = closure_factory(definition)
                    # Creating the closure runs at import, but its body runs
                    # only when the parser reaches this entry, so the body is
                    # what can observe the changed argument.
                    start = inner.body[0].lineno
                    sites.add((target, start, ("<factory>", start, inner.end_lineno)))
            else:
                sites, init, aliases = graph.dependent_sites(file, key, kind)
            hierarchy, unknown = (graph.class_family(file, key.split("[")[0])
                                  if kind in ("class_scalar", "deferred_factory") else (set(), False))
            for src, line, receiver, owner, function in graph.opaque_attributes:
                # A known or possible receiver in the relevant namespace
                # contributes its cohort. Unresolved site attribution widens.
                local = kind == "module_scalar" and src == file and (
                    receiver in {"", "module", "sys.modules"} or receiver.startswith("module.")
                )
                member = (kind == "class_scalar" and receiver in {"self", "cls"}
                          and f"{module_name(src)}.{'.'.join(owner)}" in hierarchy)
                if local or member:
                    if function is None:
                        init.add(f"{src}:{line}")
                    else:
                        sites.add((src, line, function))
            reason = "initializer_reference" if init else "unresolved_class_hierarchy" if unknown else None
            bits = 0
            references = []
            for src, line, function in sorted(sites):
                name, start, end = function
                if (src, name) in graph.registry_functions:
                    reason = reason or "dynamic_registry_consumer"
                if name == "<lambda>":
                    cohort, issue = coverage_for(src, start, end)
                else:
                    # A same-shape scalar replacement can first affect an
                    # execution at a read. If no read is observed, widen to the
                    # enclosing body, then fall back if attribution is missing.
                    cohort, issue = coverage_for(src, line, line)
                    if not cohort and not issue:
                        cohort, issue = coverage_for(src, start + 1, end)
                references.append([src, line, name])
                if issue or not cohort:
                    reason = reason or issue or "unobserved_consumer"
                bits |= cohort
            if not bits:
                reason = reason or "no_consumer_evidence"
            audit[label] = {"kind": kind, "reason": reason, "references": references,
                            "initializers": sorted(init), "aliases": sorted(aliases),
                            "class_hierarchy": sorted(hierarchy)}
            if reason is None:
                bits |= inspection
                routes[label] = {"kind": kind,"tests": spans(bits)}
    # Capture audited initializer code and relationships in the provenance;
    # the runtime only needs the precomputed routes for changed bindings.
    result = {"schema_version": 1, "source_revision": REVISION, "coverage_sha256": sha(args.coverage),
              "resource_sha256": sha(args.resources), "class_evidence_sha256": sha(args.coverage.with_name("class_evidence.json")),
              "generator_sha256": sha(Path(__file__)),
              "initializer_policy": "fallback on initializer reads, changes to binding shape, mutable values, and unattributed execution",
              "routes": routes}
    args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    if args.audit:
        inventory = {"declarations": audit, "dynamic": graph.dynamic,
                     "code_elements": {file: sorted(names) for file, names in graph.elements.items()},
                     "classes": {f:facts for f, facts in (
                         (file,{name:[ast.unparse(base) for base in cls.bases] for name,cls in classes.items()})
                         for file,classes in graph.classes.items())},
                     "imports": {file: sorted(names) for file,names in graph.visibility.items()}}
        args.audit.write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n")
    print(f"{len(routes)} supported bindings out of {len(audit)} indexed bindings")


if __name__ == "__main__":
    main()
