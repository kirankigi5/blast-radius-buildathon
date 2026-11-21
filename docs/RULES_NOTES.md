# Blast Radius rules — Stage 1

Read on November 21, 2026. Official sources:

- [Track page](https://www.joinbuilders.org/buildathon/tracks/blast-radius)
- [Published starter archive](https://www.joinbuilders.org/buildathon/tracks/blast-radius/files/blast-radius-sample.tar.gz)
- [Published SCORING.md](https://www.joinbuilders.org/buildathon/tracks/blast-radius/files/SCORING.md)
- Local unmodified `README.md`, `SCORING.md`, `Makefile`, `Dockerfile`, `selector.py`, `score.py`, and `requirements.lock` extracted from that archive.

The web reader could not open the track page; HTTPS retrieval with `curl -fL` succeeded for all three URLs. These are the actual links published by the page. No retrieval blocker remains. The separately downloaded SCORING.md is byte-identical to the archived copy.

## Pinned source and environment

The track page and starter README both specify exactly
`eb11aec4be8cb2122afe713a4816662c3f0fb2fa` for sqlglot. This matches the requested revision. Every patch independently applies to that clean revision, never to another patch. The Stage 1 starter does not need or download a sqlglot checkout.

The official Dockerfile uses `python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90`. The scorer runs linux/amd64; the Makefile explicitly builds and runs that platform, including on Apple Silicon. Preserve the image digest if executing sqlglot tests: Python and SQLite versions affect test availability. Use the supplied `requirements.lock` and put the clean checkout on `PYTHONPATH` to reproduce labeling dependencies; installing sqlglot's current dev extras can choose different versions. Executor integration tests require `SKIP_INTEGRATION=0`, as used for labeling. Pytest subtest failures count even when a parent prints PASSED.

## Input and output

- `/data/tests.json`: object with `tests` and `skipped`. Each numbered test has `number`, pytest `id`, `file`, and `seconds` (three decimal places). Numbers start at zero with no gaps. Skipped tests have no number and cannot fail.
- `/data/commits/<id>.patch`: one unified diff per independent change. Its filename stem is the opaque commit ID.
- Local evaluation only: `sample/answers.json` is `{"commits": {"<id>": {"failing": [12, 845], "kind": "code"}}}`. These labels and categories are evaluation data and are never mounted into the selector.
- stdout: UTF-8, exactly one JSON object per change, with exactly the keys `commit` (known string ID) and `workers` (list of lists of test numbers). Example from the rules: `{"commit":"k7q2","workers":[[12,845,901],[3,77]]}`. `workers: []` selects nothing.
- Every change must appear exactly once. No duplicate test within or across workers for a change, and no unknown test numbers. Whole-valued JSON numbers such as `3.0` are accepted; booleans, strings, and fractions are not. Empty workers are discarded; at most eight occupied workers remain.
- Changes, workers, and tests need not be ordered. One final newline is allowed; blank lines, a BOM, non-JSON lines, NaN, and Infinity reject output. Diagnostics belong on stderr. More than 2 MB of stdout rejects a run.

The scorer rejects malformed JSON, wrong shape, unknown/repeated commits, unknown/repeated tests, too many workers, missing commits, or invalid UTF-8. Exact validation order and error codes are in SCORING.md. A failed build, crash, timeout, memory overrun, or broken rule rejects the submission without changing its best score.

## Exact scoring

Scorer version: `blast-radius-1`. Lower is better. For test t, duration is `floor(seconds[t] * 1000 + 0.5)` integer milliseconds, as implemented by score.py. All published durations have three decimals.

For a change c with k nonempty workers:

```
test_load(c) = max(sum(duration[t] for t in worker) for worker in workers)
cost(c)     = test_load(c) + 2000 * k             # milliseconds
cost(c)     = 0                                  # if k == 0
miss(c)     = any failing test absent from all workers
simulated_ms = sum(cost(c)) + 300000 * count(missed changes)
total_us     = simulated_ms * 1000 + container_cpu_us
```

A miss is charged once per change, regardless of how many failing tests were omitted. The worker/test cost still counts. A test fails when pytest reports failure, error, or timeout, or its file cannot import. One failing subtest fails the entire numbered test. Even a comment-only change is not guaranteed harmless.

CPU is aggregate user plus system CPU time for every process in the container, from start to exit, measured in microseconds. Running sqlglot tests to decide selections is allowed and charged as CPU. Build time is not charged. All three runs must be valid. The median of their totals is rounded to 0.1 seconds, halves up: `floor((median_total_us + 50000) / 100000) / 10`.

`make sample` runs once and reports exact simulated cost and misses for its output. It does not measure container CPU or produce the leaderboard total/median. `score.py --cpu-seconds <measured>` can include an independently measured CPU value; none was supplied for the Stage 1 baseline.

## Build, runtime, and submission limits

| Area | Official restriction |
| --- | --- |
| Submission | Public GitHub repository, root Dockerfile, chosen commit; at most 20 MB. Submodules and Git LFS content are not fetched. |
| Build | Network access; 4 cores, 8 GB memory, 10 minutes. Each submission builds from nothing. Installing sqlglot and running clean-source tests to derive coverage/import/fixture maps is allowed. Plain committed maps can avoid repeating this work. |
| Download sources | Public package registries (PyPI, npm, Docker Hub), GitHub releases at a fixed tag, and sqlglot's own repository at the pinned revision. No team-controlled download endpoint. Final images are rebuilt after cutoff. |
| Practice runtime | No network; 2 cores, 4 GB memory, 3 minutes for the whole batch. |
| Final runtime | 4.5 minutes; roughly 1.5 times as many changes. Other listed runtime restrictions remain. |
| Filesystem/user | Read-only disk, initially empty 64 MB `/tmp`, user nobody (65534:65534), `HOME=/tmp`, at most 256 processes. Required image files must be readable by nobody. |
| Output | At most 2 MB stdout; only protocol lines; diagnostics on stderr. |
| Submission rate | Initially once per hour per team; organizers may raise it if the queue stays short. |

The unmodified Makefile applies linux/amd64, no network, two CPUs, 4096m memory and swap cap, 256 processes, read-only filesystem, 64m tmpfs, nobody/HOME, read-only input mounts, dropped capabilities, and no-new-privileges. It does **not** implement the server's 180-second batch watchdog or 2 MB stdout cap, nor enforce server build resource/time limits. Passing locally does not prove those additional server checks. The measured Stage 1 output was below 2 MB and the entire make command finished well below 180 seconds.

## Fairness and final evaluation

- One team per person; submit the team's own work. No code sharing across teams. A later submission with another team's repository, commit, or archive is disqualified. Top entries are reviewed and teams may need to explain their work.
- Never embed sample answers or mappings from commit IDs, patch fingerprints, or edit categories to known failing tests. Sample labels are evaluation data only. Future coverage, dependency, import, or fixture maps must derive from the clean pinned source. No maps or algorithm changes were made in Stage 1.
- Keep the repository public and retain every submitted commit until results are published. A final entry that cannot be fetched/restored scores nothing.
- Practice output is hidden; feedback gives simulated seconds, CPU seconds, and miss counts per run, never which changes were missed. Local sample evaluation can name misses.
- Only the final counts for prizes. At cutoff the selected commit (best practice commit by default) runs on unseen changes, including change kinds absent from practice.
- At least the top five are rerun on the same final changes, five runs each, sequentially on one idle machine. Their median replaces their first final score.
- Practice equal scores favor the earlier submission. In the final, entries at most one second behind the best tie and rank by earliest submission; repeat grouping from the next remaining best.
- The page gives cutoff as Sunday 11:00 AM EST (November 22, 2026, in the supplied client date context). Organizers correct mislabeled changes for every team before publishing results.

The page advertises a **1614.1 s** starter baseline. That is a published reference, not this repository's measured sample result and not a score submitted by this team.
