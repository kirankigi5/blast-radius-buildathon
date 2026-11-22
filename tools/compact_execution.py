"""Compact a per-test line trace into coverage_index/execution.json.

The raw trace is produced by running sqlglot's tests at eb11aec with
ProcessPoolExecutor replaced by an in-process executor that still pickle-
round-trips each task, so worker lines are credited to the submitting test.
Import and collection lines are stored separately from per-test lines.

    python3 tools/compact_execution.py raw.json coverage_index/index.json coverage_index/execution.json
"""

import hashlib
import json
import sys
from pathlib import Path


def ranges(values):
    grouped = []
    for ordinal in sorted(set(values)):
        if grouped and ordinal == grouped[-1][1] + 1:
            grouped[-1][1] = ordinal
        else:
            grouped.append([ordinal, ordinal])
    return tuple(tuple(pair) for pair in grouped)


def main():
    raw_path, index_path, output_path = map(Path, sys.argv[1:])
    raw = json.loads(raw_path.read_bytes())
    index_bytes = index_path.read_bytes()
    index = json.loads(index_bytes)
    limit = len(index["tests"])
    interned = {}
    order = []

    def set_index(ordinals):
        ordinals = [ordinal for ordinal in ordinals if 0 <= ordinal < limit]
        key = ranges(ordinals)
        if key not in interned:
            interned[key] = len(order)
            order.append([list(pair) for pair in key])
        return interned[key]

    files = {}
    for name, rows in sorted(raw["files"].items()):
        merged = []
        for line, ordinals in rows:
            if not ordinals:
                continue
            index_id = set_index(ordinals)
            if merged and merged[-1][1] + 1 == line and merged[-1][2] == index_id:
                merged[-1][1] = line
            else:
                merged.append([line, line, index_id])
        if merged:
            files[name] = merged
    imports = {}
    for name, lines in sorted(raw.get("import_lines", {}).items()):
        grouped = [list(pair) for pair in ranges(lines)]
        if grouped:
            imports[name] = grouped
    payload = {
        "schema_version": 1,
        "source_revision": index["source_revision"],
        "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
        "test_count": limit,
        "test_sets": order,
        "files": files,
        "import_lines": imports,
    }
    output_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"files={len(files)} sets={len(order)} bytes={output_path.stat().st_size}")


if __name__ == "__main__":
    main()
