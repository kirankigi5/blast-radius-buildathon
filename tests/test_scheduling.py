"""Scheduling checks use synthetic durations and the untouched official scorer."""

import json
import random
import unittest

from checkpoints.selector_stage1 import split as starter_split
from score import evaluate_run
from selector import _partition_cost_ms, schedule


class SchedulingTests(unittest.TestCase):
    def official_cost(self, workers, seconds):
        tests = [{"number": number, "seconds": value} for number, value in seconds.items()]
        output = json.dumps({"commit": "synthetic", "workers": workers}).encode("utf-8")
        result = evaluate_run(output, tests, {"synthetic": {"failing": []}})
        self.assertTrue(result["ok"], result)
        return result["simulated_milliseconds"]

    def assert_schedule(self, selected, seconds):
        workers = schedule(selected, seconds)
        flattened = [number for worker in workers for number in worker]
        self.assertCountEqual(flattened, selected)
        self.assertEqual(len(flattened), len(set(flattened)))
        self.assertTrue(set(flattened) <= set(seconds))
        self.assertLessEqual(len(workers), 8)
        self.assertTrue(all(workers))
        cost = self.official_cost(workers, seconds)
        starter = starter_split(
            [{"number": n, "seconds": seconds[n]} for n in sorted(selected)], 3
        )
        self.assertLessEqual(cost, self.official_cost(starter, seconds))
        self.assertEqual(workers, schedule(selected, seconds))
        self.assertEqual(workers, schedule(reversed(selected), dict(reversed(list(seconds.items())))))
        return workers

    def test_empty(self):
        self.assertEqual(self.assert_schedule([], {7: 4.0}), [])

    def test_single(self):
        self.assertEqual(self.assert_schedule([7], {7: 12.345}), [[7]])

    def test_balanced_and_cost_tie(self):
        seconds = {n: 4.0 for n in range(4)}
        workers = self.assert_schedule(list(seconds), seconds)
        # Two and four workers both cost 12 s: prefer fewer workers.
        self.assertEqual(workers, [[0, 2], [1, 3]])
        self.assertEqual(self.official_cost(workers, seconds), 12000)

    def test_eight_workers(self):
        seconds = {n: 10.0 for n in range(8)}
        workers = self.assert_schedule(list(seconds), seconds)
        self.assertEqual(workers, [[n] for n in range(8)])

    def test_uneven_and_subset(self):
        seconds = {0: 9.0, 1: 2.0, 2: 1.0, 3: 0.001, 99: 100.0}
        workers = self.assert_schedule([3, 1, 0, 2], seconds)
        self.assertEqual(workers, [[0], [1, 2, 3]])
        self.assertEqual(self.official_cost(workers, seconds), 13000)

    def test_zero_duration(self):
        self.assertEqual(self.assert_schedule([8, 2, 4], {2: 0.0, 4: 0.0, 8: 0.0}), [[2, 4, 8]])

    def test_millisecond_rounding_matches_scorer(self):
        seconds = {0: 0.0005, 1: 0.0015, 2: 1.2345}
        durations_ms = {0: 1, 1: 2, 2: 1235}
        for workers in ([], [[0, 1, 2]], [[0, 1], [], [2]]):
            self.assertEqual(_partition_cost_ms(workers, durations_ms), self.official_cost(workers, seconds))

    def test_reject_unknown_duplicate_and_noninteger_ids(self):
        for selected in ([99], [0, 0], [True], ["0"]):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                schedule(selected, {0: 1.0})

    def test_reject_invalid_durations(self):
        for value in (-1.0, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                schedule([0], {0: value})

    def test_varied_inputs_and_original_candidate(self):
        rng = random.Random(2026)
        for count in (1, 2, 3, 7, 8, 9, 31, 100):
            for _ in range(8):
                seconds = {n: rng.randrange(0, 60000) / 1000 for n in range(count)}
                selected = list(seconds)
                rng.shuffle(selected)
                with self.subTest(count=count):
                    self.assert_schedule(selected, seconds)


if __name__ == "__main__":
    unittest.main()
