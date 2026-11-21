#!/usr/bin/env python3
"""Reproduce Stage 4 checks and evaluate labels only after selector execution."""

import hashlib
import json
import math
from pathlib import Path
import shlex
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from score import evaluate_run

OUT = ROOT / ".local/stage4"


def run(name, command, input_text=None):
    start = time.perf_counter()
    with (OUT / f"{name}.stdout").open("w") as stdout, (OUT / f"{name}.stderr").open("w") as stderr:
        result = subprocess.run(command, cwd=ROOT, input=input_text, text=True, stdout=stdout, stderr=stderr)
    record = {"command": command, "wall_seconds": time.perf_counter() - start, "exit_code": result.returncode}
    timings[name] = record
    (OUT / "evaluation-timings.json").write_text(json.dumps(timings, indent=2) + "\n")
    if result.returncode:
        raise RuntimeError(f"{name} failed: see {OUT / (name + '.stderr')}")
    print(name, f"{record['wall_seconds']:.3f}s", flush=True)
    return OUT / f"{name}.stdout"


def diagnostics(path):
    result = []
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def per_change(stdout, tests, answers, reasons):
    durations = {t["number"]: math.floor(t["seconds"] * 1000 + 0.5) for t in tests}
    rows = []
    for line in stdout.read_text().splitlines():
        row = json.loads(line)
        workers = [worker for worker in row["workers"] if worker]
        selected = {n for worker in workers for n in worker}
        missed = set(answers[row["commit"]]["failing"]) - selected
        cost = max((sum(durations[n] for n in worker) for worker in workers), default=0) + 2000 * len(workers)
        rows.append({"commit": row["commit"], "selected_tests": len(selected), "workers": len(workers),
                     "test_worker_milliseconds": cost, "missed_test_count": len(missed),
                     "penalty_milliseconds": 300000 if missed else 0,
                     **reasons.get(row["commit"], {})})
    return rows


timings = {}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    context = subprocess.check_output(["docker", "context", "show"], text=True).strip()
    engine = subprocess.check_output(["docker", "info", "--format", "{{.OperatingSystem}}"], text=True).strip()
    assert engine == "Docker Desktop", (context, engine)
    # Exact checkpoint bytes are independently hashed; source is not modified.
    assert hashlib.sha256((ROOT / "checkpoints/selector_stage2.py").read_bytes()).hexdigest() == "61183dc6d4cbdbbc9267d2c3b386e27e8fc8b73732d2e0e4382d51d2a10d0b7e"
    dockerfile = """FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
COPY checkpoints/selector_stage2.py /app/selector.py
CMD ["python", "/app/selector.py"]
"""
    run("stage2-build", ["docker", "build", "--platform", "linux/amd64", "-t", "blast-radius-stage2", "-f", "-", "."], dockerfile)
    baseline_output = OUT / "stage2-output.jsonl"
    run("stage2-sample", ["make", "-o", "build", "sample", "IMAGE=blast-radius-stage2", f"OUTPUT={baseline_output}"])
    run("make-check", ["make", "check"])
    run("make-sample", ["make", "sample"])
    current_output = OUT / "stage4-output.jsonl"
    current_output.write_bytes((ROOT / "output.jsonl").read_bytes())
    dry = subprocess.check_output(["make", "-n", "sample"], cwd=ROOT, text=True)
    docker_run = next(line for line in dry.splitlines() if line.startswith("docker run "))
    words = shlex.split(docker_run)
    flags = words[2:words.index(">") - 1]
    run("focused", ["docker", "run"] + flags + ["--env", "PYTHONDONTWRITEBYTECODE=1",
                    "--volume", f"{ROOT}:/workspace:ro", "--workdir", "/workspace",
                    "blast-radius-entry", "python", "-m", "unittest", "discover", "-s", "tests", "-v"])
    cpu = {}
    for image in ("blast-radius-stage2", "blast-radius-entry"):
        values = []
        for attempt in range(3):
            name = f"cpu-{image}-{attempt}"
            output = run(name, ["docker", "run"] + flags + ["--volume", f"{ROOT / 'tools/stage4_cpu.py'}:/meter.py:ro",
                        "--entrypoint", "python", image, "/meter.py"])
            expected = baseline_output if image == "blast-radius-stage2" else current_output
            assert output.read_bytes() == expected.read_bytes(), f"Nondeterministic output in {name}"
            record = next(row for row in diagnostics(OUT / f"{name}.stderr") if row.get("measurement") == "container_cpu_snapshot")
            values.append(record)
        cpu[image] = values
    # Labels are read here only, after all protocol outputs have been generated.
    tests = json.loads((ROOT / "sample/tests.json").read_text())["tests"]
    answers = json.loads((ROOT / "sample/answers.json").read_text())["commits"]
    before = evaluate_run(baseline_output.read_bytes(), tests, answers)
    after = evaluate_run(current_output.read_bytes(), tests, answers)
    assert before["ok"] and after["ok"], (before, after)
    reasons = {row["commit"]: {"fallback": row["fallback"], "reasons": row["reasons"]}
               for row in diagnostics(OUT / "make-sample.stderr") if "commit" in row}
    rows = per_change(current_output, tests, answers, reasons)
    report = {"context": context, "engine": engine, "before": before, "after": after,
              "improvement_percent": (before["simulated_milliseconds"] - after["simulated_milliseconds"]) / before["simulated_milliseconds"] * 100,
              "per_change": rows, "cpu": cpu,
              "fallback_count": sum(row["fallback"] for row in rows),
              "median_local_cgroup_cpu_seconds": {image: statistics.median(row["cgroup_usage_seconds"] for row in values)
                                                  for image, values in cpu.items()
                                                  if all(row["cgroup_usage_seconds"] is not None for row in values)}}
    (OUT / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("per_change", "cpu")}, indent=2))


if __name__ == "__main__":
    main()
