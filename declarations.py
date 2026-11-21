"""Recognize declaration edits whose binding and initialization shape stay fixed."""

from __future__ import annotations

import ast
import copy


def scalar(node):
    if isinstance(node, ast.Constant) and type(node.value) in (bool, int, float, str):
        return type(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        kind = scalar(node.operand)
        if kind in (int, float):
            return kind
    return None


def bindings(tree):
    """Yield qualified assignments and named, deferred dictionary lambdas."""
    def visit(body, prefix):
        for statement in body:
            if isinstance(statement, ast.ClassDef):
                yield from visit(statement.body, (*prefix, statement.name))
                continue
            if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
                target = statement.targets[0]
            elif isinstance(statement, ast.AnnAssign):
                target = statement.target
            else:
                continue
            if not isinstance(target, ast.Name) or statement.value is None:
                continue
            value = statement.value
            qualified = ".".join((*prefix, target.id))
            if target.id.isupper() and scalar(value):
                kind = "class_scalar" if prefix else "module_scalar"
                yield qualified, kind, value
            if prefix and target.id.isupper() and isinstance(value, ast.Dict):
                for key, entry in zip(value.keys, value.values):
                    if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                            and isinstance(entry, ast.Lambda)
                            and not entry.args.defaults and not any(entry.args.kw_defaults)):
                        yield f"{qualified}[{key.value!r}]", "deferred_lambda", entry
    yield from visit(tree.body, ())


def _normalize(tree):
    normalized = copy.deepcopy(tree)
    entries = list(bindings(normalized))
    for _, kind, node in entries:
        if kind == "deferred_lambda":
            for item in ast.walk(node.body):
                if scalar(item) and isinstance(item, ast.Constant):
                    item.value = (type(item.value).__name__,)
        elif isinstance(node, ast.UnaryOp):
            node.operand = ast.Constant(value=(scalar(node).__name__,))
        else:
            node.value = (scalar(node).__name__,)
    return ast.dump(normalized, include_attributes=False)


def _mask(text, nodes):
    """Mask exact token spans, preserving whitespace, comments, and other edits."""
    lines = text.encode().splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    spans = [(offsets[n.lineno - 1] + n.col_offset, offsets[n.end_lineno - 1] + n.end_col_offset)
             for n in nodes]
    data = text.encode()
    for start, stop in sorted(spans, reverse=True):
        data = data[:start] + b"\0" + data[stop:]
    return data


def changed_bindings(old_text, new_text, old_tree, new_tree):
    before = list(bindings(old_tree))
    after = list(bindings(new_tree))
    keys = [(key, kind) for key, kind, _ in before]
    if keys != [(key, kind) for key, kind, _ in after] or len(keys) != len(set(keys)):
        return []
    if _normalize(old_tree) != _normalize(new_tree):
        return []
    changed = []
    masks = ([], [])
    for (key, kind, prev), (_, _, new) in zip(before, after):
        if ast.dump(prev) == ast.dump(new):
            continue
        if kind == "deferred_lambda":
            pairs = [(a, b) for a, b in zip(ast.walk(prev.body), ast.walk(new.body))
                     if isinstance(a, ast.Constant) and isinstance(b, ast.Constant)
                     and scalar(a) and a.value != b.value]
            # The lambda's declaration line can be recorded during import.
            if not pairs or any(a.lineno <= prev.lineno or b.lineno <= new.lineno for a, b in pairs):
                return []
            left, right = zip(*pairs)
        else:
            left, right = (prev,), (new,)
        masks[0].extend(left)
        masks[1].extend(right)
        changed.append((key, kind))
    if not changed or _mask(old_text, masks[0]) != _mask(new_text, masks[1]):
        return []
    return changed
