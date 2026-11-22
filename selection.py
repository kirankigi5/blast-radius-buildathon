"""Coverage-informed candidate selection, with explicit conservative fallbacks."""

import ast
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
from declarations import changed_bindings

from patch_analysis import (
    UncertainPatch, affected_functions, analyze, behavior_preserving_text, docstrings,
    import_comment_insertion, localized_statement, observer_sensitive_edits, parse_patch,
    prose_comment_insertions, reconstruct, shifted_line,
)

REVISION = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
RESOURCE_STATE_CHANGE = re.compile(
    r"(?im)^\s*#|\b(?:insert|update|delete|merge|truncate|create|alter|drop|set|attach|"
    r"detach|copy|load|pragma|install|replace|commit|rollback|begin|call|grant|revoke)\b"
)


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


def isolated_test_structure(old, new):
    """Limit declaration routing to module-local bindings with inert headers."""
    def split_declarations(body):
        fixed, bindings = [], {}
        for node in body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)
                    and not node.targets[0].id.startswith("__")):
                name = node.targets[0].id
            elif (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and not node.decorator_list and node.returns is None and not node.args.defaults
                  and not any(node.args.kw_defaults)
                  and not any(isinstance(n, ast.arg) and n.annotation for n in ast.walk(node.args))
                  and not getattr(node, "type_params", None) and not node.name.startswith("__")):
                name = node.name
            else:
                fixed.append(node)
                continue
            if name in bindings:
                return None
            bindings[name] = node
        return fixed, bindings

    def compare(old_body, new_body, in_class=False):
        a, b = split_declarations(old_body), split_declarations(new_body)
        if a is None or b is None or len(a[0]) != len(b[0]):
            return False
        # If executable statements could observe a binding during definition,
        # keep the all-test fallback. Normal imports and the module docstring
        # are the only allowed fixed statements outside the test class.
        for left, right in zip(a[0], b[0]):
            if not in_class and isinstance(left, ast.ClassDef) and isinstance(right, ast.ClassDef):
                header = lambda n: (n.name, [ast.dump(x) for x in n.bases],
                                    n.keywords, n.decorator_list, getattr(n, "type_params", None))
                if (header(left) != header(right) or left.keywords or left.decorator_list
                        or [ast.unparse(x) for x in left.bases] != ["unittest.TestCase"]
                        or not compare(left.body, right.body, in_class=True)):
                    return False
            elif ((not in_class and isinstance(left, (ast.Import, ast.ImportFrom))) or
                  (isinstance(left, ast.Expr) and isinstance(left.value, ast.Constant)
                   and isinstance(left.value.value, str))):
                if ast.dump(left) != ast.dump(right):
                    return False
            else:
                # Unchanged member definitions with dynamic decorators,
                # annotations or defaults could read the changed bindings.
                return False
        return True

    return compare(old.body, new.body)


class SelectionPolicy:
    def __init__(self, tests, index_dir, base_dir, *, conditional_classes=True,
                 precise_body=True, diagnostic_imports=False, declaration_families=None):
        self.tests = tests
        self.dialect_local = os.environ.get("BR_DIALECT_LOCAL", "1") != "0"
        self.all_numbers = frozenset(t["number"] for t in tests)
        self.base_dir = Path(base_dir)
        self.base_cache = {}
        self.text_cache = {}
        self.reverse_imports = None
        self.resources = {}
        self.ordinals = {}
        self.conditional_classes = conditional_classes
        self.precise_body = precise_body
        self.diagnostic_imports = diagnostic_imports
        self.class_risks = {}
        self.class_methods = {}
        self.decorator_cohort = {}
        self.inspection_tests = 0
        self.declaration_routes = {}
        self.source_observation = None
        self.process_paths = {}
        self.process_pools = []
        self.process_context = 0
        self.declaration_families = ({"module_scalar", "class_scalar", "deferred_lambda",
                                      "deferred_factory"}
                                     if declaration_families is None else declaration_families)
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
            self.ordinals = identities
            coupling_path = index_dir / "class_evidence.json"
            if coupling_path.is_file():
                coupling = json.loads(coupling_path.read_text())
                if (coupling["source_revision"] == REVISION
                        and coupling["index_sha256"] == provenance["index_sha256"]):
                    self.class_risks = coupling["class_risks"]
                    # Absent per-method detail keeps the complete-class rule.
                    self.class_methods = coupling.get("class_methods", {})
                    for file in coupling["source_inspection_files"]:
                        self.inspection_tests |= self.sets[self.index["cohorts"].get(file, 0)]
            resource_path = index_dir / "resources.json"
            if resource_path.is_file():
                resources = json.loads(resource_path.read_text())
                if (resources["schema_version"] == 1 and resources["source_revision"] == REVISION
                        and resources["manifest_sha256"] == provenance.get("manifest_sha256")):
                    self.resources = resources
            declaration_path = index_dir / "declarations.json"
            if self.declaration_families and declaration_path.is_file() and resource_path.is_file() and coupling_path.is_file():
                declaration_map = json.loads(declaration_path.read_bytes())
                if (declaration_map["schema_version"] == 1 and declaration_map["source_revision"] == REVISION
                        and declaration_map["coverage_sha256"] == provenance["index_sha256"]
                        and declaration_map["resource_sha256"] == hashlib.sha256(resource_path.read_bytes()).hexdigest()
                        and declaration_map["class_evidence_sha256"] == hashlib.sha256(coupling_path.read_bytes()).hexdigest()):
                    self.declaration_routes = declaration_map["routes"]
            observer_path = index_dir / "source_observers.json"
            if observer_path.is_file() and resource_path.is_file():
                observers = json.loads(observer_path.read_bytes())
                if (observers["schema_version"] == 1 and observers["source_revision"] == REVISION
                        and observers["index_sha256"] == provenance["index_sha256"]
                        and observers["manifest_sha256"] == provenance.get("manifest_sha256")
                        and observers["resources_sha256"] == hashlib.sha256(resource_path.read_bytes()).hexdigest()
                        and not observers["static_unresolved"]):
                    self.source_observation = observers
            process_path = index_dir / "process_tasks.json"
            if process_path.is_file() and self.resources.get("process", {}).get("complete"):
                trace = json.loads(process_path.read_bytes())
                if (trace["schema_version"] == 1 and trace["source_revision"] == REVISION
                        and trace["index_sha256"] == provenance["index_sha256"]
                        and trace["manifest_sha256"] == provenance.get("manifest_sha256")
                        and trace["resources_sha256"] == hashlib.sha256(resource_path.read_bytes()).hexdigest()
                        and trace["corpus"]["numbered_tests"] == len(self.canonical)):
                    self.process_context = sum(1 << i for i, ctx in enumerate(self.index["shared_contexts"])
                                               if ctx["id"] == "shared:process")
                    valid = (1 << len(self.canonical)) - 1
                    pools = [sum(1 << i for i in set(owners)) for owners in trace["pool_tests"]]
                    if all(bits and bits & valid == bits for bits in pools):
                        self.process_paths = trace["paths"]
                        self.process_pools = pools
            self.execution_files = {}
            self.execution_import = {}
            execution_path = index_dir / "execution.json"
            if execution_path.is_file():
                executed = json.loads(execution_path.read_bytes())
                if (executed.get("schema_version") == 1 and executed.get("source_revision") == REVISION
                        and executed.get("index_sha256") == provenance["index_sha256"]
                        and executed.get("test_count") == len(self.canonical)):
                    sets = [decode_set(groups) for groups in executed["test_sets"]]
                    valid = (1 << len(self.canonical)) - 1
                    files = {}
                    for name, rows in executed["files"].items():
                        parsed = []
                        for start, end, index in rows:
                            mask = sets[index]
                            if mask & valid != mask:
                                raise ValueError("execution_ordinal")
                            parsed.append((start, end, mask))
                        files[name] = parsed
                    self.execution_files = files
                    self.execution_import = {
                        name: [(start, end) for start, end in rows]
                        for name, rows in executed.get("import_lines", {}).items()
                    }
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
            # A call-scoped patch decorator couples its own method to the
            # module it patches, so that method joins any narrowed seed of its
            # class. An unknown decorator anywhere in the class forfeits the
            # scoped cohort and the complete class cohort is used instead.
            for class_name, detail in self.class_methods.items():
                if detail.get("unknown"):
                    continue
                bits = 0
                for method in detail.get("call_scoped", ()):
                    ordinal = identities.get(f"{class_name}::{method}")
                    if ordinal is not None:
                        bits |= 1 << ordinal
                self.decorator_cohort[class_name] = bits
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

    def identity_bits(self, identities):
        bits = 0
        for identity in identities:
            if identity not in self.ordinals:
                raise UncertainPatch("unresolved_dependency_identity")
            bits |= 1 << self.ordinals[identity]
        return bits

    def resource_cohort(self, change):
        file = change.old
        if not self.resources or not file or change.new not in (file, None):
            raise UncertainPatch("unknown_resource_or_path_change")
        record = self.resources["files"].get(file)
        if not record or not record["readers"]:
            raise UncertainPatch("resource_without_reader_evidence")
        content = (self.base_dir / file).read_bytes()
        if hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise UncertainPatch("resource_base_hash_mismatch")
        new, removed, added = reconstruct(content.decode("utf-8"), change)
        if not (removed or added) or (change.new is None and new):
            raise UncertainPatch("invalid_resource_delta")
        entries = [record]
        # Contents-only edits cannot change directory membership. For removals,
        # retain enumerator dependencies even when a reader has been identified.
        if change.new is None:
            entries.extend(info for directory, info in self.resources["directories"].items()
                           if file.startswith(directory.rstrip("/") + "/"))
        bits = 0
        for entry in entries:
            if entry["unresolved"]:
                raise UncertainPatch("unattributed_resource_access")
            bits |= self.identity_bits(entry["readers"])
        return bits

    def direct_resource_reads(self, change):
        if (not change.old or change.old != change.new or change.mode_change
                or not change.old.endswith((".sql", ".json"))):
            return False
        contexts = self.resources["files"][change.old].get("contexts", ())
        if not contexts or any(not context.startswith("test|") or not context.endswith("|call")
                               for context in contexts):
            return False
        # Shared class setup can still exist, for example a database or worker
        # pool. Widen for edited metadata and potential state-changing SQL.
        return not any(RESOURCE_STATE_CHANGE.search(line)
                       for _, _, _, _, hunk in change.hunks for mark, line in hunk if mark != " ")

    def fallback(self, reason, reasons):
        return self.all_numbers, {"fallback": True, "reasons": sorted(set(reasons + [f"fallback:{reason}"]))}

    def process_line_cohort(self, file, ranges):
        needed = 0
        for first, last, _, contexts in self.index["files"][file]["lines"]:
            if not self.shared_sets[contexts] & self.process_context:
                continue
            for start, stop in ranges:
                lo, hi = max(first, start), min(last, stop)
                if lo <= hi:
                    needed |= (1 << (hi + 1)) - (1 << lo)
        if not needed:
            return 0
        pools = 0
        for first, last, mask, outside in self.process_paths.get(file, ()):
            span = (1 << (last + 1)) - (1 << first)
            if mask and not outside and needed & span:
                needed &= ~span
                pools |= mask
            if not needed:
                bits = 0
                for owner in members(pools):
                    bits |= self.process_pools[owner]
                return bits
        return 0

    def shared_consumers(self, shared, reasons, *, positional=False, child_cohort=0):
        bits = 0
        for context_id in members(shared):
            context = self.index["shared_contexts"][context_id]
            if context["kind"] == "global":
                if positional and context["id"] == "shared:collection":
                    # Compilation/import alone is position-bearing. Actual
                    # collection-time source and position readers are gated
                    # separately by the clean source-observation artifact.
                    continue
                process = self.resources.get("process", {})
                if context["id"] == "shared:process" and process.get("complete") and process.get("tests"):
                    if child_cohort:
                        bits |= child_cohort
                        reasons.append("clean_task_lines_pool_owners")
                    else:
                        bits |= self.identity_bits(process["tests"])
                        reasons.append("clean_process_owner_cohorts")
                    continue
                raise UncertainPatch(context["id"].replace(":", "_") + "_execution")
            consumers = self.sets[context["consumers"]]
            if not consumers:
                raise UncertainPatch("unknown_fixture_consumers")
            bits |= consumers
            reasons.append("shared_fixture_consumers")
        return bits

    def source_and_position_cohort(self, file, start, reasons, *, narrow_process=False):
        evidence = self.source_observation
        if file in evidence["unresolved"]:
            raise UncertainPatch("unattributed_source_or_position_observation")
        bits = 0
        for ordinal in (*evidence["static_tests"], *evidence["tests_by_file"].get(file, ())):
            if not 0 <= ordinal < len(self.canonical):
                raise UncertainPatch("invalid_source_observer_identity")
            bits |= 1 << ordinal
        if bits:
            reasons.append(f"source_observers:{file}")
        if start is not None:
            shifted = shared = 0
            for _, last, tests, contexts in self.index["files"][file]["lines"]:
                if last >= start:
                    shifted |= self.sets[tests]
                    shared |= self.shared_sets[contexts]
            child_cohort = 0
            if narrow_process and shared & self.process_context:
                child_cohort = self.process_line_cohort(file, [(start, len(self.base_text(file).splitlines()))])
            shifted |= self.shared_consumers(shared, reasons, positional=True, child_cohort=child_cohort)
            if shifted:
                reasons.append(f"shifted_python_execution:{file}")
            bits |= shifted
        return bits

    def traced_change(self, file, lines):
        """Tests that executed changed lines, from the in-process line trace.

        ``covered`` means every changed line was executed by a numbered test
        or only while importing. ``gap`` means the trace never saw a line, so
        the caller must keep the coarse process cohort. ``missing`` means this
        build has no execution map.
        """
        if not self.execution_files and not self.execution_import:
            return 0, "missing"
        if not lines:
            return 0, "missing"
        rows = self.execution_files.get(file)
        imports = self.execution_import.get(file, ())
        if rows is None and file not in self.execution_import:
            return 0, "gap"
        bits = 0
        covered = unseen = 0
        for line in lines:
            hit = 0
            if rows:
                for start, end, mask in rows:
                    if start > line:
                        break
                    if start <= line <= end and mask:
                        hit |= mask
            if hit:
                bits |= hit
                covered += 1
                continue
            if any(start <= line <= end for start, end in imports):
                covered += 1
                continue
            unseen += 1
        if unseen:
            return bits, "gap"
        if bits:
            return bits, "covered"
        if covered:
            return 0, "import_only"
        return 0, "gap"

    def declaration_selection(self, file, old_text, new_text, old, new):
        if not self.declaration_routes or not file.startswith("sqlglot/"):
            return 0, []
        changed = changed_bindings(old_text, new_text, old["tree"], new["tree"])
        bits = 0
        reasons = []
        for key, kind in changed:
            route = self.declaration_routes.get(f"{file}::{key}")
            if kind not in self.declaration_families or not route or route["kind"] != kind:
                return 0, []
            covered = decode_set(route["tests"])
            if not covered:
                return 0, []
            bits |= covered
            reasons.append(f"declaration:{kind}:{file}:{key}")
        return bits, reasons

    DIALECT_FAMILIES = ("sqlglot/dialects/", "sqlglot/parsers/", "sqlglot/generators/",
                        "sqlglot/tokenizers/", "sqlglot/typing/")
    DIALECT_SHARED = {"__init__", "dialect", "base"}
    ALL_DIALECT_MARKERS = ("Dialects", "Dialect.classes", "Dialect._classes", "DIALECTS",
                           "dialects.__all__", "MODULE_BY_DIALECT", "all_dialects", "for dialect in",
                           "for read in", "for write in", "Dialect.get", "Dialect[", "get_or_raise",
                           "getsource", "inspect.", "__file__", "importlib", "sys.modules")

    def dialect_local_cohort(self, changed_files):
        """Tests that can observe a change confined to one dialect's own files.

        A dialect's class constants and methods are only reachable through that
        dialect (or dialects that import/subclass it). Candidates are every
        test that executed any line of the family's files, every test of that
        dialect's test module, every test whose source names the dialect or
        walks all dialects, and readers of fixtures that name it. Returns None
        when the change is not dialect-local."""
        names = set()
        for file in changed_files:
            if not file or not file.startswith(self.DIALECT_FAMILIES) or not file.endswith(".py"):
                return None
            stem = file.rsplit("/", 1)[1][:-3]
            if stem in self.DIALECT_SHARED or stem.startswith("_"):
                return None
            names.add(stem)
        family = {f"{prefix}{name}.py" for prefix in self.DIALECT_FAMILIES for name in names}
        self.dependency_cohort([])  # builds reverse imports
        pending = [f for f in family if f in self.index["files"]]
        reached = set(pending)
        while pending:
            for importer in self.reverse_imports.get(pending.pop(), ()):
                if importer in reached:
                    continue
                if importer.startswith("tests/"):
                    continue
                if not importer.startswith(self.DIALECT_FAMILIES):
                    return None  # a shared module depends on this dialect
                stem = importer.rsplit("/", 1)[1][:-3]
                if stem in self.DIALECT_SHARED:
                    # the registry imports dialects lazily by name; fine only
                    # for the package __init__ files
                    if stem != "__init__":
                        return None
                    continue
                names.add(stem)
                reached.add(importer)
                pending.append(importer)
                for prefix in self.DIALECT_FAMILIES:
                    sibling = f"{prefix}{stem}.py"
                    if sibling in self.index["files"] and sibling not in reached:
                        reached.add(sibling)
                        pending.append(sibling)
        # Dialects also reach each other by name ("teradata" in Presto's
        # TO_CHAR), so any other dialect family file quoting a reached name
        # joins, to a fixed point.
        family_files = [f for f in self.index["files"]
                        if f.startswith(self.DIALECT_FAMILIES) and f.endswith(".py")
                        and f.rsplit("/", 1)[1][:-3] not in self.DIALECT_SHARED]
        changed = True
        while changed:
            changed = False
            quoted = re.compile("[\"']({})[\"']".format("|".join(re.escape(n) for n in sorted(names))),
                                re.IGNORECASE)
            for file in family_files:
                stem = file.rsplit("/", 1)[1][:-3]
                if stem in names:
                    continue
                if quoted.search(self.base_text(file)):
                    names.add(stem)
                    changed = True
                    for prefix in self.DIALECT_FAMILIES:
                        sibling = f"{prefix}{stem}.py"
                        if sibling in self.index["files"]:
                            reached.add(sibling)
        bits = 0
        for file in reached:
            for _, _, mask in self.execution_files.get(file, ()):
                bits |= mask
            bits |= self.sets[self.index["cohorts"].get(file, 0)]
        lowered = {name.lower() for name in names}
        patterns = [re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE) for name in lowered]
        markers = self.ALL_DIALECT_MARKERS
        for name in lowered:
            for test_file in (f"tests/dialects/test_{name}.py", f"tests/test_{name}.py"):
                bits |= self.sets[self.index["cohorts"].get(test_file, 0)]
        # Source mentions, per test method (class/module text widens).
        by_file = defaultdict(list)
        for ordinal, identity in enumerate(self.canonical):
            by_file[identity.split("::", 1)[0]].append((ordinal, identity))
        for test_file, rows in by_file.items():
            try:
                text = self.base_text(test_file)
                tree = ast.parse(text)
            except Exception:
                for ordinal, _ in rows:
                    bits |= 1 << ordinal
                continue
            lines = text.splitlines()

            def hit(segment):
                return any(p.search(segment) for p in patterns) or any(m in segment for m in markers)

            outside = []
            spans = {}
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    class_outside = []
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
                            spans[f"{node.name}::{item.name}"] = "\n".join(lines[item.lineno - 1 - len(item.decorator_list):item.end_lineno])
                        else:
                            class_outside.append("\n".join(lines[item.lineno - 1:item.end_lineno]))
                    spans[node.name] = "\n".join(class_outside)
                else:
                    outside.append("\n".join(lines[node.lineno - 1:node.end_lineno]))
            module_hit = hit("\n".join(outside))
            for ordinal, identity in rows:
                _, cls, method = identity.split("::")
                method_text = spans.get(f"{cls}::{method}")
                # Inherited or generated tests have no own text: keep them.
                if method_text is None or module_hit or hit(spans.get(cls, "")) or hit(method_text):
                    bits |= 1 << ordinal
        # Fixtures that name the dialect.
        for path, record in self.resources.get("files", {}).items():
            try:
                content = (self.base_dir / path).read_text("utf-8", errors="replace")
            except OSError:
                content = None
            if content is None or any(p.search(content) for p in patterns) or record.get("unresolved"):
                if record.get("unresolved"):
                    return None
                bits |= self.identity_bits(record["readers"])
        return bits

    def select(self, patch):
        reasons = []
        if self.startup_error:
            return self.fallback(self.startup_error, reasons)
        try:
            changes = parse_patch(patch)
            selected = 0
            widenable = 0
            changed_files = []
            comment_files = set()
            import_gap_files = set()
            prose_observer_files = set()
            python_changes = []
            process_compatible = set()
            python_files = set()
            process_prose_used = False
            for change in changes:
                file = change.old or change.new
                changed_files.append(file)
                if file and file.startswith("tests/fixtures/") and not file.endswith(".py"):
                    readers = self.resource_cohort(change)
                    selected |= readers
                    if self.conditional_classes and self.direct_resource_reads(change):
                        reasons.append("direct_resource_callers")
                    else:
                        widenable |= readers
                    reasons.append(f"resource_readers:{file}")
                    continue
                if not file or not file.endswith(".py"):
                    raise UncertainPatch("non_python_or_fixture_change")
                old_text, old = self.base(file) if change.old else ("", analyze(""))
                new_text, removed, added = reconstruct(old_text, change)
                new = analyze(new_text)
                if change.old != change.new:
                    raise UncertainPatch("file_add_delete_or_rename")
                if change.mode_change:
                    raise UncertainPatch("file_mode_change")
                python_files.add(file)
                if file.startswith("sqlglot/") and behavior_preserving_text(old_text, new_text):
                    # Comments, whitespace, and docstrings do not change behavior.
                    # Only tests that read the file as text need to run.
                    prose_observer_files.add(file)
                    reasons.append(f"behavior_preserving:{file}")
                    continue
                prose = bool(file.startswith("sqlglot/")
                             and prose_comment_insertions(old_text, new_text, removed, added))
                if prose and self.process_paths:
                    process_compatible.add(file)
                if self.source_observation:
                    python_changes.append((change, old_text, new_text, old, new, removed, added))
                    if (file.startswith("sqlglot/") and import_comment_insertion(
                            old_text, new_text, new["tree"], removed, added) is not None):
                        comment_files.add(file)
                        import_gap_files.add(file)
                        continue
                    if prose:
                        # Standalone prose outside the import gap keeps the
                        # narrower enclosing-body route, which measured cheaper
                        # than shifted execution, but the file's bytes and the
                        # positions of later definitions still changed, so its
                        # recorded source and position observers are unioned in.
                        prose_observer_files.add(file)
                try:
                    affected = affected_functions(old, new, removed, added)
                except UncertainPatch as error:
                    if str(error) == "structural_or_initialization_change":
                        cohort, evidence = self.declaration_selection(file, old_text, new_text, old, new)
                        if cohort:
                            selected |= cohort
                            widenable |= cohort
                            reasons.extend(evidence)
                            continue
                    if (str(error) != "structural_or_initialization_change"
                            or not self.index["cohorts"].get(file)
                            or not file.startswith("tests/test_") and not file.startswith("tests/dialects/test_")
                            or not isolated_test_structure(old["tree"], new["tree"])):
                        raise
                    cohort = self.dependency_cohort([file])
                    selected |= cohort
                    widenable |= cohort
                    reasons.append(f"test_declarations_and_import_dependents:{file}")
                    continue
                record = self.index["files"][file]
                shared = 0
                file_bits = 0
                localized = self.precise_body and not file.startswith("tests/") and localized_statement(
                    old, new, affected, removed, added
                )
                # Stage 10 accepted prose and a same-line bool or int
                # replacement here. The type restriction was the arbitrary
                # part: localized_statement already proves the edit introduces
                # no name, call or control-flow change, so a same-type string
                # or float replacement carries exactly the bool and int
                # exposure. An edit that changes a call stays unmodeled and
                # keeps the coarse cohort.
                trace_bits, trace_kind = self.traced_change(file, removed)
                precise_trace = trace_kind == "covered" and bool(trace_bits)
                narrow_process = bool(self.process_paths and file.startswith("sqlglot/") and (
                    prose or (localized and len(removed) == 1 and removed == added)
                ))
                process_ranges = [(line, line) for line in removed] if narrow_process else []
                if narrow_process:
                    process_compatible.add(file)
                for key in sorted(affected):
                    scope = old["scopes"][key]
                    new_scope = new["scopes"][key]
                    if any(not isinstance(d, ast.Name) or d.id not in {"property", "classmethod", "staticmethod"}
                           for d in scope["node"].decorator_list):
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
                    if not localized and not precise_trace:
                        if narrow_process:
                            process_ranges.append((scope["body_start"], scope["end"]))
                        for first, last, tests, contexts in record["lines"]:
                            if first <= scope["end"] and last >= scope["body_start"]:
                                file_bits |= self.sets[tests]
                                shared |= self.shared_sets[contexts]
                    reasons.append(f"function:{file}:{'.'.join(key)}")
                    if any(n.lstrip().startswith("#") for n in
                           (new["lines"][line - 1] for line in added if line < new_scope["body_start"])):
                        reasons.append("definition_boundary_comment")
                    if any("#" in part for part in key) or any(
                            peer[:-1] == key[:-1] and peer[-1].startswith(key[-1] + "#")
                            for peer in old["scopes"]):
                        reasons.append("paired_repeated_definition")
                for first, last, tests, contexts in record["lines"]:
                    if any(first <= line <= last for line in removed):
                        file_bits |= self.sets[tests]
                        shared |= self.shared_sets[contexts]
                if precise_trace:
                    # The line trace credited inlined pool work to the submitting
                    # test, so the 340-test process cohort would only add tests
                    # that never executed the edit. Class widening stays off for
                    # the same reason: siblings that did not run the line are
                    # not evidence of a failure.
                    file_bits |= trace_bits
                    shared &= ~self.process_context
                    reasons.append("per_test_line_execution")
                if localized and (file_bits or shared):
                    file_bits |= self.inspection_tests
                    reasons.append("localized_old_statement")
                elif localized:
                    for key in sorted(affected):
                        scope = old["scopes"][key]
                        for first, last, tests, contexts in record["lines"]:
                            if first <= scope["end"] and last >= scope["body_start"]:
                                file_bits |= self.sets[tests]
                                shared |= self.shared_sets[contexts]
                    reasons.append("unobserved_statement_use_body")
                child_cohort = 0
                if narrow_process and shared & self.process_context:
                    child_cohort = self.process_line_cohort(file, process_ranges)
                    process_prose_used |= bool(prose and child_cohort)
                file_bits |= self.shared_consumers(shared, reasons, child_cohort=child_cohort)
                if not file_bits:
                    raise UncertainPatch("no_body_coverage")
                if file.startswith("tests/"):
                    file_bits |= self.dependency_cohort([file])
                    reasons.append("test_helper_import_dependents")
                selected |= file_bits
                if not precise_trace:
                    widenable |= file_bits
            for file in sorted(prose_observer_files - comment_files):
                cohort = self.source_and_position_cohort(file, None, reasons)
                selected |= cohort
                widenable |= cohort
            if comment_files:
                for change, old_text, new_text, old, new, removed, added in python_changes:
                    file = change.old
                    if file in comment_files:
                        reasons.append(f"{'import_gap_comment' if file in import_gap_files else 'standalone_comment'}:{file}")
                    elif (not file.startswith("sqlglot/") or docstrings(old["tree"]) != docstrings(new["tree"])
                          or observer_sensitive_edits(old_text, removed) or observer_sensitive_edits(new_text, added)):
                        raise UncertainPatch("unresolved_companion_source_observation")
                    cohort = self.source_and_position_cohort(
                        file, shifted_line(change), reasons, narrow_process=file in process_compatible,
                    )
                    if not cohort and file in comment_files:
                        raise UncertainPatch("no_comment_observer_evidence")
                    selected |= cohort
                    widenable |= cohort
            if "clean_task_lines_pool_owners" in reasons and (
                    process_compatible != python_files or process_prose_used and not comment_files):
                coarse = self.identity_bits(self.resources["process"]["tests"])
                selected |= coarse
                widenable |= coarse
                reasons.append("clean_process_owner_cohorts")
                reasons.append("unresolved_patch_effects_retain_coarse_process")
            before = selected.bit_count()
            scoped = False
            for ordinal in members(widenable if self.conditional_classes else selected):
                class_name = self.canonical[ordinal].rsplit("::", 1)[0]
                if not self.conditional_classes:
                    selected |= self.class_cohort[ordinal]
                    continue
                risks = self.class_risks.get(class_name, ["unknown_class"])
                if not risks:
                    continue
                # Lifecycle hooks, class writes, mutable class state, dynamic
                # classes or mutation, nonlocal bindings, shared fixtures,
                # unresolved bases and unknown classes can couple any two
                # methods, so those keep the complete class cohort.
                if set(risks) == {"method_decorator"} and class_name in self.decorator_cohort:
                    selected |= self.decorator_cohort[class_name]
                    scoped = True
                else:
                    selected |= self.class_cohort[ordinal]
            if selected.bit_count() != before:
                reasons.append("test_class_cohorts")
            if scoped:
                reasons.append("decorator_scoped_class_cohort")
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
            # state remain gaps. Inspect the cohort only in development.
            if isinstance(error, UncertainPatch) and reason in {
                "structural_or_initialization_change", "scope_header_change",
                "file_add_delete_or_rename", "outside_function_body",
                "function_import_change",
            }:
                reasons.append("dependency_gap:dynamic_imports_inheritance_global_state")
                if self.dialect_local and reason == "structural_or_initialization_change":
                    try:
                        cohort = self.dialect_local_cohort(changed_files)
                    except (OSError, ValueError, SyntaxError, UncertainPatch, RecursionError, KeyError):
                        cohort = None
                    if cohort:
                        numbers = self.mandatory | {self.number_by_ordinal[i] for i in members(cohort)
                                                    if i in self.number_by_ordinal}
                        if numbers:
                            return frozenset(numbers), {"fallback": False,
                                                        "reasons": sorted(set(reasons + ["dialect_local_cohort"]))}
                if self.diagnostic_imports:
                    try:
                        cohort = self.dependency_cohort(changed_files)
                        reasons.append(f"source_import_cohort:{cohort.bit_count()}")
                    except (OSError, ValueError, SyntaxError, UncertainPatch, RecursionError):
                        reasons.append("dependency_analysis_incomplete")
            return self.fallback(reason, reasons)
