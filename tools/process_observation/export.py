"""Validate clean child traces and export an offline pool-versus-task audit."""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from selection import REVISION, decode_set, members


def test_owners(context, ordinals, fixtures):
    kind, separator, detail = context.partition("|")
    if separator and kind == "test":
        test, _ = detail.rsplit("|", 1)
        return {ordinals[test]} if test in ordinals else set()
    if separator and kind == "fixture":
        fixture, _ = detail.rsplit("|", 1)
        return {ordinals[test] for test in fixtures.get(fixture, ()) if test in ordinals}
    return set()


def load_children(directory, topology):
    children = {}
    if list(directory.glob("*.partial")):
        raise ValueError("partial child archive")
    for path in sorted(directory.glob("child-*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            child = json.load(stream)
        pid = child["pid"]
        if pid in children or path.name != f"child-{pid}.json.gz":
            raise ValueError("ambiguous child trace identity")
        children[pid] = child
    workers = [pid for pool in topology["pools"] for pid in pool["workers"]]
    external = [pid for pid, _ in topology["subprocesses"]]
    expected = [*workers, *external]
    tracker = topology["resource_tracker"]
    if tracker is not None:
        expected.append(tracker)
    if len(expected) != len(set(expected)) or set(expected) != children.keys():
        raise ValueError(f"child roster mismatch: missing={set(expected) - children.keys()}, "
                         f"unexpected={children.keys() - set(expected)}")
    if Counter(topology["started_children"]) != Counter(workers):
        raise ValueError("untracked multiprocessing child")
    launches = Counter(topology["launches"])
    if (launches.pop("subprocess.Popen", 0) != len(external)
            or launches.pop("os.posix_spawn", 0) > len(external) or launches):
        raise ValueError(f"untracked parent launch: {launches}")
    for pid, child in children.items():
        if child["launches"] or child["active_at_exit"] is not None:
            raise ValueError(f"interrupted task or untracked child launch in {pid}")
        if child["resource_tracker"] != (pid == tracker):
            raise ValueError("ambiguous resource-tracker identity")
        if pid == tracker and (child["coverage"] or child["started"] or child["pool"] is not None):
            raise ValueError("resource tracker executed relevant code")
        if pid in external and (child["pool"] is not None or child["started"] or child["ended"]):
            raise ValueError("opaque subprocess has unexpected pool events")
    return children, external


def pool_owners(pool, children, ordinals, fixtures):
    expected = {task[0] for task in pool["tasks"]}
    if expected != set(range(len(pool["tasks"]))) or not expected:
        raise ValueError("invalid submission sequence")
    contexts = {pool["created"], *(task[1] for task in pool["tasks"])}
    owners = set()
    for context in contexts:
        tests = test_owners(context, ordinals, fixtures)
        if not tests:
            raise ValueError(f"unowned submission or pool creation: {context}")
        owners.update(tests)
    seen = Counter()
    for pid in pool["workers"]:
        child = children[pid]
        if child["pool"] != pool["id"]:
            raise ValueError("worker joined a different pool")
        task_coverage = {int(key[5:]) for key in child["coverage"] if key.startswith("task:")}
        if (child["ended"] != [[t, "result"] for t in child["started"]]
                or task_coverage != set(child["started"])):
            raise ValueError("worker task is missing its entry, successful exit, or coverage")
        seen.update(child["started"])
    if seen != Counter(expected):
        raise ValueError("not every submitted work ID ran exactly once")
    return sorted(owners)


def aggregate(coverage, indexed_paths):
    tasks, others, virtual = defaultdict(int), defaultdict(int), set()
    for phase, observed in coverage.items():
        target = tasks if phase.startswith("task:") else others
        for file, lines in observed.items():
            if file not in indexed_paths:
                virtual.add(file)
                continue
            target[file] |= int(lines, 16)
    return tasks, others, virtual


def index_coverage(index, children):
    pool_masks = defaultdict(lambda: defaultdict(int))
    outside = defaultdict(int)
    opaque = defaultdict(int)
    virtual = set()
    phases = Counter()
    for child in children.values():
        tasks, others, unseen_paths = aggregate(child["coverage"], index["files"])
        if child["background_threads"]:
            # The C tracer switches shared contexts across threads. None of a
            # multithreaded worker's observations can support task isolation.
            for file, bits in tasks.items():
                others[file] |= bits
        virtual.update(unseen_paths)
        for key in child["coverage"]:
            phases["task" if key.startswith("task:") else key] += 1
        if child["pool"] is None:
            for file, bits in others.items():
                opaque[file] |= bits
            continue
        for file in tasks.keys() | others.keys():
            outside[file] |= others[file]
            for line in members(tasks[file] | others[file]):
                pool_masks[file][line] |= 1 << child["pool"]
    process = next(i for i, ctx in enumerate(index["shared_contexts"]) if ctx["id"] == "shared:process")
    shared = [decode_set(bits) for bits in index["shared_sets"]]
    output = {}
    counts = Counter()
    for file, record in index["files"].items():
        rows = []
        for start, stop, test_set, context_set in record["lines"]:
            if not shared[context_set] & (1 << process):
                continue
            for line in range(start, stop + 1):
                mask = pool_masks[file].get(line, 0)
                if not mask or opaque[file] & (1 << line):
                    mask = 0
                out_of_task = bool(outside[file] & (1 << line))
                counts["legacy"] += 1
                counts["mapped" if mask else "coarse"] += 1
                counts["outside_task"] += bool(mask and out_of_task)
                if rows and rows[-1][1] == line - 1 and rows[-1][2:] == [mask, out_of_task]:
                    rows[-1][1] = line
                else:
                    rows.append([line, line, mask, out_of_task])
        if rows:
            output[file] = rows
    return output, phases, counts, len(virtual)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("index", type=Path)
    ap.add_argument("manifest", type=Path)
    ap.add_argument("trace", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    assert subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip() == REVISION
    assert not subprocess.check_output(["git", "-C", str(args.source), "status", "--porcelain", "--untracked-files=all"])
    raw = args.index.read_bytes()
    index = json.loads(raw)
    assert index["source_revision"] == REVISION
    for file, entry in index["files"].items():
        assert sha((args.source / file).read_bytes()) == entry["sha256"]
    provenance = json.loads(args.index.with_name("provenance.json").read_bytes())
    resources = args.index.with_name("resources.json").read_bytes()
    assert sha(raw) == provenance["index_sha256"]
    assert sha(args.manifest.read_bytes()) == provenance["manifest_sha256"]
    manifest = json.loads(args.manifest.read_bytes())
    report = json.loads((args.trace / "completeness.json").read_bytes())
    pytest = json.loads((args.trace / "pytest.json").read_bytes())
    assert report["complete"] and not report["failing_ids"] and pytest["exit_code"] == 0
    ordinals = {t["id"]: i for i, t in enumerate(index["tests"])}
    assert ordinals.keys() == {t["id"] for t in manifest["tests"]}
    assert len(ordinals) == report["numbered_count"] == len(manifest["tests"])
    topology = json.loads((args.trace / "topology.json").read_bytes())
    children, external = load_children(args.trace, topology)
    pools = topology["pools"]
    assert [p["id"] for p in pools] == list(range(len(pools)))
    owners = [pool_owners(p, children, ordinals, pytest["fixture_users"]) for p in pools]
    paths, phases, counts, virtual = index_coverage(index, children)
    artifact = {"schema_version": 1, "source_revision": REVISION, "index_sha256": sha(raw),
                "manifest_sha256": provenance["manifest_sha256"],
                "resources_sha256": sha(resources),
                "tool_sha256": {p.name: sha(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("*.py"))},
                "pool_tests": owners, "paths": paths, "counts": counts,
                "corpus": {"numbered_tests": len(ordinals), "children": len(children),
                           "subprocesses": len(external), "tasks": [len(p["tasks"]) for p in pools],
                           "phases": phases, "unbacked_paths": virtual,
                           "workers_with_background_threads": sum(bool(c["background_threads"]) for c in children.values())}}
    args.output.write_text(json.dumps(artifact, sort_keys=True, separators=(",", ":")) + "\n")
    for pool, tests in zip(pools, owners):
        print(f"pool {pool['id']}: {len(tests)} owners, {len(pool['tasks'])} tasks, "
              f"{len(pool['workers'])} workers, initializer={pool['initializer']}")
    print(artifact["corpus"], dict(counts))


if __name__ == "__main__":
    main()
