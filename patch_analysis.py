"""Strict in-memory unified diffs and clean-source scope correspondence."""

from __future__ import annotations

import ast
from bisect import bisect_left
from collections import Counter
import copy
from dataclasses import dataclass, field
import io
from pathlib import PurePosixPath
import re
import shlex
import tokenize


class UncertainPatch(ValueError):
    pass


def normalize_path(value, git_prefix=True):
    if value == "/dev/null":
        return None
    if value.startswith('"'):
        parts = shlex.split(value)
        if len(parts) != 1 or "\\" in parts[0]:
            raise UncertainPatch("unsupported_quoted_path")
        value = parts[0]
    if git_prefix and value.startswith(("a/", "b/")):
        value = value[2:]
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or "\0" in value or not path.parts:
        raise UncertainPatch("unsafe_path")
    return str(path)


@dataclass
class FilePatch:
    old: str | None
    new: str | None
    hunks: list = field(default_factory=list)
    mode_change: bool = False


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)?$")


def parse_patch(text):
    lines = text.splitlines(keepends=True)
    changes = []
    current = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            fields = shlex.split(line.rstrip("\n"))
            if len(fields) != 4:
                raise UncertainPatch("unsupported_diff_header")
            current = FilePatch(normalize_path(fields[2]), normalize_path(fields[3]))
            changes.append(current)
        elif line.startswith("--- "):
            old = normalize_path(line[4:].rstrip("\n").split("\t")[0])
            if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
                raise UncertainPatch("missing_new_path")
            new = normalize_path(lines[i + 1][4:].rstrip("\n").split("\t")[0])
            if current is None or current.hunks:
                current = FilePatch(old, new)
                changes.append(current)
            else:
                current.old, current.new = old, new
            i += 1
        elif line.startswith("@@"):
            match = HUNK.match(line.rstrip("\n"))
            if current is None or not match:
                raise UncertainPatch("invalid_hunk_header")
            old_start, old_count, new_start, new_count = match.groups()
            old_start, new_start = int(old_start), int(new_start)
            old_count = int(old_count) if old_count is not None else 1
            new_count = int(new_count) if new_count is not None else 1
            body = []
            used_old = used_new = 0
            i += 1
            while i < len(lines):
                part = lines[i]
                if part.startswith("\\ No newline at end of file"):
                    if not body or not body[-1][1].endswith("\n"):
                        raise UncertainPatch("invalid_no_newline_marker")
                    body[-1] = (body[-1][0], body[-1][1][:-1])
                    i += 1
                    continue
                if used_old == old_count and used_new == new_count:
                    break
                if not part or part[0] not in " +-":
                    raise UncertainPatch("invalid_hunk_line")
                mark = part[0]
                used_old += mark != "+"
                used_new += mark != "-"
                if used_old > old_count or used_new > new_count:
                    raise UncertainPatch("hunk_count_mismatch")
                body.append((mark, part[1:]))
                i += 1
            if (used_old, used_new) != (old_count, new_count):
                raise UncertainPatch("truncated_hunk")
            current.hunks.append((old_start, old_count, new_start, new_count, body))
            continue
        elif line.startswith(("Binary files ", "GIT binary patch", "diff --cc ", "@@@")):
            raise UncertainPatch("unsupported_binary_or_combined_diff")
        elif current is not None and line.startswith(("old mode ", "new mode ", "new file mode ", "deleted file mode ")):
            current.mode_change = True
        elif current is not None and line.startswith("rename from "):
            current.old = normalize_path(line[12:].rstrip("\n"), git_prefix=False)
        elif current is not None and line.startswith("rename to "):
            current.new = normalize_path(line[10:].rstrip("\n"), git_prefix=False)
        elif line.strip() and not line.startswith(("index ", "similarity index ")):
            raise UncertainPatch("unsupported_patch_record")
        i += 1
    if not changes:
        raise UncertainPatch("empty_patch")
    names = [change.old or change.new for change in changes]
    if len(names) != len(set(names)):
        raise UncertainPatch("repeated_file_block")
    return changes


def reconstruct(base, change):
    old = base.splitlines(keepends=True)
    output = []
    cursor = 0
    removed, added = set(), set()
    for old_start, old_count, new_start, new_count, body in change.hunks:
        position = old_start - 1 if old_count else old_start
        if position < cursor or position > len(old):
            raise UncertainPatch("hunk_offset_mismatch")
        output.extend(old[cursor:position])
        cursor = position
        expected = new_start - 1 if new_count else new_start
        if len(output) != expected:
            raise UncertainPatch("new_hunk_offset_mismatch")
        for mark, content in body:
            if mark != "+":
                if cursor >= len(old) or old[cursor] != content:
                    raise UncertainPatch("base_context_mismatch")
                if mark == "-":
                    removed.add(cursor + 1)
                cursor += 1
            if mark != "-":
                if mark == "+":
                    added.add(len(output) + 1)
                output.append(content)
    output.extend(old[cursor:])
    return "".join(output), removed, added


class StripBodies(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        node.body = [ast.Pass()]
        return node

    visit_AsyncFunctionDef = visit_FunctionDef


def analyze(text):
    tree = ast.parse(text)
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    token_lines = [token.start[0] for token in tokens]
    scopes = {}
    class_shapes = {}
    occurrences = Counter()

    def visit(node, parents=()):
        for child in ast.iter_child_nodes(node):
            nested = parents
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified = parents + (child.name,)
                occurrences[qualified] += 1
                count = occurrences[qualified]
                key = qualified if count == 1 else parents + (f"{child.name}#{count}",)
                header = {name: ast.dump(value, include_attributes=False) if isinstance(value, ast.AST)
                          else [ast.dump(v, include_attributes=False) for v in value] if isinstance(value, list)
                          else value for name, value in ast.iter_fields(child) if name != "body"}
                start = child.lineno
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    depth = 0
                    for index in range(bisect_left(token_lines, child.lineno), len(tokens)):
                        token = tokens[index]
                        if token.type == tokenize.OP:
                            if token.string in "([{": depth += 1
                            elif token.string in ")]}": depth -= 1
                            elif token.string == ":" and depth == 0:
                                start = token.start[0] + 1
                                break
                else:
                    class_shapes[key] = ast.dump(StripBodies().visit(copy.deepcopy(child)), include_attributes=False)
                scopes[key] = {"node": child, "header": header, "body_start": start,
                               "end": child.end_lineno, "parents": parents}
                nested = key
            visit(child, nested)

    visit(tree)
    shape = ast.dump(StripBodies().visit(copy.deepcopy(tree)), include_attributes=False)
    return {"tree": tree, "scopes": scopes, "shape": shape, "class_shapes": class_shapes,
            "lines": text.splitlines()}


def affected_functions(old, new, removed, added):
    if old["shape"] != new["shape"] or old["class_shapes"] != new["class_shapes"] or set(old["scopes"]) != set(new["scopes"]):
        raise UncertainPatch("structural_or_initialization_change")
    if any(old["scopes"][key]["header"] != new["scopes"][key]["header"] for key in old["scopes"]):
        raise UncertainPatch("scope_header_change")
    affected = set()
    for analysis, changed in ((old, removed), (new, added)):
        for line in changed:
            enclosing = {key for key, scope in analysis["scopes"].items()
                         if isinstance(scope["node"], (ast.FunctionDef, ast.AsyncFunctionDef))
                         and scope["body_start"] <= line <= scope["end"]}
            if not enclosing:
                # Attach adjacent indented comment blocks to the following
                # method, never an unrelated file-header or class comment.
                lines = analysis["lines"]
                content = lines[line - 1]
                indent = len(content) - len(content.lstrip(" "))
                if indent and content.lstrip(" ").startswith("#"):
                    next_line = line
                    prefix = " " * indent + "#"
                    while next_line < len(lines) and lines[next_line].startswith(prefix):
                        next_line += 1
                    enclosing = {key for key, scope in analysis["scopes"].items()
                                 if isinstance(scope["node"], (ast.FunctionDef, ast.AsyncFunctionDef))
                                 and scope["node"].col_offset == indent
                                 and min([scope["node"].lineno] + [d.lineno for d in scope["node"].decorator_list]) == next_line + 1}
            if not enclosing:
                raise UncertainPatch("outside_function_body")
            affected.update(enclosing)
    if not affected:
        raise UncertainPatch("no_localized_edit")
    return affected
