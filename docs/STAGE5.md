# Stage 5 fallback audit and validation

## Stage 4 audit

The audit ran before policy changes against the Stage 4 checkpoint on the same 30 sample changes. The first fallback reason is the one Stage 4 emitted for the entire patch. Partial candidates are the union of coverage collected before that fallback, before resolving the fallback. A diagnostic static import cohort is shown separately because Stage 4 did not use it to narrow a fallback. Scope names include directly affected declarations and their enclosing classes. A data path has no Python scope. Multi-file patches show every changed path even when the first fallback stopped analysis early.

| Change | Paths and scopes | Stage 4 fallback | Partial candidates | Static import cohort | Selected | Seconds |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| 2haz | sqlglot/dialects/dialect.py [Dialect, Dialect.case_sensitive] | ambiguous_source_scope | 0 | — | 1620 | 36.817 |
| 2jrq | sqlglot/optimizer/eliminate_joins.py [_should_eliminate_join] | shared_process_execution | 24 | — | 1620 | 36.817 |
| 2vdj | tests/fixtures/optimizer/pushdown_predicates.sql [data] | non_python_or_fixture_change | 0 | — | 1620 | 36.817 |
| 3utz | sqlglot/serde.py [dump] | shared_process_execution | 24 | — | 1620 | 36.817 |
| 4d63 | sqlglot/dialects/snowflake.py [Snowflake, Snowflake.Tokenizer] | structural_or_initialization_change | 0 | 0 | 1620 | 36.817 |
| 535z | sqlglot/dialects/tsql.py [TSQL] | structural_or_initialization_change | 0 | 1617 | 1620 | 36.817 |
| 5y72 | sqlglot/optimizer/eliminate_subqueries.py [_eliminate_cte] | shared_process_execution | 1 | — | 1620 | 36.817 |
| 66ks | sqlglot/executor/context.py [Context, Context.table] | decorated_or_cached_function | 0 | — | 1620 | 36.817 |
| 6vvp | tests/fixtures/optimizer/qualify_columns__invalid.sql [data] | non_python_or_fixture_change | 0 | — | 1620 | 36.817 |
| 6ze8 | sqlglot/parsers/dremio.py [DremioParser] | structural_or_initialization_change | 0 | 0 | 1620 | 36.817 |
| 986c | sqlglot/dialects/singlestore.py [module/boundary]<br>sqlglot/typing/snowflake.py [_annotate_median]<br>tests/fixtures/optimizer/unnest_subqueries.sql [data] | outside_function_body | 0 | 0 | 1620 | 36.817 |
| ary6 | sqlglot/parsers/bigquery.py [BigQueryParser, BigQueryParser._parse_table_parts] | ambiguous_source_scope | 0 | — | 1620 | 36.817 |
| bvw2 | sqlglot/dialects/materialize.py [module/boundary]<br>tests/fixtures/optimizer/annotate_types.sql [data] | outside_function_body | 0 | 0 | 1620 | 36.817 |
| egys | tests/fixtures/optimizer/simplify.sql [data] | non_python_or_fixture_change | 0 | — | 1620 | 36.817 |
| f4bn | tests/fixtures/optimizer/pushdown_cte_alias_columns.sql [data] | non_python_or_fixture_change | 0 | — | 1620 | 36.817 |
| f4xa | sqlglot/generators/drill.py [DrillGenerator] | outside_function_body | 0 | 0 | 1620 | 36.817 |
| gbav | sqlglot/parsers/singlestore.py [SingleStoreParser] | structural_or_initialization_change | 0 | 0 | 1620 | 36.817 |
| gbhk | tests/fixtures/optimizer/annotate_types.sql [data] | non_python_or_fixture_change | 0 | — | 1620 | 36.817 |
| j6uz | sqlglot/parsers/bigquery.py [BigQueryParser, BigQueryParser._parse_make_interval] | ambiguous_source_scope | 0 | — | 1620 | 36.817 |
| ktz3 | sqlglot/expressions/ddl.py [TriggerProperties] | structural_or_initialization_change | 0 | 1617 | 1620 | 36.817 |
| mthh | tests/fixtures/optimizer/merge_subqueries.sql [data] | non_python_or_fixture_change | 0 | — | 1620 | 36.817 |
| nwnx | tests/fixtures/optimizer/pushdown_projections.sql [data] | non_python_or_fixture_change | 0 | — | 1620 | 36.817 |
| rszg | sqlglot/optimizer/scope.py [module/boundary]<br>sqlglot/typing/snowflake.py [_annotate_within_group]<br>tests/fixtures/optimizer/qualify_columns_ddl.sql [data] | outside_function_body | 0 | 1617 | 1620 | 36.817 |
| st8f | tests/fixtures/optimizer/isolate_table_selects.sql [data] | non_python_or_fixture_change | 0 | — | 1620 | 36.817 |

The 24 all-test fallbacks accounted for **883.608 simulated seconds**. Ranked by Stage 4 cost:

| Rank | Root cause | Classification | Changes | Seconds |
| ---: | --- | --- | ---: | ---: |
| 1 | No resource reader index | Missing dependency evidence | 8 | 294.536 |
| 2 | Structural or initialization changes | Uncertain behavior beyond the import graph | 5 | 184.085 |
| 3 | Repeated names and an adjacent method comment | Scope analysis defect | 4 | 147.268 |
| 4 | Child process traces without owning tests | Missing dependency evidence | 3 | 110.451 |
| 4 | Module-level or mixed-file edits outside a body | Uncertain behavior beyond the import graph | 3 | 110.451 |
| 6 | Body of a decorated method | Blanket treatment of potentially dynamic decorators | 1 | 36.817 |

The priorities were resource readers, process-owning cohorts, and better scope pairing. The import audit also supported narrowing simple declarations in independently collected test modules. Changes to production imports, registration, inheritance, class headers, defaults, executable initialization, and unknown decorators retain all-test fallback. Even for imports with a small or empty static cohort, runtime registration, re-exports and transitive shared state remain possible.

## Evidence and policy

The resource manifest was derived solely from clean revision `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. The access-only run reused the Stage 3 pytest context plugin on the pinned Linux amd64 Python 3.13.18 and pytest 9.2.0 image. All **1,620 numbered tests and 25,440 subtests passed**, with one declared skip, in **93.92 seconds** as reported by pytest. No line tracing was run. The source was mounted read-only, its checkout was clean, and the only evaluation input mounted was the official test manifest.

The source audit identified `tests/helpers.py` as the shared SQL fixture loader. It opens the exact path and streams parsed test cases. Some callers pass dynamically constructed paths through optimizer helpers. The executor loads SQL and compressed CSV into class state during setup and also uses DuckDB views. The transpiler and serializer share a resource. The JSONPath tests open a JSON resource directly. Attribution comes from observed access in the calling test, or from all known consumers when pytest owns the access through setup or teardown. SQL fixture files are resources. Pytest fixtures are execution contexts that can own resource reads.

The access hook records Python opens and directory/glob events, separates collection and other shared phases, and starts in spawned Python interpreters. The full run produced 62 hashed resource records, five directory records with unresolved collection ownership, and a conservative child-process cohort of 340 identities. The cohort uses launch events, each process-pool submission, and the complete test files or classes with observed or source-identified owners. This accounts for worker reuse across tests. Child reads, if observed, inherit the entire supported owner cohort. No child resource reads were observed in this clean run. Native I/O can bypass Python audit events. The executor's native CSV data paths also go through Python loaders during setup. This is evidence of readers, with no claim of an exhaustive file dependency graph.

Existing resource content changes use their resolved readers and class cohorts. Directory membership remains the same for these edits. Removal includes relevant directory records and falls back if an enumerator is unresolved. Unknown, added, and renamed resource paths retain all-test fallback. The policy never infers safety from a missing read. Build-time extraction verifies observed resource hashes against files from the pinned archive. Runtime verifies the exact base resource and the patch context before using its reader cohort.

Repeated scopes are paired by qualified name and source occurrence, guarded by unchanged surrounding AST shapes and headers. An indented comment immediately preceding a method attaches to that method and uses its coverage. Existing ordinary `property`, `classmethod`, and `staticmethod` bodies can use body coverage. Dynamic decorators retain all tests. A structural edit in a known test module can use its own file and reverse-import cohort when the modified declarations are limited to inert bindings and ordinary test class members. Changed imports, inheritance, decorators, defaults, and arbitrary initialization retain all tests. Process-owned lines union the supported process cohort with ordinary coverage. Unsupported or unresolved shared execution retains all tests.

The selector still analyzes each patch against the immutable base, unions every changed file or scope, resolves canonical identities against the incoming manifest, and uses the existing scheduler. Diagnostics stay on stderr. The original coverage index, official scorer, and sample files are preserved.

## Reproduction

Run from the repository root with the clean Stage 3 checkout and official sample manifest available.

```sh
sh tools/resources/run.sh
python3 tools/evaluate_stage5.py
```

The resource exporter takes the clean Git checkout, manifest, and recorded access directory. It emits sorted canonical identities, file hashes, context ownership, and provenance. The output can be regenerated from the saved clean trace without running pytest again.

```sh
python3 tools/resources/export.py .local/coverage-final/sqlglot sample/tests.json \
  .local/stage5/access coverage_index/resources.json
```

The Stage 4 runtime checkpoint and build files are under `checkpoints/stage4/`. The evaluator builds that checkpoint using its original three coverage artifacts. It runs the official Docker targets, the focused checks, and three Linux CPU measurements per selector with unchanged Makefile runtime flags. Patch generation, patched trees, predictions, failure sets, and reports for independent validation remain under ignored `.local/stage5/independent/`. They are outside the submission image.

## Official sample comparison

| Measurement | Stage 4 checkpoint | Stage 5 |
| --- | ---: | ---: |
| Simulated cost | 916.871 s | **617.271 s** |
| Missed changes / missed failing tests | 0 / 0 | **0 / 0** |
| Penalties | 0 s | **0 s** |
| All-test fallbacks | 24 / 30 | **8 / 30** |
| Total test appearances across the batch | 39,896 | **18,814** |

Savings are **299.600 seconds (32.676%)**. The frozen candidate passed all 33 focused checks, `make check`, and `make sample` through Docker Desktop. The classes of fallbacks and their savings are below. Rows attribute the full measured change in cost to the original blocking reason. Mixed mechanisms are called out so their contributions are counted once.

| Stage 4 fallback | Before | After | Savings | Mechanism |
| --- | ---: | ---: | ---: | --- |
| Non-Python or fixture change | 8 | 0 | 193.688 s | Resource reader evidence and class cohorts |
| Structural or initialization change | 5 | 5 | 0 s | Production structure remains conservative |
| Outside function body | 4 | 3 | 34.809 s | Adjacent method comment routed through body coverage |
| Ambiguous source scope | 3 | 0 | 33.651 s | Repeated scope pairing, plus the process cohort on two changes |
| Shared process execution | 3 | 0 | 28.089 s | Process owners plus ordinary line coverage |
| Decorated or cached function | 1 | 0 | 9.363 s | Built-in property body plus the process cohort |
| **Total** | **24** | **8** | **299.600 s** | |

The eight remaining fallbacks cost **294.536 s** at 36.817 s each. They are five structural changes (`4d63`, `535z`, `6ze8`, `gbav`, `ktz3`) and three multi-file changes with a module-level edit (`986c`, `bvw2`, `rszg`). The next highest cost is 36.426 s for `ary6`, which schedules 1,183 tests. These decisions reflect import-time initialization, registries, inheritance and shared state that the current evidence cannot safely narrow.

## Independent evaluation protocol

The candidate runtime and maps were hashed and the Docker image ID was saved before generating seven local mutations at paths absent from the public sample changes. The frozen image generated all predictions before label generation. The local validation map contains no public sample labels. Each patched tree starts from the clean revision and runs in a fresh network-disabled Linux amd64 container using the pinned dependencies. To keep parallel labeling within the local VM capacity, each container uses two dedicated virtual CPUs. The official manifest has 1,620 numbered entries and one declared skip.

The labeler uses pytest phase and subtest reports, continuing collection for the remaining files after an import error. A failed subtest marks its parent numbered test. A file collection/import error marks every numbered identity in that file. Signal-based pytest-timeout records a test failure if the offline 600-second limit is reached. The published rules give no per-test threshold for reproducing server timeouts, so that limit is an offline safeguard. Missing reports, unexpectedly skipped numbered tests, ambiguous identities, unattributed collection errors, or an interrupted suite mark the result inconclusive. The raw data and the numbered failure sets remain outside Git.

The saved freeze manifest is `.local/stage5/frozen.sha256`. The predictions SHA-256 is `f96d5c82f904282228920689a947cd6b2c966fd522889f4edb4cfb362a87ace7`. The local label driver runs `tools/stage5_label.py` against each prepared tree. The comparison reads the labels only after prediction and uses the official local scorer once all seven cases are complete.

```sh
shasum -a 256 -c .local/stage5/frozen.sha256
sh .local/stage5/independent/run-labels.sh
python3 .local/stage5/independent/compare.py
```

A synthetic labeling check exercised both a recorded timeout and rejection of a missing teardown report. A sample or independent run that contains no timeouts provides no empirical evidence about how this selector handles changes that cause a timeout.

| Independent change | Coverage decision | Selected | Failing numbered tests | Missed | Complete |
| --- | --- | ---: | ---: | ---: | --- |
| File import error | All tests for changed import | 1,620 | 3 | 0 | Yes |
| Invalid JSONPath resource | Resource readers and class cohort | 6 | 1 | 0 | Yes |
| Removed partial SQL resource | All tests for unresolved directory enumeration | 1,620 | 1 | 0 | Yes |
| Changed pretty-print expectation | Resource readers and class cohort | 28 | 1 | 0 | Yes |
| Optimizer body used by a process pool | Body coverage and process owner cohort | 389 | 4 | 0 | Yes |
| Added and used test-class constant | Test file and reverse import cohort | 11 | 1 | 0 | Yes |
| Removed test helper | All tests for uncertain declaration effects | 1,620 | 3 | 0 | Yes |

All seven runs accounted for every numbered test. The frozen selector caught **14 failing numbered tests** with **zero misses and zero penalties**. The official local scorer computed 144.501 simulated seconds for this separate seven-change set. In the process-pool case, pytest reported 21 failed subtest events, representing four numbered parent tests. The suite contained no actual timeout. Recorded container test windows ranged from 91.179 to 130.393 seconds. The first six suites ran in groups of three, so these elapsed times also reflect concurrent labeling.

## Open gaps

The process cohort is broad and identifies owning tests rather than exact tasks within a reused worker. A previously unseen launch path or native resource read can evade Python access tracing. Dynamic registrations, unexecuted source branches, production inheritance changes, and cross-module mutable state still limit safe selection. Resource additions, renames, and unresolved directory membership changes remain fallback cases. The independent set exercises several routes on paths outside the public sample, while unseen server mutations can have other dependencies.

## Container CPU and repository size

The CPU comparison was repeated after all labeling containers stopped. These snapshots come from Linux cgroup v2 `cpu.stat` inside the container, with the selector run by the instrumented process and the same Docker Desktop sandbox controls at both stages. The timer includes interpreter startup and the wrapper up to the snapshot. It ends before shutdown. These are local Linux amd64 measurements under ARM64 emulation. Server CPU accounting may differ.

| Selector | CPU snapshots, seconds | Median |
| --- | --- | ---: |
| Stage 4 checkpoint | 2.678548 / 2.710010 / 2.650977 | **2.679 s** |
| Stage 5 | 3.062820 / 3.165785 / 3.062399 | **3.063 s** |

In the repeat comparison, `make check` took 3.504 seconds of host wall time, `make sample` took 3.414 seconds, and the focused Docker check took 0.484 seconds. All commands exited successfully. Every metered run reproduced its selector's sample stdout byte-for-byte.

The new resource map is **187,612 bytes**. Its SHA-256 is `57a736965d9085254abecf50471f26c2c6987bd4d0923ba19cde722705d3ea38`. Re-export from the saved clean trace produced identical bytes. The final audit examined Git-included files, including untracked submission files, and found approximately **4.93 MB**, below the 20 MB limit. The audit also verified the pinned resource hashes, selector and scheduler checkpoint, original index, scorer, rules, and sample fixtures. The exact size is recorded in `.local/stage5/final-audit.json`.
