# Stage 4 — first coverage-informed selector

Measured locally November 21, 2026. **Simulated cost decreased from 1,104.510 s to 916.871 s: 187.639 s saved, or 16.988438%.** Both selectors had zero missed changes, zero missed failing tests, and zero penalties on the same 30 official sample changes. These are sample results, not leaderboard results or a guarantee for unseen changes.

## Implementation and source integrity

Saved the byte-identical Stage 2 selector as `checkpoints/selector_stage2.py`, SHA-256 `61183dc6d4cbdbbc9267d2c3b386e27e8fc8b73732d2e0e4382d51d2a10d0b7e`. Its `split`, `schedule`, and `_partition_cost_ms` functions remain unchanged in the current selector; their ASTs were independently compared. The same deterministic 1–8-worker scheduling policy is used for each selected set, and identical selected sets reuse a partition within the batch.

Reused the existing Stage 3 index without retracing or modifying it. Index SHA-256 remains `7fa1e0af5229ea57293a4d3c73f1793d6bfdec5b18cea962e908f47366c93998`. The original scorer, Makefile, scoring documentation, dependency lock, and every sample file were compared against the official archive and remain unchanged (37 original files other than the intentionally changed Dockerfile and selector).

Runtime files:

- `selector.py`: batch loading, existing scheduler, protocol output, selection diagnostics, and a partial process CPU measurement on stderr.
- `selection.py`: index validation, incoming-manifest identity resolution, coverage-set unions, cohort widening, clean-source import graph, and explicit fallback reasons.
- `patch_analysis.py`: normalized paths, strict unified-diff parsing, in-memory reconstruction, and old/new AST scope correspondence.
- `Dockerfile`: copies the maps/runtime modules and obtains verified clean base Python source during build.

The build-only `tools/fetch_base.py` downloads sqlglot exclusively from `https://codeload.github.com/tobymao/sqlglot/tar.gz/eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. Archive SHA-256: `93b2445f15f395b81c20556777ece19a6c7507df950f13fa9fac4a3be739af0d`. It extracts only the 258 indexed Python files, rejects nonregular/unsafe paths, and verifies every file's content hash against the clean coverage index. This is sufficient source for reconstruction and import analysis; fixtures and a Git checkout are not required at runtime. The source revision marker and relevant file hashes are checked at runtime too. No source checkout or downloaded archive enters Git.

The image retains the official pinned Python base image. Build downloads use only the permitted pinned sqlglot source. Runtime does not fetch anything, import/execute patched code, run tests, or write patches to disk. Each patch is independently reconstructed against immutable `/app/base`, never against another incoming change.

## Selection policy

The policy loads maps once, decodes deduplicated test/shared sets into integer bitsets, and resolves canonical pytest identities against **each incoming tests.json**. Historic `manifest_number` values are not consulted. Unknown, ambiguous, file-mismatched, or incomplete incoming identities are mandatory selections. A missing/invalid index or base revision causes all-test fallback.

Patch handling validates old context, old/new hunk offsets and counts, multiple files/hunks, insertions, deletions, rename metadata, and final-newline markers. Paths normalize to the relative index paths; traversal is rejected. File additions/deletions/renames can be reconstructed where meaningful, then conservatively fall back. Binary/combined diffs and unsupported records also fall back. Syntax errors or uncertain scope matching do not silently omit tests.

For localized function-body edits, old/new scopes must correspond by qualified identity and unchanged headers/initialization structure. Added statements are located in the **new** AST, then paired with the old enclosing functions; no inserted line is assigned invented historical line coverage. The selection unions changed old-line coverage and all affected enclosing function-body coverage, including outer functions for nested edits. Definition/header import execution is excluded from the body range. All selected test classes widen to their clean-source class cohorts to account for shared fixtures and caches. Recorded fixture execution additionally includes every recorded consumer. Test/helper source edits widen through clean-source import dependents where available.

Module/class initialization, new/deleted definitions, changed headers/decorators, imports, renames, and edits outside a localized body expand through the clean AST import graph and then retain all tests because that graph cannot establish a safe narrow boundary for inheritance, re-exports, lazy dialect registries, or global state. The diagnostic reports both the import-cohort size and the remaining gap. A zero-sized static cohort is **not** interpreted as no affected tests.

Global/shared process execution, decorated/cached function bodies, dynamic eval/exec/compile, explicit global/nonlocal state, unknown fixture consumers, ambiguous source scopes, unindexed/non-Python files, and absent body coverage also fall back to all tests. A comment or identical normalized AST never causes the selector to skip a change: text edits still require scope/coverage handling, or fallback.

Immutable source text/AST analyses and the import graph are cached. Import analysis uses the clean module AST independently of unique function names; property accessors/repeated definitions can make scope pairing ambiguous without invalidating imports. This remains a deliberately small import analysis, not a complete call/inheritance/data-flow engine.

## Reproduction and checks

With the existing Docker Desktop context active, run from the repository root:

```sh
python3 tools/evaluate_stage4.py
```

This command builds a checkpoint image from the pinned original Python base and `checkpoints/selector_stage2.py`, then executes:

```sh
make -o build sample IMAGE=blast-radius-stage2 \
  OUTPUT="$PWD/.local/stage4/stage2-output.jsonl"
make check
make sample
```

It also runs `python -m unittest discover -s tests -v` inside the current Linux image, with the repository bound read-only, and measures three additional sandboxed CPU runs per selector. Docker run flags are taken directly from `make -n sample`; the original Makefile is not edited. Commands/timings, stdout/stderr, per-change evaluation, and CPU snapshots are retained under ignored `.local/stage4/`.

The engine checks returned context **desktop-linux**, operating system **Docker Desktop**. Generation, runtime, and evaluation used **linux/amd64 on the ARM64 host**, with the same official Python 3.13 image. Runtime checks used no network, two CPUs, 4096m memory/swap, 256 processes, read-only disk, 64m tmpfs, nobody/HOME=/tmp, dropped capabilities, and no-new-privileges.

**28 focused tests passed in Docker**, covering the existing scheduler, manifest renumbering, unresolved/ambiguous incoming identities, shifted/multiple hunks, boundary insertions, newline markers, additions/deletions/renames, new/deleted functions and overrides, class/global/header/decorator changes, shared fixture/process coverage, class cohorts, dynamic imports/execution/state, uncertain inputs, fallback, and independent immutable-base reconstruction. Synthetic checks contain no sample failure labels.

`make check` and `make sample` both exited 0. Every additional CPU run produced byte-identical protocol output to its corresponding sample run. The official scorer accepted all protocol outputs. Labels are read only by the evaluator after selector execution; no failure labels, patch fingerprints, edit-kind answer tables, or commit-specific exceptions enter the selector or derived maps.

| Command | Observed host wall time |
| --- | ---: |
| Checkpoint image build, cached base | 0.244146041 s |
| Stage 2 checkpoint sample run and scoring | 0.376768250 s |
| make check | 2.891256750 s |
| make sample | 2.806088875 s |
| Focused Docker checks | 0.433440333 s |

These wall times include Docker/client overhead where applicable and are not container CPU time. The focused suite reported 0.062 seconds of unittest elapsed time inside Docker. The first current-image build successfully fetched and verified the source; the table above is the final reproducible comparison using cached build layers.

## Results and per-change audit

Stage 2 selected 1,620 tests and cost **36.817 s** for every change, with four workers. Stage 4 made **six narrower selections and 24 all-test fallbacks (80%)**. Total scheduled test appearances fell from 48,600 to **39,896**. All-test fallbacks account for **883.608 s** of the 916.871 s total; narrower cases cost 33.263 s combined.

Reason abbreviations below describe runtime decisions, never failure labels:

- **C:** localized function-body coverage plus test-class cohorts.
- **F:** non-Python/fixture change; all tests.
- **I:** structural/class/module initialization change; import expansion plus all tests.
- **B:** outside a localized body, including boundary/comment edits; import expansion plus all tests.
- **P:** unattributed child-process execution; all tests.
- **A:** ambiguous source scope correspondence; all tests.
- **D:** decorated/cached function; all tests.

| Change | Selected | Workers | Simulated s | Missed tests | Penalty s | Reason |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2haz | 1620 | 4 | 36.817 | 0 | 0 | A |
| 2jrq | 1620 | 4 | 36.817 | 0 | 0 | P |
| 2qn5 | 341 | 2 | 6.119 | 0 | 0 | C |
| 2vdj | 1620 | 4 | 36.817 | 0 | 0 | F |
| 3utz | 1620 | 4 | 36.817 | 0 | 0 | P |
| 4d63 | 1620 | 4 | 36.817 | 0 | 0 | I |
| 535z | 1620 | 4 | 36.817 | 0 | 0 | I |
| 5y72 | 1620 | 4 | 36.817 | 0 | 0 | P |
| 66ks | 1620 | 4 | 36.817 | 0 | 0 | D |
| 6vvp | 1620 | 4 | 36.817 | 0 | 0 | F |
| 6ze8 | 1620 | 4 | 36.817 | 0 | 0 | I |
| 8y7j | 73 | 1 | 2.708 | 0 | 0 | C |
| 986c | 1620 | 4 | 36.817 | 0 | 0 | B |
| 9u5k | 177 | 1 | 4.774 | 0 | 0 | C |
| ary6 | 1620 | 4 | 36.817 | 0 | 0 | A |
| bap8 | 8 | 1 | 2.093 | 0 | 0 | C |
| bj7g | 209 | 3 | 12.778 | 0 | 0 | C |
| bvw2 | 1620 | 4 | 36.817 | 0 | 0 | B |
| egys | 1620 | 4 | 36.817 | 0 | 0 | F |
| f4bn | 1620 | 4 | 36.817 | 0 | 0 | F |
| f4xa | 1620 | 4 | 36.817 | 0 | 0 | B |
| fryt | 208 | 1 | 4.791 | 0 | 0 | C |
| gbav | 1620 | 4 | 36.817 | 0 | 0 | I |
| gbhk | 1620 | 4 | 36.817 | 0 | 0 | F |
| j6uz | 1620 | 4 | 36.817 | 0 | 0 | A |
| ktz3 | 1620 | 4 | 36.817 | 0 | 0 | I |
| mthh | 1620 | 4 | 36.817 | 0 | 0 | F |
| nwnx | 1620 | 4 | 36.817 | 0 | 0 | F |
| rszg | 1620 | 4 | 36.817 | 0 | 0 | B |
| st8f | 1620 | 4 | 36.817 | 0 | 0 | F |

Fallback counts: **8** non-Python/fixture, **5** structural/initialization, **4** outside-body, **3** shared process, **3** ambiguous scope, and **1** decorated/cached function. The five costliest changes, breaking the 24-way 36.817-second tie lexicographically, are **2haz, 2jrq, 2vdj, 3utz, and 4d63**. Each costs 36.817 s, selects all 1,620 tests, and has zero penalty.

## CPU estimate

CPU snapshots were taken **inside Linux**, separately from host Docker wall time. `tools/stage4_cpu.py` runs the selector as instrumented PID 1 and reads both process `getrusage` and the container's cgroup-v2 `cpu.stat usage_usec`. `/proc/self/cgroup` returned `0::/`; measured child-process CPU was zero. The cgroup snapshot includes interpreter startup/imports and wrapper work up to the snapshot, but excludes final printing/shutdown. The selector's own stderr timer measures only work after its main-entry imports and is a narrower partial measurement.

| Selector | Three local cgroup CPU snapshots, s | Median, s |
| --- | --- | ---: |
| Stage 2 checkpoint | 0.227080 / 0.222806 / 0.223377 | **0.223377** |
| Stage 4 | 2.398839 / 2.431709 / 2.384068 | **2.398839** |

Process user+system CPU snapshots were 0.225981 / 0.221252 / 0.221631 s for Stage 2 and 2.397684 / 2.430463 / 2.382578 s for Stage 4. Main-loop-only CPU was approximately 2.17 s in one instrumented Stage 4 run. These are **local emulated Linux CPU estimates**, with instrumentation overhead and a before-exit boundary; they are not authoritative server CPU measurements or a submitted score. Adding the median local cgroup snapshot gives approximately 1,104.733 s versus 919.270 s, but that is only a local instrumented estimate. `make sample` itself still does not measure CPU or a leaderboard median.

## Remaining gaps and size

No sample misses remain unresolved. Zero sample misses do not establish sound exclusion on every unseen mutation. Important remaining limits are observed-path coverage, new behavior that exercises previously untaken branches, source introspection, indirect object/global state and cross-class caches, dynamic registries/imports, inheritance/removed overrides, native/non-Python dependencies, and child-process attribution. Repeated qualified definitions/property accessors currently make the whole file's scope matching ambiguous and cause fallback. The import graph cannot prove safety for global initialization or structural changes, so those remain all-test cases even when a static cohort is found.

These gaps are explicit fallbacks where detected; dynamic coverage and class cohorts cannot prove that every undetected cross-class state relationship has been captured. No narrower selection is inferred from a zero static import cohort or absent historical coverage. Future dependency work must continue to derive from the clean pinned source, not sample answers.

The Git-included file audit (cached plus untracked, respecting .gitignore) remains approximately **4.67 MB**, below the conservative **20,000,000-byte** limit. The ignored local datasets, source checkouts, logs, archives, and evaluation reports are excluded. Exact final size is recorded in `.local/stage4/final-audit.json` after this document is written. No raw coverage, downloaded sqlglot source, or answer map was added to the submission files.

Stage 4 is complete. No push or competition submission was made, and no later stage has begun.
