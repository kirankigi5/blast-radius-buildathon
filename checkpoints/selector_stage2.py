"""Select every test; minimize greedy scheduling cost across 1–8 workers."""

import json
import math
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

DATA = Path("/data")
WORKERS = 3


def split(tests: list[dict], worker_count: int) -> list[list[int]]:
    """Original starter partition, preserved as a scheduling candidate."""
    workers: list[list[int]] = [[] for _ in range(worker_count)]
    loads = [0.0] * worker_count
    for test in sorted(tests, key=lambda test: test["seconds"], reverse=True):
        lightest = loads.index(min(loads))
        workers[lightest].append(test["number"])
        loads[lightest] += test["seconds"]
    return workers


def _partition_cost_ms(
    workers: list[list[int]], durations_ms: Mapping[int, int]
) -> int:
    """Official busiest-worker load plus 2000 ms per nonempty worker."""
    loads = [sum(durations_ms[number] for number in worker) for worker in workers if worker]
    return max(loads, default=0) + 2000 * len(loads)


def schedule(
    selected_test_ids: Iterable[int], seconds_by_test: Mapping[int, float]
) -> list[list[int]]:
    """Schedule numbered tests using recorded seconds, without selecting tests.

    Test IDs here are the integer `number` fields, not pytest node-ID strings.
    Input order does not affect the result. Duration ties use test number;
    worker-load ties use worker index. Equal-cost partitions prefer fewer
    occupied workers, then the lexicographically smallest worker lists.

    The starter candidate uses canonical test-number order, which is the
    official tests.json order, including its original floating-point loads.
    All candidate costs and new greedy loads use the scorer's integer ms.
    """
    selected = list(selected_test_ids)
    if any(not isinstance(number, int) or isinstance(number, bool) for number in selected):
        raise ValueError("selected test IDs must be integers")
    if len(selected) != len(set(selected)):
        raise ValueError("selected test IDs must be unique")
    if any(number not in seconds_by_test for number in selected):
        raise ValueError("unknown selected test ID")
    if not selected:
        return []

    selected.sort()
    seconds = {number: seconds_by_test[number] for number in selected}
    if any(not math.isfinite(value) or value < 0 for value in seconds.values()):
        raise ValueError("recorded durations must be finite and nonnegative")
    durations_ms = {
        number: math.floor(value * 1000 + 0.5) for number, value in seconds.items()
    }
    ordered = sorted(selected, key=lambda number: (-seconds[number], number))
    starter_tests = [
        {"number": number, "seconds": seconds[number]} for number in selected
    ]
    candidates = [[worker for worker in split(starter_tests, WORKERS) if worker]]

    for worker_count in range(1, min(8, len(selected)) + 1):
        workers: list[list[int]] = [[] for _ in range(worker_count)]
        loads = [0] * worker_count
        for number in ordered:
            lightest = loads.index(min(loads))
            workers[lightest].append(number)
            loads[lightest] += durations_ms[number]
        candidates.append([worker for worker in workers if worker])

    return min(
        candidates,
        key=lambda workers: (_partition_cost_ms(workers, durations_ms), len(workers), workers),
    )


def main() -> None:
    tests = json.loads((DATA / "tests.json").read_text())["tests"]
    # Every change selects the same complete test set: schedule only once.
    workers = schedule(
        [test["number"] for test in tests],
        {test["number"]: test["seconds"] for test in tests},
    )
    for patch in sorted((DATA / "commits").glob("*.patch")):
        print(json.dumps({"commit": patch.stem, "workers": workers}))
    print(
        f"selected {len(tests)} tests on every commit across {len(workers)} workers",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
