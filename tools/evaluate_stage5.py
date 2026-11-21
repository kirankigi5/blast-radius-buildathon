#!/usr/bin/env python3
"""Run the Stage 4 checkpoint and current selector on the official sample."""

import json
from pathlib import Path
import shlex
import statistics
import subprocess

import evaluate_stage4 as common

ROOT = common.ROOT
OUT = ROOT / ".local/stage5/sample"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    common.OUT = OUT
    dockerfile = (ROOT / "checkpoints/stage4/Dockerfile").read_text()
    dockerfile = dockerfile.replace("COPY coverage_index /app/coverage_index",
                                    "COPY coverage_index/index.json coverage_index/audit.json coverage_index/provenance.json /app/coverage_index/")
    dockerfile = dockerfile.replace("COPY tools/fetch_base.py", "COPY checkpoints/stage4/fetch_base.py")
    dockerfile = dockerfile.replace("COPY selector.py selection.py patch_analysis.py",
                                    "COPY checkpoints/stage4/selector.py checkpoints/stage4/selection.py checkpoints/stage4/patch_analysis.py")
    common.run("stage4-build", ["docker", "build", "--platform", "linux/amd64", "-t",
                                "blast-radius-stage4", "-f", "-", "."], dockerfile)
    baseline = OUT / "stage4-output.jsonl"
    common.run("stage4-sample", ["make", "-o", "build", "sample", "IMAGE=blast-radius-stage4", f"OUTPUT={baseline}"])
    common.run("make-check", ["make", "check"])
    common.run("make-sample", ["make", "sample"])
    current = OUT / "stage5-output.jsonl"
    current.write_bytes((ROOT / "output.jsonl").read_bytes())
    dry = subprocess.check_output(["make", "-n", "sample"], cwd=ROOT, text=True)
    words = shlex.split(next(line for line in dry.splitlines() if line.startswith("docker run ")))
    flags = words[2:words.index(">") - 1]
    common.run("focused", ["docker", "run", *flags, "--env", "PYTHONDONTWRITEBYTECODE=1",
                          "--volume", f"{ROOT}:/workspace:ro", "--workdir", "/workspace",
                          "blast-radius-entry", "python", "-m", "unittest", "discover", "-s", "tests", "-v"])
    cpu = {}
    for image, expected in (("blast-radius-stage4", baseline), ("blast-radius-entry", current)):
        cpu[image] = []
        for attempt in range(3):
            name = f"cpu-{image}-{attempt}"
            output = common.run(name, ["docker", "run", *flags,
                                     "--volume", f"{ROOT / 'tools/stage4_cpu.py'}:/meter.py:ro",
                                     "--entrypoint", "python", image, "/meter.py"])
            assert output.read_bytes() == expected.read_bytes(), f"Output changed in {name}"
            cpu[image].append(next(row for row in common.diagnostics(OUT / f"{name}.stderr")
                                   if row.get("measurement") == "container_cpu_snapshot"))
    # Load evaluation labels only after the containers have produced all results.
    tests = json.loads((ROOT / "sample/tests.json").read_text())["tests"]
    answers = json.loads((ROOT / "sample/answers.json").read_text())["commits"]
    report = {"cpu": cpu, "median_cpu_seconds": {
        image: statistics.median(row["cgroup_usage_seconds"] for row in runs)
        for image, runs in cpu.items() if all(row["cgroup_usage_seconds"] is not None for row in runs)}}
    for name, path, diagnostics in (("before", baseline, "stage4-sample"), ("after", current, "make-sample")):
        score = common.evaluate_run(path.read_bytes(), tests, answers)
        assert score["ok"], score
        reasons = {row["commit"]: {"fallback": row["fallback"], "reasons": row["reasons"]}
                   for row in common.diagnostics(OUT / f"{diagnostics}.stderr") if "commit" in row}
        score["per_change"] = common.per_change(path, tests, answers, reasons)
        report[name] = score
    (OUT / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    for name in ("before", "after"):
        score = report[name]
        print(name, score["simulated_milliseconds"], len(score["missed_commits"]),
              sum(change["fallback"] for change in score["per_change"]), flush=True)
    print(report["median_cpu_seconds"])


if __name__ == "__main__":
    main()
