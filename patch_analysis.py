"""Strict in-memory unified diffs and clean-source scope correspondence."""

from __future__ import annotations

import ast
from bisect import bisect_left
from collections import Counter
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
PROSE_COMMENT = re.compile(r"# [A-Z][A-Za-z]*(?: [A-Za-z]+)+(?:[.!?])?\n")
COMMENT_CONTROL = re.compile(
    r"\b(?:coding|encoding|noqa|type|mypy|mypyc|pyright|pyrefly|pyre|ruff|pylint|"
    r"flake8|isort|fmt|black|pragma|nosec|coverage|pytest|region|endregion|"
    r"doctest|sphinx|directive|skip|ignore|disable|enable)\b", re.IGNORECASE
)
SOURCE_OBSERVER_NAMES = frozenset({
    "__code__", "__file__", "__loader__", "__doc__", "get_source", "get_data",
    "getsource", "getsourcelines", "getsourcefile", "getcomments", "findsource",
    "linecache", "getframeinfo", "currentframe", "_getframe", "extract_tb", "extract_stack",
    "f_code", "f_lineno", "tb_frame", "tb_lineno", "co_firstlineno", "co_linetable",
    "co_lnotab", "co_lines", "co_positions", "lineno", "end_lineno", "col_offset",
})
SOURCE_READER_NAMES = SOURCE_OBSERVER_NAMES | {
    "open", "read_text", "read_bytes", "inspect", "traceback", "runpy", "compile", "exec", "eval",
}


def import_comment_insertion(old_text, new_text, new_tree, removed, added):
    """Recognize a complete file delta of prose insertions between leading imports."""
    if removed or not added:
        return None
    lines = new_text.splitlines(keepends=True)
    if any(not PROSE_COMMENT.fullmatch(lines[i - 1]) or COMMENT_CONTROL.search(lines[i - 1])
           for i in added):
        return None
    if "".join(line for i, line in enumerate(lines, 1) if i not in added) != old_text:
        return None
    # A '#' inside a string or continuation cannot stand in for a comment token.
    tokens = tokenize.generate_tokens(io.StringIO(new_text).readline)
    comment_lines = {t.start[0] for t in tokens if t.type == tokenize.COMMENT and t.start[1] == 0}
    if not added <= comment_lines:
        return None
    body = new_tree.body[1:] if ast.get_docstring(new_tree, clean=False) is not None else new_tree.body
    eligible = set()
    previous = None
    for node in body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            break
        if previous is not None:
            gap = range(previous.end_lineno + 1, node.lineno)
            if all(i in added or not lines[i - 1].strip() for i in gap):
                eligible.update(gap)
        previous = node
    if not added <= eligible:
        return None
    before, after = (text.encode("utf-8") for text in (old_text, new_text))
    if any(tokenize.detect_encoding(io.BytesIO(text).readline)[0] != "utf-8" for text in (before, after)):
        return None
    if ast.dump(ast.parse(before, type_comments=True)) != ast.dump(ast.parse(after, type_comments=True)):
        return None
    return min(added)


def shifted_line(change):
    """Old coordinate before the first edit block that can shift later lines."""
    for old_start, old_count, _, _, body in change.hunks:
        line = old_start if old_count else old_start + 1
        balance = 0
        start = line
        for mark, _ in body:
            if mark == " ":
                if balance:
                    return max(1, start)
                line += 1
                start = line
            elif mark == "-":
                balance -= 1
                line += 1
            else:
                balance += 1
        if balance:
            return max(1, start)
    return None


def observer_sensitive_edits(text, lines):
    """Block new observation mechanisms and directives in a companion delta."""
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if not any(line in lines for line in range(token.start[0], token.end[0] + 1)):
            continue
        if token.type == tokenize.COMMENT and (COMMENT_CONTROL.search(token.string)
                                               or token.string.startswith("#!")):
            return True
        if token.type == tokenize.NAME and token.string in SOURCE_READER_NAMES:
            return True
        if token.type == tokenize.STRING and any(word in token.string for word in SOURCE_OBSERVER_NAMES):
            return True
    return False


def docstrings(tree):
    scopes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return [(getattr(node, "name", ""), text) for node in ast.walk(tree) if isinstance(node, scopes)
            if (text := ast.get_docstring(node, clean=False)) is not None]


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            body.pop(0)
        if not body:
            body.append(ast.Pass())
    return tree


def behavior_preserving_text(old_text, new_text):
    """True when comments, whitespace, and docstrings are the only differences.

    Type comments are part of the compared tree. A change to an executable
    constant, name, or call is not preserving.
    """
    try:
        old = ast.parse(old_text, type_comments=True)
        new = ast.parse(new_text, type_comments=True)
    except SyntaxError:
        return False
    return ast.dump(_strip_docstrings(old)) == ast.dump(_strip_docstrings(new))


def prose_comment_insertions(old_text, new_text, removed, added):
    """Recognize pure, standalone comment insertions without code or directive edits."""
    if removed or not added:
        return False
    lines = new_text.splitlines(keepends=True)
    if any(not PROSE_COMMENT.fullmatch(lines[i - 1].lstrip(" "))
           or COMMENT_CONTROL.search(lines[i - 1]) for i in added):
        return False
    if "".join(line for i, line in enumerate(lines, 1) if i not in added) != old_text:
        return False
    comments = {t.start[0] for t in tokenize.generate_tokens(io.StringIO(new_text).readline)
                if t.type == tokenize.COMMENT and not t.line[:t.start[1]].strip()}
    if not added <= comments:
        return False
    before, after = (text.encode("utf-8") for text in (old_text, new_text))
    if any(tokenize.detect_encoding(io.BytesIO(text).readline)[0] != "utf-8" for text in (before, after)):
        return False
    return ast.dump(ast.parse(before, type_comments=True)) == ast.dump(ast.parse(after, type_comments=True))


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


_STRIPPED = ("<body>",)


def structure(node):
    """A comparable tuple for one AST node, with every field included.

    Only equality is ever asked of this value, so nested tuples replace the
    string dumps the comparison used to build. Tuples compare with a
    short-circuit and allocate no text.
    """
    fields = []
    for name, value in ast.iter_fields(node):
        if isinstance(value, list):
            fields.append((name, tuple(structure(item) if isinstance(item, ast.AST) else item
                                       for item in value)))
        elif isinstance(value, ast.AST):
            fields.append((name, structure(value)))
        else:
            fields.append((name, value))
    return type(node).__name__, tuple(fields)


def analyze(text):
    tree = ast.parse(text)
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    token_lines = [token.start[0] for token in tokens]
    scopes = {}
    class_shapes = {}
    occurrences = Counter()

    def body_start(node):
        depth = 0
        for index in range(bisect_left(token_lines, node.lineno), len(tokens)):
            token = tokens[index]
            if token.type == tokenize.OP:
                if token.string in "([{":
                    depth += 1
                elif token.string in ")]}":
                    depth -= 1
                elif token.string == ":" and depth == 0:
                    return token.start[0] + 1
        return node.lineno

    def describe(node, parents):
        """Collect scopes and class shapes, returning the stripped structure.

        One pass replaces the previous three: a traversal for scopes, a copy
        and dump per class, and a copy and dump for the module. Function
        bodies are descended into so nested scopes are still recorded, but
        they are omitted from the structure, so a definition nested inside a
        stripped body disappears from it exactly as before.
        """
        key = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            qualified = parents + (node.name,)
            occurrences[qualified] += 1
            count = occurrences[qualified]
            key = qualified if count == 1 else parents + (f"{node.name}#{count}",)
            header = {name: structure(value) if isinstance(value, ast.AST)
                      else tuple(structure(item) if isinstance(item, ast.AST) else item
                                 for item in value) if isinstance(value, list)
                      else value for name, value in ast.iter_fields(node) if name != "body"}
            scopes[key] = {
                "node": node, "header": header, "parents": parents, "end": node.end_lineno,
                "body_start": body_start(node) if not isinstance(node, ast.ClassDef) else node.lineno,
            }
        inner = key if key is not None else parents
        stripped = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        fields = []
        for name, value in ast.iter_fields(node):
            if isinstance(value, list):
                shaped = tuple(describe(item, inner) if isinstance(item, ast.AST) else item
                               for item in value)
                fields.append((name, _STRIPPED if stripped and name == "body" else shaped))
            elif isinstance(value, ast.AST):
                fields.append((name, describe(value, inner)))
            else:
                fields.append((name, value))
        shape = (type(node).__name__, tuple(fields))
        if isinstance(node, ast.ClassDef):
            class_shapes[key] = shape
        return shape

    shape = describe(tree, ())
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


def localized_statement(old, new, affected, removed, added, *, literal_types=None):
    """Match small, single-line edits with an executable old entry point."""
    if len(affected) != 1 or len(removed) != 1 or len(added) > 1:
        return False
    key = next(iter(affected))
    scope = old["scopes"][key]["node"]
    if scope.decorator_list or isinstance(scope, ast.AsyncFunctionDef):
        return False

    def statement(node, line):
        candidates = [item for item in ast.walk(node) if isinstance(item, ast.stmt)
                      and item.lineno == line and item.end_lineno == line]
        return candidates[0] if len(candidates) == 1 else None

    prior = statement(scope, next(iter(removed)))
    if not added:
        # Removing a binding (even a dead assignment) can change name lookup
        # everywhere in a function. Only a standalone pass is accepted here.
        return isinstance(prior, ast.Pass)
    after = statement(new["scopes"][key]["node"], next(iter(added)))
    if type(prior) is not type(after):
        return False
    if isinstance(prior, ast.Assign):
        if (len(prior.targets) != 1 or len(after.targets) != 1
                or not isinstance(prior.targets[0], ast.Name)
                or not isinstance(after.targets[0], ast.Name)
                or prior.targets[0].id != after.targets[0].id):
            return False
    elif not isinstance(prior, ast.Return):
        return False
    return (isinstance(prior.value, ast.Constant) and isinstance(after.value, ast.Constant)
            and type(prior.value.value) is type(after.value.value)
            and (literal_types is None or type(prior.value.value) in literal_types)
            and prior.value.value != after.value.value)
