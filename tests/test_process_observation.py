"""Checks for complete task accounting and shared pool ownership."""

from pathlib import Path
import tempfile
import unittest

from tools.process_observation.export import load_children, pool_owners


class ProcessAuditTests(unittest.TestCase):
    def test_reused_worker_keeps_every_submitter_and_initialization_consumer(self):
        pool = {"id": 0, "created": "fixture|setup|setup", "workers": [42],
                "tasks": [[0, "test|first|call", "module", "task"],
                          [1, "test|second|call", "module", "task"]]}
        child = {"pool": 0, "started": [0, 1], "ended": [[0, "result"], [1, "result"]],
                 "coverage": {"task:0": {"one.py": "1"}, "task:1": {"two.py": "2"}}}
        ordinals = {"first": 0, "second": 1, "setup_consumer": 2}
        args = pool, {42: child}, ordinals, {"setup": ["setup_consumer"]}
        self.assertEqual(pool_owners(*args), [0, 1, 2])
        child["started"].pop()
        child["ended"].pop()
        child["coverage"].pop("task:1")
        with self.assertRaisesRegex(ValueError, "not every submitted work ID"):
            pool_owners(*args)

    def test_absent_child_archive_invalidates_the_run(self):
        topology = {"pools": [{"workers": [42]}], "subprocesses": [], "resource_tracker": None,
                    "started_children": [42], "launches": []}
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "child roster mismatch"):
                load_children(Path(temporary), topology)


if __name__ == "__main__":
    unittest.main()
