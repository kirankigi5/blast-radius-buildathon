#!/usr/bin/env python3
"""Reproduce offline maps without mounting sample patches or failure labels."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

REVISION = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
ROOT = Path(__file__).resolve().parents[2]
PILOTS = [
    "tests/test_parser.py::TestParser::test_union",
    "tests/test_executor.py::TestExecutor::test_array_slice",
    "tests/test_optimizer.py::TestOptimizer::test_aggfunc_annotation",
    "tests/test_executor.py::TestExecutor::test_execute_tpch",
]


def command(args, log=None, cwd=ROOT):
    start = time.perf_counter()
    if log:
        with log.open("w") as stream:
            result = subprocess.run(args, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    else:
        result = subprocess.run(args, cwd=cwd)
    if result.returncode:
        raise RuntimeError(f"command exited {result.returncode}: {args}; log: {log}")
    return time.perf_counter() - start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, default=ROOT / ".local/coverage")
    parser.add_argument("--platform", default="linux/amd64")
    parser.add_argument("--steps", default="collect,pilot,full,export")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    start = time.perf_counter()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = work / "sqlglot"
    if not (source / ".git").exists():
        command(["git", "init", str(source)])
        command(["git", "-C", str(source), "remote", "add", "origin", "https://github.com/tobymao/sqlglot.git"])
        command(["git", "-C", str(source), "fetch", "--depth", "1", "origin", REVISION])
        command(["git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD"])
    assert subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() == REVISION
    assert not subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"])
    steps = args.steps.split(",")
    assert set(steps) <= {"collect", "pilot", "full", "export"}
    image = "blast-radius-coverage"
    build_seconds = command(["docker", "build", "--platform", args.platform, "-f",
                             "tools/coverage/Dockerfile", "-t", image, "."], work / "build.log")
    raw = work / "raw"
    raw.mkdir(exist_ok=True)
    artifacts = ROOT / "coverage_index"
    artifacts.mkdir(exist_ok=True)
    docker = ["docker", "run", "--rm", "--platform", args.platform, "--network", "none",
              "--cpus", "4", "--memory", "6g", "--pids-limit", "256", "--read-only",
              "--tmpfs", "/tmp:rw,size=512m", "--env", "PYTHONHASHSEED=0",
              "--env", "OPENBLAS_NUM_THREADS=1", "--env", "OMP_NUM_THREADS=1",
              "--env", "MKL_NUM_THREADS=1",
              "--volume", f"{source}:/src:ro", "--volume", f"{ROOT / 'tools/coverage'}:/tool:ro",
              "--volume", f"{ROOT / 'sample/tests.json'}:/manifest/tests.json:ro",
              "--volume", f"{raw}:/raw", "--volume", f"{artifacts}:/artifacts"]
    timings = {}

    def run(mode, name, node=None):
        if args.resume and (raw / name / "run.json").exists():
            expected = hashlib.sha256((ROOT / "sample/tests.json").read_bytes()).hexdigest()
            environment = json.loads((raw / name / "environment.json").read_text())
            assert environment["manifest_sha256"] == expected
            for filename in ("generate.py", "pytest_contexts.py"):
                assert environment["tool_sha256"][filename] == hashlib.sha256((ROOT / "tools/coverage" / filename).read_bytes()).hexdigest(), "Tool changed; regenerate raw traces in a fresh work directory"
            print(f"Using completed run {name}", flush=True)
            return
        tail = ["--mode", mode, "--name", name]
        if node:
            tail += ["--node", node]
        timings[name] = command(docker + [image] + tail, work / f"{name}.log")
        (work / "completed-command-timings.json").write_text(json.dumps(timings, indent=2) + "\n")
        print(f"Completed {name}: {timings[name]:.3f}s", flush=True)

    command(docker + ["--entrypoint", "python", image, "-m", "unittest", "discover",
                      "-s", "/tool", "-p", "test_tools.py", "-v"], work / "tool-checks.log")
    if "collect" in steps:
        run("collect", "collect")
    if "pilot" in steps:
        for i, node in enumerate(PILOTS):
            run("pilot", f"pilot-{i}", node)
        # Infrastructure/context attribution must pass before a full run.
        command(docker + ["--entrypoint", "python", image, "/tool/export.py", "--pilot-only"],
                work / "pilot-audit.log")
        print((work / "pilot-audit.log").read_text(), flush=True)
    if "full" in steps:
        assert (raw / "pilot-audit.json").exists(), "Complete and audit the pilot before full coverage"
        run("full", "full")
    if "export" in steps:
        timings["export"] = command(docker + ["--entrypoint", "python", image, "/tool/export.py"],
                                   work / "export.log")
        print((work / "export.log").read_text(), flush=True)
        timings["verify"] = command(docker + ["--entrypoint", "python", image, "/tool/verify.py"],
                                   work / "verify.log")
        print((work / "verify.log").read_text(), flush=True)
    assert not subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"])
    record = {"command": ["python3", "tools/coverage/run.py"] + os.sys.argv[1:],
              "source_revision": REVISION, "source_tree": subprocess.check_output(
                  ["git", "-C", str(source), "rev-parse", "HEAD^{tree}"], text=True).strip(),
              "platform": args.platform, "build_wall_seconds": build_seconds,
              "command_wall_seconds": timings, "invocation_wall_seconds": time.perf_counter() - start}
    (work / f"timing-{'-'.join(steps)}.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2), flush=True)


if __name__ == "__main__":
    main()
