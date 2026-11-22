# Stage 9 comment dependencies

The comparison starts from Stage 8 commit `af4065a2651dcec895654f766408ef917f9c447f`. All measurements here are local. The clean source is sqlglot `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`.

## Audit of the three sample fallbacks

Stage 8 reported `outside_function_body` at the first Python file in each patch. Each was an existing module with a new comment between complete top-level imports. Stage 8 selected all 1,620 tests and cost 36.817 simulated seconds on each patch.

| Change | Module comment | Companion edits preserved by selection | Stage 9 tests | Stage 9 seconds |
| --- | --- | --- | ---: | ---: |
| `986c` | `dialects/singlestore.py` after the first import | An inserted comment inside `_annotate_median` in `typing/snowflake.py` and an invalid token in the `unnest_subqueries.sql` input | 462 | 27.454 |
| `bvw2` | `dialects/materialize.py` between the future import and `Postgres` import | A broken expected type in `annotate_types.sql` | 77 | 3.127 |
| `rszg` | `optimizer/scope.py` between `exp` and `OptimizeError` imports | Boolean condition change in `_annotate_within_group` in `typing/snowflake.py` and an invalid CTE in `qualify_columns_ddl.sql` | 1,149 | 36.817 |

The last case keeps the 28.817-second parser node-limit test via its broad coverage cohort. The best four-worker schedule still costs 36.817 seconds. The other two cases save 9.363 and 33.690 seconds respectively.

## Evidence and routing

The offline audit runs the clean numbered manifest using the existing pytest phase and fixture contexts, with an audit hook for raw source opens and code-object, frame, and traceback access. Ordinary CPython import-loader reads are distinguished from reads that can inspect the source. Child events retain child attribution. The exporter uses the existing clean process-owner set and skips only identities recorded as explicitly skipped in the official manifest. A remaining unattributed test, collection, or fixture access is recorded for its path.

The baseline had 1,620 passing numbered tests, 25,440 passing subtests and one official unnumbered skip. It took approximately 80 seconds inside the Linux amd64 pytest image. The audit recorded 1,901 distinct events across contexts, including 14 explicit production-source reads by the typing metadata test. The Snowflake typing file has both a raw-source and code-object observer. Two optimizer tests observed traceback frames from the scope module. The index holds attributed cohorts for 71 paths and marks 11 paths with unresolved contexts. A separate scan of the pinned Python source records relevant observer syntax. It adds four numbered tests from eight static sites and identifies two standalone tooling sites with no measured test execution. There were zero unresolved static sites inside the exercised source and test roots.

The runtime accepts only insertions of standalone prose comment tokens between complete leading top-level imports in an existing production Python file. Removing exactly those inserted lines must reproduce the original bytes. The guard compares UTF-8 source encoding and the parsed structure with type comments enabled. The import-gap token and byte checks exclude strings, inline comments, comments in continuations, control directives, shebangs, deletions, replacements, and docstring changes. A same-file comment plus behavioral change stays on the existing fallback path when its module edit is outside a supported body. The classifier uses the same rule for every indexed path, with evidence derived independently of evaluation outcomes.

For an accepted comment file, the selector adds direct and static source or position observers, and clean execution cohorts from the first shifted old line onward. It handles shared fixtures and process owners through the existing evidence. For successful Stage 8 companion edits, it retains the ordinary behavior and fixture selections and unions the observers of all changed Python source. Any companion line-count changes add shifted execution cohorts. Companion edits to test Python files, docstrings, or recognized observer and directive syntax fall back. The map is checked against the pinned revision, index, resources, and manifest hashes. Existing test ID resolution and worker scheduling apply after the union.

Collection-time line coverage alone includes module definitions and import execution. The positional cohort therefore uses the explicit observation audit to gate collection effects. Unresolved collection observers on a changed file force all tests. Known ordinary imports still contribute through other clean execution, fixture, and process evidence. This does not model unobserved native reads, private loader internals, arbitrary Python reflection, or a tool added outside the audited environment. The leading-import restriction keeps these assumptions narrow. The measurements below establish observed recall for these cases.

Reproduce the clean audit using the Stage 3 checkout and pinned pytest image:

```sh
mkdir -p .local/stage9/trace
docker build --platform linux/amd64 -f tools/coverage/Dockerfile -t blast-radius-coverage .
docker run --rm --platform linux/amd64 --network none --cpuset-cpus 0,1 --cpus 2 \
  --memory 3072m --memory-swap 3072m --pids-limit 256 --read-only --tmpfs /tmp:rw,size=512m \
  --env PYTHONHASHSEED=0 --env OPENBLAS_NUM_THREADS=1 --env OMP_NUM_THREADS=1 \
  --env MKL_NUM_THREADS=1 --env SOURCE_OBSERVATION_TRACE=1 \
  --env PYTHONPATH=/src:/source_observation:/tool:/label-tool \
  --volume "$PWD/.local/coverage-final/sqlglot:/src:ro" \
  --volume "$PWD/tools/coverage:/tool:ro" \
  --volume "$PWD/tools/source_observation:/source_observation:ro" \
  --volume "$PWD/tools/stage5_label.py:/label-tool/stage5_label.py:ro" \
  --volume "$PWD/sample/tests.json:/manifest/tests.json:ro" \
  --volume "$PWD/.local/stage9/trace:/result" \
  --entrypoint python blast-radius-coverage /source_observation/run.py
python3 -m tools.source_observation.export .local/coverage-final/sqlglot \
  coverage_index/index.json sample/tests.json .local/stage9/trace coverage_index/source_observers.json
```

The emitted map is 44,687 bytes. Re-exporting the captured events produced byte-identical output. Run the audit into an empty trace directory to avoid mixing separate runs. The raw logs, full-manifest reports and evaluation patches are excluded by Git and Docker.

## Public sample results

| Policy | Simulated seconds | Tests selected | Full-suite fallbacks | Missed changes / tests | Penalty seconds | Median container CPU seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Stage 8 | 476.228 | 13,804 | 6 | 0 / 0 | 0.000 | 2.357 |
| Stage 9 | 433.175 | 10,632 | 3 | 0 / 0 | 0.000 | 2.594 |

Stage 9 saves 43.053 simulated seconds (9.04%) and 3,172 test selections. The remaining three full-suite sample fallbacks are structural or initialization changes. The CPU estimates are medians of three `usage_usec` snapshots from `/sys/fs/cgroup/cpu.stat` after the selector returns. They include Python startup and the measurement wrapper. The Docker Desktop runs used Linux amd64 emulation on ARM64 with the official two-CPU sandbox limits and the same two VM CPUs for both policies. The comparison repeats produced byte-identical protocol outputs.

## Independent evaluation

The first batch comprised eleven fresh patches outside the public comment edit locations. Four companion edits reused a file found elsewhere in the public sample, at different changed lines. A twelfth case combined a comment in a module with a known source reader, a generator change, and a fixture edit, using only files absent from the public sample. Both policies froze predictions before labeling each batch, and the same frozen runtime served both. The first SHA-256 freeze manifest is `19aef3c0246773214e91e299fae20e6ddc022f9da7b772dd0a180bd48ffd6a04`. The second is `733ebc7b34f161a68c0f3a50619c026ea2f4fc0077b74f14b262306440cfc514`. The judging inputs and outcomes were kept in ignored local storage and the prediction container only saw patches and the numbered manifest.

Every case accounted for all **1,620 numbered tests**. Both policies selected all **19 observed failing test occurrences**. Each narrowed case caused at least one actual failure. The added line-position assertion failed when a comment shifted an existing function, and the frozen candidate used the full suite for the patch. The evaluation classifier maps subtest failures to their numbered parent, file import failures to the numbered tests in that file, and pytest timeouts to failures. The complete runs observed call and subtest failures and no collection errors or timeouts.

| Independent case | Stage 9 routing | Selected tests | Failing numbered tests | Missed tests |
| --- | --- | ---: | ---: | ---: |
| `comment-and-generator` | comment cohort plus companion selections | 191 | 3 | 0 |
| `comment-body-and-fixture` | comment cohort plus companion selections | 417 | 3 | 0 |
| `disjoint-reader-behavior-fixture` | comment cohort plus companion selections | 420 | 2 | 0 |
| `encoding-cookie` | outside function body | 1,620 | 1 | 0 |
| `format-directive` | outside function body | 1,620 | 1 | 0 |
| `known-source-reader` | comment cohort plus companion selections | 344 | 1 | 0 |
| `module-docstring` | structural or initialization change | 1,620 | 1 | 0 |
| `new-position-reader` | unresolved companion source observation | 1,620 | 1 | 0 |
| `same-file-comment-and-code` | outside function body | 1,620 | 3 | 0 |
| `two-comment-modules` | comment cohort plus companion selections | 190 | 1 | 0 |
| `type-ignore` | outside function body | 1,620 | 1 | 0 |
| `unattributed-collection` | unattributed source or position observation | 1,620 | 1 | 0 |

| Policy | Simulated seconds | Tests selected | Full-suite fallbacks | Missed changes / tests | Penalty seconds | Median container CPU seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Stage 8 | 441.804 | 19,440 | 12 | 0 / 0 | 0.000 | 0.853 |
| Stage 9 | 350.008 | 12,902 | 7 | 0 / 0 | 0.000 | 2.512 |

The combined savings across the independent cases were 20.78%. On the eight cases with wholly file-disjoint patches, cost fell from 294.536 to 221.466 simulated seconds, with full-suite fallbacks falling from 8 to 5. Both policies selected all 13 failing test occurrences in this subset. The runtime reads the same clean observer artifact for every patch. These costs use the manifest test durations and the official scheduler cost formula. The independent CPU estimates use the same method as the sample measurements.

## Exact-tree verification

The verification exports the commit with `git archive`, extracts the unmodified public sample separately, and builds the exported tree with `docker build --no-cache --platform linux/amd64`. The image inventory checks module and map hashes against the commit. The focused suite and official `make check` and `make sample` targets run against that image. The Git blob total is 5,707,849 bytes. The `/app` inventory is 17,416,518 bytes including the pinned source. The sample, scorer, and Docker build rules are unchanged. The packaged runtime receives only the manifest and patches, with networking disabled.
