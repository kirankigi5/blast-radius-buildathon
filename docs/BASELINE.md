# Unmodified official baseline — Stage 1

Measured locally on November 21, 2026, in `/Users/kiri/Desktop/hackathon`. The following sections record the original Stage 1 run; the Stage 2 scheduling experiment is appended below. Stage 1 made no selector optimization, dependency map, source checkout, or leaderboard submission.

## Setup and provenance

Read all applicable ancestor locations (`/AGENTS.md`, `/Users/AGENTS.md`, `/Users/kiri/AGENTS.md`, `/Users/kiri/Desktop/AGENTS.md`) and the workspace; none contained an applicable AGENTS.md. The workspace was empty and had no `.git` directory. `git init` initialized it in place; existing system/global Git configuration was left untouched. No nested project directory was created.

Downloaded the [official track page](https://www.joinbuilders.org/buildathon/tracks/blast-radius), followed its [starter archive link](https://www.joinbuilders.org/buildathon/tracks/blast-radius/files/blast-radius-sample.tar.gz) and [SCORING.md download link](https://www.joinbuilders.org/buildathon/tracks/blast-radius/files/SCORING.md) using `curl -fL` (with retries), inspected the archive listing, and extracted it directly into the empty workspace. There is no enclosing archive directory. Read README, scoring rules, Dockerfile, Makefile, requirements lock, complete selector/scorer, and sample schemas before adding any files.

| Published artifact | SHA-256 |
| --- | --- |
| blast-radius-sample.tar.gz | `81efabbc69c3c4367d928f2dba0f33ce9dccccbd080b54721b2636e5d8afab9d` |
| SCORING.md | `26a9941ca2980d8da00bea00910a29703efac95ec79e30a15ab3482e3a9c0903` |

Every extracted regular file was compared byte-for-byte with its archive member. The separately downloaded SCORING.md matches the extracted copy. The full requested sqlglot pin was verified in the retrieved track HTML and README. All original starter files, samples, and scorer remain unchanged.

## Environment and commands

| Component | Observed |
| --- | --- |
| Host | macOS 26.6.2, build 25G83; Darwin 25.6.0; arm64 Apple Silicon |
| Host Python | `/usr/bin/python3`, Python 3.9.6; satisfies documented >=3.9 requirement |
| Make | `/usr/bin/make`, GNU Make 3.81; universal ARM/x86 executable (its version banner says i386-apple-darwin11.3.0) |
| Docker client | 29.4.0, darwin/arm64; context desktop-linux |
| Docker daemon | Running; Docker Desktop 4.90.0, Engine 29.7.2, linux/arm64 (aarch64), 10 CPUs, 7.748 GiB reported memory |
| Execution platform | Official Makefile explicitly uses linux/amd64 for both build and run; therefore amd64 emulation on the ARM64 host. Host Rosetta translation flag was 0; the container emulation backend was not independently identified. |
| Baseline image | `blast-radius-entry:latest`, linux/amd64; initial image ID `sha256:7073bec6be6fa18f45db9760891953b87950965805fdcfafaaf26e7c0a62f54a` (later format-check rebuild regenerated image attestations) |
| Container Python | 3.13.18; platform.machine() returned x86_64 |

Availability/daemon checks actually run: `command -v python3 make docker colima brew`, `python3 --version`, `make --version`, `docker version`, `docker info`, `uname -a`, `uname -m`, `sw_vers`, `sysctl -in sysctl.proc_translated`, and `file /usr/bin/make`. Colima was absent and unnecessary. `docker image inspect` verified linux/amd64; a separate no-network `docker run --rm --platform linux/amd64 blast-radius-entry python -c ...` queried Python/platform (the actual command also included `--network none`). No system configuration changes or environment repairs were needed.

The exact baseline command was:

```sh
make sample
```

It ran without Make/environment overrides, before adding .gitignore, .dockerignore, or docs. A host Python wrapper called `subprocess.run(['make', 'sample'], stdout=log, stderr=subprocess.STDOUT)` and measured `time.perf_counter()` immediately before/after that subprocess. This measures the full build + Docker run + host scorer, not container-only wall or CPU time. Exit code: **0**. The fresh image pulled its base layers; Docker build output reported 3.6 seconds for the base-image step. This was not a controlled server-equivalent cold build benchmark.

The Makefile expanded to the official `docker build --platform linux/amd64 --tag blast-radius-entry .`, the Docker run with RUN_FLAGS documented in RULES_NOTES.md, and:

```sh
python3 score.py /Users/kiri/Desktop/hackathon/sample \
  /Users/kiri/Desktop/hackathon/sample/answers.json \
  /Users/kiri/Desktop/hackathon/output.jsonl
```

## Local results

| Measurement | Result |
| --- | --- |
| Independent sample changes | 30; patch IDs exactly match answer keys |
| Available tests | 1,620, numbered 0–1,619, across 58 files; 1 additional skipped test entry |
| Selection | Every available test for every change; original longest-first greedy split over 3 workers |
| Worker test counts | 500 / 510 / 610 |
| Recorded test load per worker per change | 34.349 / 34.349 / 34.349 s |
| Total recorded duration of all available tests | 103.047 s |
| Batch busiest-worker testing cost | 1,030.470 s = 30 × 34.349 s |
| Batch worker overhead | 180.000 s = 30 × 3 × 2 s |
| Missed-change count | **0** |
| Miss penalties | **0.000 s** |
| Simulated total, including overhead/penalties | **1,210.470 s** |
| Container CPU cost | **Not measured by make sample** |
| CPU-inclusive total score | **Unavailable** without measured container CPU |
| Median-of-three leaderboard score | **Unavailable**; this command runs once locally |
| Full make sample wall time | **6.803387416 s** (6.803 s rounded) |
| Container-only wall time | Not exposed by the supplied command |
| Protocol output | 30 lines, 259,440 bytes; below the official 2 MB cap |

The supplied scorer printed:

```text
Simulated: 1210.470 s
Misses:    0 (0.000 s of the simulated time)
CPU:       not measured here. The simulated seconds above are exact. The board adds the CPU seconds your container used and takes the middle of 3 runs.
```

The selector printed `selected 1620 tests on every commit` to stderr. Its stdout remained JSON lines only. The sample scorer accepted every line and answered change. Worker costs above were independently calculated from the saved output and integer-millisecond test durations. They are recorded-runtime simulations, not actual execution of sqlglot tests.

The track's advertised **1614.1 s** baseline is separate from this local **1210.470 s simulated** result. This is a 30-change sample, without measured CPU or a three-run median. No practice or final leaderboard result was obtained.

## Files and local evidence

- Original starter: root `Dockerfile`, `Makefile`, `README.md`, `SCORING.md`, `requirements.lock`, `selector.py`, and `score.py`.
- Official samples: `sample/tests.json`, `sample/answers.json`, and `sample/commits/*.patch`; preserved locally, ignored by Git and excluded from the Docker context.
- Baseline stdout: `output.jsonl`, ignored by Git and Docker.
- Raw command/build/scorer log: `.local/baseline/blast-radius-make-sample.log`; timing: `.local/baseline/blast-radius-make-sample-timing.json`.
- Retrieved HTML, archive, and standalone scoring document are retained in `.local/baseline/`, excluded from Git and Docker.
- Added tracked-intent files: `.gitignore`, `.dockerignore`, `docs/RULES_NOTES.md`, and this report. No original starter file was edited.

`.gitignore` excludes samples, output, archives, local evidence, downloaded checkouts, virtual environments, caches, and build artifacts. `.dockerignore` also keeps evaluation labels and local artifacts out of the build context. Keep future derived maps as plain files built from the clean pinned source; neither ignore file broadly excludes JSON maps. Before submitting, audit all Git-included files and history against the 20 MB limit; ignored files already tracked by a future operation would still count.

Final verification: `make check` rebuilt with the added .dockerignore and exited 0 with `format ok`. This reran the same unmodified selector and refreshed the ignored output.jsonl; the baseline timing above remains the first `make sample` measurement. All **39** original archive files still matched byte-for-byte. `git check-ignore` confirmed exclusions for samples, output, downloaded archives, source checkouts, environments, and caches. An audit using `git ls-files --cached --others --exclude-standard -z` found **11** intended repository files totaling approximately **40 kB**, well below 20 MB. The newly initialized Git repository has no commits or imported history. `git diff --check` exited 0 (the new files are untracked).

At the close of Stage 1 there was no remaining blocker. Git hosting/public repository setup and submission were not requested in that stage.

## Stage 2 experiment — worker scheduling only

Measured November 21, 2026. Every available test is still selected for every change. No sample answers, failure categories, patch contents, or commit-specific information influence the schedule. Answers are read only by local evaluation. The official scorer, scoring document, Makefile, Dockerfile, requirements lock, and sample data remain byte-identical to the downloaded archive: **38 original files unchanged**, with only selector.py changed.

### Reproducible checkpoint and implementation

Before editing, copied the existing selector to `checkpoints/selector_stage1.py` and verified it against the archive. Its SHA-256 is `52ed812c2fc5bdacaa33704d88a2c55b6b0439791d3826f9291be1648b726e2d`. The checkpoint is a plain repository file, requires no sample labels, and is imported by focused checks as the independent original partition reference. To reproduce Stage 1 without replacing the current selector:

```sh
docker build --platform linux/amd64 --tag blast-radius-stage1 -f - . <<'DOCKERFILE'
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
COPY checkpoints/selector_stage1.py /app/selector.py
CMD ["python", "/app/selector.py"]
DOCKERFILE
make -o build sample IMAGE=blast-radius-stage1 OUTPUT="$PWD/.local/stage2/reproduced-stage1.jsonl"
```

This checkpoint reproduction recipe is provided for future use; it was not separately executed during Stage 2. The checkpoint's exact bytes and the saved Stage 1 output were verified instead. The normal `make sample` continues to build the current selector.

`schedule(selected_test_ids, seconds_by_test)` accepts integer test numbers and a mapping of numbers to recorded seconds. It rejects duplicate/unknown/noninteger selected IDs and negative/nonfinite selected durations; an empty selection returns `[]`. It sorts by descending recorded duration with ascending test number as the tie breaker, then greedily assigns to the least-loaded worker, breaking load ties by worker index. It considers each feasible count from 1 through min(8, number of selected tests), along with the original starter's three-worker floating-point partition in official test-number order. Empty workers are removed.

New loads and all candidate costs use the scorer's `floor(seconds * 1000 + 0.5)` millisecond conversion and `max(worker_loads) + 2000 * occupied_workers`. The minimum-cost partition wins; ties prefer fewer occupied workers, then lexicographically smaller worker lists. Sorting selected IDs makes results independent of input iteration order. The partition is computed once before the patch loop and reused for every change. There is no expensive search and no change to test selection.

### Commands, environment, and checks

Commands actually executed from the repository root:

```sh
docker context show
docker info --format '{{.OperatingSystem}}'
python3 -m unittest discover -s tests -v
make check
make sample
docker run --rm --platform linux/amd64 --network none --cpus 2 \
  --memory 4096m --memory-swap 4096m --pids-limit 256 --read-only \
  --tmpfs /tmp:rw,size=64m,mode=1777 --cap-drop ALL \
  --security-opt no-new-privileges --user 65534:65534 --env HOME=/tmp \
  --env PYTHONDONTWRITEBYTECODE=1 --volume "$PWD:/workspace:ro" \
  --workdir /workspace blast-radius-entry \
  python -m unittest discover -s tests -v
```

The engine checks returned `desktop-linux` and `Docker Desktop`; no Docker configuration changed. The existing official Makefile used linux/amd64 build/run flags and its original runtime restrictions on the same ARM64 host. Host Python remained 3.9.6; the container used the unchanged pinned Python image. No push or submission was performed.

Focused checks: **10 tests passed on both host Python 3.9.6 and Docker's linux/amd64 Python 3.13.18**, including 64 seeded synthetic workloads per suite. The container suite reported 0.024 seconds (unittest's elapsed time, not full Docker-command wall time). They verify empty, single-test, balanced, uneven, zero-duration, subset, and eight-worker cases; exact-once selection and known IDs; determinism under reordered inputs; invalid-input rejection; millisecond cost agreement with the untouched official scorer; and cost never exceeding the checkpoint's original partition. Synthetic scorer answers contain no failing tests; the checks do not use sample failure labels.

`make check` exited **0**, printing `format ok`. `make sample` exited **0**. The two output files were byte-identical. An additional audit of every emitted change confirmed all 1,620 known test numbers appear exactly once, with four nonempty workers. Local official-scorer evaluation of both saved Stage 1 output and Stage 2 output confirmed the before/after scores and zero misses. Archive comparison confirmed the checkpoint and all untouched original files.

The Make commands were timed sequentially with host `time.perf_counter()` around `subprocess.run(['make', target], stdout=log, stderr=subprocess.STDOUT)` for targets `check`, then `sample`. Raw logs, timing JSON, both Stage 2 outputs, the saved Stage 1 output, and calculated metrics are retained under ignored `.local/stage2/`.

### Measured results

| Measurement | Stage 1 | Stage 2 |
| --- | --- | --- |
| Changes / available tests | 30 / 1,620 | 30 / 1,620 |
| Tests selected per change | 1,620 | 1,620 |
| Chosen workers | 3 | **4** |
| Worker test counts | 500 / 510 / 610 | **1 / 485 / 613 / 521** |
| Worker recorded loads, seconds | 34.349 / 34.349 / 34.349 | **28.817 / 24.744 / 24.743 / 24.743** |
| Batch busiest-worker test cost | 1,030.470 s | **864.510 s** |
| Batch worker overhead | 180.000 s | **240.000 s** |
| Missed changes | 0 | **0** |
| Miss penalties | 0.000 s | **0.000 s** |
| Simulated score | 1,210.470 s | **1,104.510 s** |
| Simulated savings | — | **105.960 s (8.753625%)** |
| Full make sample wall time | 6.803387416 s | **0.569339291 s** |
| Full make check wall time | Not measured | **2.325061500 s** |
| Container CPU / CPU-inclusive total | Unmeasured / unavailable | **Unmeasured / unavailable** |
| Protocol output size | 259,440 bytes | **259,500 bytes**, 30 lines |

Improvement is `(1210.470 - 1104.510) / 1210.470 * 100`. Each Stage 2 change costs 28.817 + 4 × 2 = **36.817 s**. A single 28.817-second test sets a floor for the busiest worker; extra workers beyond four cannot reduce that floor and add overhead. The observed four-worker partition isolates it on worker zero.

Wall time includes build, container execution, and the host scorer. Stage 1 pulled base layers, whereas the Stage 2 sample run reused the image built immediately before it by `make check`; these wall times are not a controlled performance comparison. Container-only wall time and CPU remain unmeasured. These are **local sample results**, not a practice or final leaderboard score; no CPU-inclusive median score is claimed.

Stage 2 is complete. No coverage-based selection, further optimization stage, push, or submission has begun.
