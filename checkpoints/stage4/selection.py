"""Coverage-informed candidate selection, with explicit conservative fallbacks."""

import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from patch_analysis import UncertainPatch, affected_functions, analyze, parse_patch, reconstruct

REVISION = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"


def decode_set(groups):
    value = 0
    for first, last in groups:
        value |= ((1 << (last - first + 1)) - 1) << first
    return value


def members(bits):
    while bits:
        least = bits & -bits
        yield least.bit_length() - 1
        bits ^= least


class SelectionPolicy:
    def __init__(self, tests, index_dir, base_dir):
        self.tests = tests
        self.all_numbers = frozenset(t["number"] for t in tests)
        self.base_dir = Path(base_dir)
        self.base_cache = {}
        self.text_cache = {}
        self.reverse_imports = None
        self.startup_error = None
        try:
            index_dir = Path(index_dir)
            raw = (index_dir / "index.json").read_bytes()
            self.index = json.loads(raw)
            audit = json.loads((index_dir / "audit.json").read_text())
            provenance = json.loads((index_dir / "provenance.json").read_text())
            if (self.index["schema_version"] != 1 or self.index["source_revision"] != REVISION or provenance["source_revision"] != REVISION
                    or hashlib.sha256(raw).hexdigest() != provenance["index_sha256"]
                    or not audit["raw_trace_complete"] or audit["collection_errors"]
                    or (self.base_dir / "REVISION").read_text().strip() != REVISION):
                raise ValueError("index_or_base_provenance")
            self.sets = [decode_set(groups) for groups in self.index["test_sets"]]
            self.shared_sets = [decode_set(groups) for groups in self.index["shared_sets"]]
            self.canonical = [row["id"] for row in self.index["tests"]]
            if len(self.canonical) != len(set(self.canonical)):
                raise ValueError("duplicate_index_identity")
            identities = {identity: i for i, identity in enumerate(self.canonical)}
            counts = Counter(t["id"] for t in tests)
            self.number_by_ordinal = {}
            self.mandatory = set()
            for test in tests:
                ordinal = identities.get(test["id"])
                if (ordinal is None or counts[test["id"]] != 1
                        or self.index["tests"][ordinal]["file"] != test["file"]
                        or self.index["tests"][ordinal]["incomplete"]):
                    self.mandatory.add(test["number"])
                else:
                    self.number_by_ordinal[ordinal] = test["number"]
            self.class_cohort = {}
            for i, identity in enumerate(self.canonical):
                name = identity.rsplit("::", 1)[0]
                self.class_cohort[i] = self.sets[self.index["cohorts"].get(name, 0)]
        except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
            self.startup_error = f"index_unavailable:{type(error).__name__}"

    def base_text(self, file):
        if file not in self.text_cache:
            record = self.index["files"].get(file)
            if record is None:
                raise UncertainPatch("unindexed_source")
            path = self.base_dir / file
            if not path.resolve().is_relative_to(self.base_dir.resolve()):
                raise UncertainPatch("unsafe_base_path")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != record["sha256"]:
                raise UncertainPatch("base_hash_mismatch")
            self.text_cache[file] = raw.decode("utf-8")
        return self.text_cache[file]

    def base(self, file):
        if file not in self.base_cache:
            text = self.base_text(file)
            self.base_cache[file] = (text, analyze(text))
        return self.base_cache[file]

    def dependency_cohort(self, changed_files):
        """Import closure is a widening hint, not a complete call graph."""
        if self.reverse_imports is None:
            files = self.index["files"]
            module_file = {}
            for file in files:
                module = file[:-3].replace("/", ".")
                if module.endswith(".__init__"):
                    module = module[:-9]
                module_file[module] = file
            reverse = defaultdict(set)
            for module, file in module_file.items():
                # Import analysis does not require unique function names.
                # Overloads/property accessors can make scope pairing ambiguous
                # without making the clean module's import AST ambiguous.
                tree = self.base_cache[file][1]["tree"] if file in self.base_cache else ast.parse(self.base_text(file))
                package = module if file.endswith("/__init__.py") else module.rpartition(".")[0]
                for node in ast.walk(tree):
                    targets = []
                    if isinstance(node, ast.Import):
                        targets.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        prefix = package.split(".") if package else []
                        if node.level:
                            prefix = prefix[:max(0, len(prefix) - node.level + 1)]
                            target = ".".join(prefix + ([node.module] if node.module else []))
                        else:
                            target = node.module or ""
                        targets.append(target)
                        targets.extend(f"{target}.{alias.name}" for alias in node.names)
                    for target in targets:
                        parts = target.split(".")
                        for length in range(1, len(parts) + 1):
                            dependency = module_file.get(".".join(parts[:length]))
                            if dependency:
                                reverse[dependency].add(file)
            self.reverse_imports = reverse
        reached = set(changed_files)
        pending = list(changed_files)
        while pending:
            for file in self.reverse_imports.get(pending.pop(), ()):
                if file not in reached:
                    reached.add(file)
                    pending.append(file)
        result = 0
        for file in reached:
            result |= self.sets[self.index["cohorts"].get(file, 0)]
        return result

    def fallback(self, reason, reasons):
        return self.all_numbers, {"fallback": True, "reasons": sorted(set(reasons + [f"fallback:{reason}"]))}

    def select(self, patch):
        reasons = []
        if self.startup_error:
            return self.fallback(self.startup_error, reasons)
        try:
            changes = parse_patch(patch)
            selected = 0
            changed_files = []
            for change in changes:
                file = change.old or change.new
                changed_files.append(file)
                if not file or not file.endswith(".py"):
                    raise UncertainPatch("non_python_or_fixture_change")
                old_text, old = self.base(file) if change.old else ("", analyze(""))
                new_text, removed, added = reconstruct(old_text, change)
                new = analyze(new_text)
                if change.old != change.new:
                    raise UncertainPatch("file_add_delete_or_rename")
                if change.mode_change:
                    raise UncertainPatch("file_mode_change")
                affected = affected_functions(old, new, removed, added)
                record = self.index["files"][file]
                shared = 0
                file_bits = 0
                for key in sorted(affected):
                    scope = old["scopes"][key]
                    new_scope = new["scopes"][key]
                    if scope["node"].decorator_list:
                        raise UncertainPatch("decorated_or_cached_function")
                    old_imports = [ast.dump(n) for n in ast.walk(scope["node"]) if isinstance(n, (ast.Import, ast.ImportFrom))]
                    new_imports = [ast.dump(n) for n in ast.walk(new_scope["node"]) if isinstance(n, (ast.Import, ast.ImportFrom))]
                    if old_imports != new_imports:
                        raise UncertainPatch("function_import_change")
                    nodes = [*ast.walk(scope["node"]), *ast.walk(new_scope["node"])]
                    if any(isinstance(node, (ast.Global, ast.Nonlocal)) for node in nodes):
                        raise UncertainPatch("nonlocal_state_dependency_gap")
                    if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                           and node.func.id in {"eval", "exec", "compile", "__import__"}
                           for node in nodes):
                        raise UncertainPatch("dynamic_execution_dependency_gap")
                    for first, last, tests, contexts in record["lines"]:
                        if first <= scope["end"] and last >= scope["body_start"]:
                            file_bits |= self.sets[tests]
                            shared |= self.shared_sets[contexts]
                    reasons.append(f"function:{file}:{'.'.join(key)}")
                for first, last, tests, contexts in record["lines"]:
                    if any(first <= line <= last for line in removed):
                        file_bits |= self.sets[tests]
                        shared |= self.shared_sets[contexts]
                for context_id in members(shared):
                    context = self.index["shared_contexts"][context_id]
                    if context["kind"] == "global":
                        raise UncertainPatch(context["id"].replace(":", "_") + "_execution")
                    consumers = self.sets[context["consumers"]]
                    if not consumers:
                        raise UncertainPatch("unknown_fixture_consumers")
                    file_bits |= consumers
                    reasons.append("shared_fixture_consumers")
                if not file_bits:
                    raise UncertainPatch("no_body_coverage")
                if file.startswith("tests/"):
                    file_bits |= self.dependency_cohort([file])
                    reasons.append("test_helper_import_dependents")
                selected |= file_bits
            before = selected.bit_count()
            for ordinal in list(members(selected)):
                selected |= self.class_cohort[ordinal]
            if selected.bit_count() != before:
                reasons.append("test_class_cohorts")
            numbers = self.mandatory | {self.number_by_ordinal[i] for i in members(selected) if i in self.number_by_ordinal}
            if self.mandatory:
                reasons.append(f"unresolved_or_incomplete_incoming:{len(self.mandatory)}")
            if not numbers:
                raise UncertainPatch("no_resolvable_candidates")
            return frozenset(numbers), {"fallback": False, "reasons": sorted(set(reasons))}
        except (UncertainPatch, SyntaxError, UnicodeError, OSError, ValueError, TypeError, KeyError, IndexError, RecursionError) as error:
            reason = str(error) if isinstance(error, UncertainPatch) else type(error).__name__
            # Structural edits cannot be narrowed safely with an import-only
            # graph: inheritance, re-exports, dynamic registries and nonlocal
            # state remain gaps. Compute its widening cohort, then retain all.
            if isinstance(error, UncertainPatch) and reason in {
                "structural_or_initialization_change", "scope_header_change",
                "file_add_delete_or_rename", "outside_function_body",
                "function_import_change",
            }:
                try:
                    cohort = self.dependency_cohort(changed_files)
                    reasons.append(f"source_import_cohort:{cohort.bit_count()}")
                    reasons.append("dependency_gap:dynamic_imports_inheritance_global_state")
                except (OSError, ValueError, SyntaxError, UncertainPatch, RecursionError):
                    reasons.append("dependency_analysis_incomplete")
            return self.fallback(reason, reasons)
