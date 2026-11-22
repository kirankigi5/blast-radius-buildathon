"""Compact a class-attribute reader trace into coverage_index/readers.json.

    python3 tools/compact_readers.py raw.json coverage_index/index.json coverage_index/readers.json
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
        key = ranges(ordinal for ordinal in ordinals if 0 <= ordinal < limit)
        if key not in interned:
            interned[key] = len(order)
            order.append([list(pair) for pair in key])
        return interned[key]

    readers = {}
    for section in ("inst", "missing"):
        for name, ordinals in raw.get(section, {}).items():
            if ordinals:
                readers[name] = set_index(ordinals)
    payload = {
        "schema_version": 1,
        "source_revision": index["source_revision"],
        "index_sha256": hashlib.sha256(index_bytes).hexdigest(),
        "test_count": limit,
        "test_sets": order,
        "readers": readers,
    }
    output_path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"keys={len(readers)} sets={len(order)} bytes={output_path.stat().st_size}")


if __name__ == "__main__":
    main()
