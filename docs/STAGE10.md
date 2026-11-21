# Stage 10 process coverage attribution

The baseline is the published Stage 9 commit `4d835ea1f991a0feb3f08ad1ab42198939b79f08`, which scored 433.175 simulated seconds on the local sample. All source tracing uses sqlglot `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`.

## Per-change cost audit

The offline audit replayed the exact Stage 9 image and checked that all 30 worker partitions matched the verified sample run. For each change, it retained the test numbers on all tied busiest workers and the inclusion reasons for every selected test. The table shows the longest test on the busiest worker, including its reasons and the score difference when that one test is omitted and the same scheduler partitions the remaining tests. These are scheduling counterfactuals. Selection still follows production evidence.

The mechanism columns show leave-one-mechanism-out simulated seconds, which recompute class widening from the retained seed evidence before scheduling. Body and statement lines are direct coverage, positional coverage is execution on shifted lines, and the process column represents explicit uses of the 340-test coarse cohort. Resource readers, source observers, shared fixture readers and declaration maps remain fixed, including any process evidence already embedded in those maps. Full-suite fallback is also fixed. The development audit never reads failure labels.

| Change | Score s | Busiest load s | Longest test on busiest worker | Inclusion reasons | Single-test marginal s | Process s | Class s | Position s | Direct s |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `2haz` | 27.454 | 21.454 | `TestExecutor.test_execute_tpcds` | class, process | 9.341 | 0.000 | 0.000 | 0.000 | 0.000 |
| `2jrq` | 27.454 | 21.454 | `TestExecutor.test_execute_tpcds` | class, process | 11.415 | 0.000 | 0.000 | 0.000 | 0.000 |
| `2qn5` | 5.086 | 3.086 | `TestBigQuery.test_bigquery` | class | 0.436 | 0.000 | 2.550 | 0.000 | 5.086 |
| `2vdj` | 2.083 | 0.083 | `TestOptimizer.test_pushdown_predicates` | resource | 2.083 | 0.000 | 0.000 | 0.000 | 0.000 |
| `3utz` | 27.454 | 21.454 | `TestExecutor.test_execute_tpcds` | class, direct, process | 10.915 | 0.000 | 0.000 | 0.000 | 0.000 |
| `4d63` | 36.817 | 28.817 | `TestParser.test_max_nodes` | full suite | 7.363 | 0.000 | 0.000 | 0.000 | 0.000 |
| `535z` | 27.454 | 21.454 | `TestExecutor.test_execute_tpcds` | class, declaration | 11.197 | 0.000 | 0.000 | 0.000 | 0.000 |
| `5y72` | 27.454 | 21.454 | `TestExecutor.test_execute_tpcds` | class, process | 11.517 | 2.000 | 0.000 | 0.000 | 0.000 |
| `66ks` | 27.454 | 21.454 | `TestExecutor.test_execute_tpcds` | class, process | 11.517 | 2.000 | 0.000 | 0.000 | 0.000 |
| `6vvp` | 2.037 | 0.037 | `TestOptimizer.test_qualify_columns__invalid` | resource | 2.037 | 0.000 | 0.000 | 0.000 | 0.000 |
| `6ze8` | 2.127 | 0.127 | `TestSQLGlotC.test_build_removes_obsolete_extensions` | class, declaration | 0.073 | 0.000 | 0.000 | 0.000 | 0.000 |
| `8y7j` | 2.031 | 0.031 | `TestDuckDB.test_time` | direct | 2.031 | 0.000 | 0.000 | 0.000 | 2.031 |
| `986c` | 27.454 | 21.454 | `TestExecutor.test_execute_tpcds` | class, process | 11.132 | 13.729 | 0.000 | 0.000 | 0.000 |
| `9u5k` | 4.186 | 2.186 | `TestDialect.test_lazy_load` | class | 0.368 | 0.000 | 2.010 | 0.000 | 4.186 |
| `ary6` | 35.180 | 29.180 | `TestParser.test_max_nodes` | class | 7.726 | 0.000 | 7.726 | 0.000 | 7.726 |
| `bap8` | 2.042 | 0.042 | `TestTransforms.test_eliminate_join_marks` | direct | 2.042 | 0.000 | 0.000 | 0.000 | 2.042 |
| `bj7g` | 2.367 | 0.367 | `TestClickhouse.test_clickhouse` | direct | 0.230 | 0.000 | 0.000 | 0.000 | 0.241 |
| `bvw2` | 3.127 | 1.127 | `TestBigQuery.test_bigquery` | class | 0.436 | 0.000 | 0.929 | 0.940 | 0.000 |
| `egys` | 2.596 | 0.596 | `TestOptimizer.test_simplify` | resource | 2.596 | 0.000 | 0.000 | 0.000 | 0.000 |
| `f4bn` | 2.007 | 0.007 | `TestOptimizer.test_pushdown_cte_alias_columns` | resource | 2.007 | 0.000 | 0.000 | 0.000 | 0.000 |
| `f4xa` | 2.005 | 0.005 | `TestDrill.test_ilike` | direct | 2.005 | 0.000 | 0.000 | 0.000 | 2.005 |
| `fryt` | 4.758 | 2.758 | `TestBigQuery.test_bigquery` | class | 0.436 | 0.000 | 2.585 | 0.000 | 4.758 |
| `gbav` | 36.817 | 28.817 | `TestParser.test_max_nodes` | full suite | 7.363 | 0.000 | 0.000 | 0.000 | 0.000 |
| `gbhk` | 2.061 | 0.061 | `TestOptimizer.test_annotate_types` | resource | 2.061 | 0.000 | 0.000 | 0.000 | 0.000 |
| `j6uz` | 12.920 | 6.920 | `TestOptimizer.test_scope` | class | 0.845 | 0.000 | 8.521 | 0.000 | 12.920 |
| `ktz3` | 36.817 | 28.817 | `TestParser.test_max_nodes` | full suite | 7.363 | 0.000 | 0.000 | 0.000 | 0.000 |
| `mthh` | 3.016 | 1.016 | `TestOptimizer.test_merge_subqueries` | resource | 3.016 | 0.000 | 0.000 | 0.000 | 0.000 |
| `nwnx` | 2.092 | 0.092 | `TestOptimizer.test_pushdown_projection` | resource | 2.092 | 0.000 | 0.000 | 0.000 | 0.000 |
| `rszg` | 36.817 | 28.817 | `TestParser.test_max_nodes` | class | 7.363 | 0.000 | 9.363 | 9.363 | 0.000 |
| `st8f` | 2.008 | 0.008 | `TestOptimizer.test_isolate_table_selects` | resource | 2.008 | 0.000 | 0.000 | 0.000 | 0.000 |

Leave-one-out totals overlap. The audit also distributes the difference from the fixed routes using all 16 subsets of the four mechanisms. The Shapley contribution is the average cost added by each mechanism over all orders. The fixed score is 168.271 s. Both accounting views use the official worker overhead and integer-millisecond durations.

| Mechanism | Leave-one-out s | Shapley contribution s |
| --- | ---: | ---: |
| Process | 17.729 | 132.345 |
| Class | 33.684 | 39.757 |
| Position | 10.303 | 17.206 |
| Direct | 40.995 | 75.596 |

The 21.454-second executor TPC-DS test is the sole occupant of the busiest worker on seven sample changes. On several of those changes it has direct, declaration, or class evidence as well as process evidence. Omitting the entire explicit process reason saved 17.729 s in the counterfactual under the other current routes. The three relevant changes contribute 13.729, 2.000, and 2.000 s. The class column contains a larger 33.684 s leave-one-out opportunity.

Reproduce the reason audit against the verified Stage 9 image and official protocol output:

```sh
mkdir -p .local/stage10/audit
docker run --rm --platform linux/amd64 --network none --cpus 2 --memory 4096m \
  --read-only --tmpfs /tmp:rw,size=64m \
  --volume "$PWD/sample/commits:/data/commits:ro" \
  --volume "$PWD/sample/tests.json:/data/tests.json:ro" \
  --volume "$PWD/.local/stage9/release/evaluation/sample-output.jsonl:/baseline.jsonl:ro" \
  --volume "$PWD/tools/process_observation/audit_stage9.py:/audit.py:ro" \
  --entrypoint python blast-radius-stage9:4d835ea1f991 /audit.py >.local/stage10/audit/stage9.json
```

## Clean process tracing

The tracer captures the submitting pytest phase or fixture, the executor pool identity, and its original work ID. The child uses the same CPython work item and arguments. Only its bootstrap envelope carries the pool ID. Local Python monitoring events delimit worker initialization, queue deserialization, entry into the callable, and result or exception handling. Coverage.py's C tracer records lines under those contexts. This distinguishes code executed by pickle or startup from execution inside the callable. Child JSON archives are emitted atomically at normal exit. Missing tasks, missing or partial archives, unexpected launches, unmatched PIDs, and failing clean runs prevent an export. Background Python threads, if observed, disqualify the child's lines from task-only attribution.

An initial attempt treated the repeated opening line of a multiline result call as a second exit. It disrupted the pools and produced 24 failing numbered tests. A subsequent attempt using a Python callback for every line was stopped after excessive tracing overhead. The successful run used the C tracer for source lines and an idempotent boundary marker. It completed in 107.9 s in Linux amd64 on Docker Desktop under Apple Silicon emulation, with all 1,620 numbered tests and 25,440 subtests passing. The official unnumbered skip was also present.

| Worker population | Spawned workers | Matched tasks | Tests in pool cohort | Initialization |
| --- | ---: | ---: | ---: | --- |
| Executor TPC-DS | 4 | 99 | 1 | Explicit schema and table initializer |
| Executor TPC-H | 4 | 22 | 1 | Explicit schema and table initializer |
| Shared optimizer pool | 4 | 2,062 | 167 | Class-owned pool with 22 submitting tests |

The remaining two child archives were the separately launched Python subprocess and multiprocessing's resource tracker. In all, 14 PIDs and 2,183 submitted tasks reconciled exactly. The 12 pool workers reused their processes. The independent launches use distinct spawned interpreters, while state between tasks within a pool can persist. Each routed line adds every indexed owner of its observed pools, including owners of the fixture that created the pool. The runtime has no task-level selection rule. Lines observed in the opaque subprocess, before or between tasks, during initialization, or while handling a result retain the previous 340-test evidence. Native launches and cross-pool effects outside the Python observation channels remain limitations.

The Stage 3 index contains 32,758 physical lines marked as process execution. The experiment mapped 21,942 to known pools and retained 10,816 as unmatched or opaque. Another 1,867 mapped lines were observed outside tasks, leaving 20,075 task-only lines. The clean run also reported 432 unbacked paths, which supply no narrowing for a physical source file. The 14 raw child archives total 689,119 bytes and stay offline. The deterministic runtime artifact is 235,378 bytes and is bound to the pinned revision, coverage and resource hashes, and canonical manifest.

## Candidate policy

The offline replay of exact affected line ranges cost 417.446 s for both whole-pool attribution and task-line-gated pool attribution. The latter gained 13.729 s on the mixed comment case and 2.000 s on the executor comparison case. On the other six changes that explicitly used the process group, the other selection evidence or unresolved process lines kept the same cost.

The runtime uses narrower eligibility than that replay. It accepts a same-line, same-type boolean or integer replacement in a localized return or plain assignment. It also accepts standalone prose comment insertions when the Stage 9 source and position path applies. The comment guard checks tokens, exact text reconstruction, encoding, and the AST with type comments enabled. Each affected legacy process line must be in a task-only range of the new evidence. The selector then unions the owning pool cohorts with parent coverage, all applicable fixture and source evidence, and conditional class widening. Unsupported companion Python edits restore the coarse process group for the change. The sample `is None` to `== None` edit retains the coarse route because it can invoke custom equality. The rest of the Stage 9 selection and scheduling rules supply the comparison.

Run the tracing only in the offline image, using an empty result directory and the clean Stage 3 checkout:

```sh
mkdir -p .local/stage10/trace
docker run --rm --platform linux/amd64 --network none \
  --cpuset-cpus 0,1,2,3 --cpus 4 --memory 6144m --memory-swap 6144m --pids-limit 256 \
  --read-only --tmpfs /tmp:rw,size=512m --env PYTHONHASHSEED=0 --env OPENBLAS_NUM_THREADS=1 \
  --env OMP_NUM_THREADS=1 --env MKL_NUM_THREADS=1 --env PROCESS_OBSERVATION_TRACE=1 \
  --env COVERAGE_CORE=ctrace --env PYTHONPATH=/src:/process_observation:/tool:/label-tool \
  --volume "$PWD/.local/coverage-final/sqlglot:/src:ro" --volume "$PWD/tools/coverage:/tool:ro" \
  --volume "$PWD/tools/process_observation:/process_observation:ro" \
  --volume "$PWD/tools/stage5_label.py:/label-tool/stage5_label.py:ro" \
  --volume "$PWD/sample/tests.json:/manifest/tests.json:ro" \
  --volume "$PWD/.local/stage10/trace:/result" \
  --entrypoint python blast-radius-coverage /process_observation/run.py
python3 -m tools.process_observation.export .local/coverage-final/sqlglot \
  coverage_index/index.json sample/tests.json .local/stage10/trace coverage_index/process_tasks.json
```

For the pool replay, add `--volume "$PWD/coverage_index/process_tasks.json:/pool-evidence.json:ro"` to the Stage 9 audit command above. This outputs each line coverage counterfactual separately from the real policy measurements.

## Measured results and validation

The promoted policy saves **13.729 simulated seconds (3.17%)** on the public sample. The one changed schedule selects 402 tests instead of 462. Its busiest worker load drops far enough to cut the simulated cost from 27.454 to 13.725 s. All three structural and initialization fallbacks remain. All comparisons had zero missed changes, missed tests and penalties.

| Evaluation | Policy | Simulated seconds | Test selections | Full-suite fallbacks | Median container CPU s |
| --- | --- | ---: | ---: | ---: | ---: |
| Public sample | Stage 9 | 433.175 | 10,632 | 3 | 2.686 |
| Public sample | Stage 10 | 419.446 | 10,572 | 3 | 2.828 |
| Seven fresh cases | Stage 9 | 220.267 | 6,364 | 3 | — |
| Seven fresh cases | Stage 10 | 203.461 | 5,798 | 3 | — |
| Ten-case batch | Stage 9 | 311.992 | 8,821 | 4 | 4.200 |
| Ten-case batch | Stage 10 | 295.186 | 8,255 | 4 | 4.224 |
| Twelve Stage 9 regressions | Stage 9 | 350.008 | 12,902 | 7 | — |
| Twelve Stage 9 regressions | Stage 10 | 350.008 | 12,789 | 7 | — |

CPU values are the median of three readings from `/sys/fs/cgroup/cpu.stat` after selector execution and include interpreter startup plus the measurement wrapper. The Linux amd64 containers ran under Apple Silicon emulation with the official sandbox settings, using the same two VM CPUs for both policies. CPU for the ten-case batch includes seven fresh cases and three re-executed regressions. Each repeated prediction matched the frozen worker output.

### Independent positives and safety regressions

The candidate, official inputs, and both policies' predictions were frozen before starting any fresh test outcome run. The SHA-256 of the freeze manifest is `44c83866397acfda6e2e6fbd9422feaefa56774327bc26229f42a8e16a96103c`. All ten cases completed with 1,620 numbered tests accounted for in each. The seven fresh cases produced 48 failing test occurrences, all selected. The three end-to-end Stage 9 regressions produced 6 failures, all selected. The local labeler counts failing subtests under their numbered parent, accounts for collection failures and timeouts, and excludes incomplete reports from evaluation. All 12 original Stage 9 patches were also rerun through both selectors against their complete prior labels.

| Case | Failing numbered tests | Stage 9 → Stage 10 selected | Stage 10 route |
| --- | ---: | ---: | --- |
| `comment-with-worker-behavior` | 6 | 470 → 470 | task lines with pool owners |
| `executor-boolean` | 5 | 344 → 64 | task lines with pool owners |
| `optimizer-copy-budget` | 5 | 346 → 233 | task lines with pool owners |
| `optimizer-join-expand` | 3 | 344 → 171 | task lines with pool owners |
| `regression-comment-body-and-fixture` | 3 | 417 → 417 | coarse process cohort |
| `regression-disjoint-reader-behavior-fixture` | 2 | 420 → 420 | coarse process cohort |
| `regression-new-position-reader` | 1 | 1,620 → 1,620 | unresolved companion source observation |
| `serialization-restore` | 3 | 1,620 → 1,620 | dynamic execution dependency gap |
| `worker-initializer` | 1 | 1,620 → 1,620 | nonlocal state dependency gap |
| `worker-reuse` | 25 | 1,620 → 1,620 | nonlocal state dependency gap |

The positive executor boolean mutation failed in the TPC-DS worker pool and in parent tests. The optimizer copy-budget mutation and mixed comment plus worker-behavior mutation produced failures in the reused optimizer pool. The latter retains source and position selection for the comments. The initializer, worker-state and serialization mutations retained full-suite fallback. In the worker-state case an assertion ran only after the same process had already handled a submission. Keeping whole-pool owners protects observed test coupling without using task execution alone to claim independence.

## Exact-tree verification

The verification exports the candidate commit with `git archive` and builds it using `docker build --no-cache --platform linux/amd64`. It verifies all runtime map and module hashes in the image, runs `make check`, `make sample`, and 55 focused tests, and compares the exact tree's independent predictions with the freeze. The committed Git blob total is 5,998,183 bytes versus 5,707,849 at Stage 9. The packaged `/app` inventory is 17,657,662 bytes including the pinned source, below the 20 MB limit. Only the manifest and batch patches are mounted into the submission runtime. Raw traces, local evaluation trees, and outcome labels stay outside it.
