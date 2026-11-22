# Stage 8 declaration dependencies

Stage 7 commit `0b4fc86b7ca431f5ba1b342b9c73c63263d54af7` was the starting point. Its reported competition result is 731.9 total seconds, 724.372 simulated seconds, and zero misses. On the local sample it scored 520.281 simulated seconds with zero misses. This report compares local runs.

## Eight-fallback audit

Each Stage 7 fallback selected all 1,620 tests and cost 36.817 simulated seconds. The reference column is the development evaluator’s score using only known failing tests and the existing scheduler. The ranking uses evidence and expected tractability alongside this reference. The reference supplies neither a runtime feature nor a guarantee that the scheduler found an optimum.

| Change | Actual edit | Stage 7 reason | Reference, s | Stage 8 treatment |
| --- | --- | --- | ---: | --- |
| `6ze8` | Read a different positional argument inside the existing `DremioParser.FUNCTIONS['REGEXP_SPLIT']` lambda | Structural or initialization | 2.001 | Deferred literal route |
| `535z` | Replace `TSQL.WEEK_OFFSET` with another negative integer | Structural or initialization | 2.596 | Class scalar route, including inherited and ambiguous reads |
| `gbav` | Change a factory argument in the `SingleStoreParser.SHOW_PARSERS` mapping | Structural or initialization | 0.000 | Fallback for changed initialization and closure construction |
| `4d63` | Edit a tuple in `Snowflake.Tokenizer.NUMERIC_ESCAPES` | Structural or initialization | 0.000 | Fallback for mutable mapping with tokenizer and metaclass dependencies |
| `ktz3` | Change a `TriggerProperties.arg_types` dictionary entry from optional to required | Structural or initialization | 0.000 | Fallback for mutable mapping feeding `Expr.__init_subclass__` |
| `986c` | Insert a module comment, insert a function comment, and corrupt a SQL fixture | Outside function body | 2.329 | Fallback for the unsupported module edit |
| `bvw2` | Insert a module comment and alter an expected SQL type in a fixture | Outside function body | 2.061 | Fallback for the unsupported module edit |
| `rszg` | Insert a module comment, change a helper condition, and alter an INSERT fixture | Outside function body | 5.764 | Fallback for the unsupported module edit |

The existing lambda ranked first among the supportable changes because its construction, signature, mapping key, and names stay identical. The integer class binding ranked second. It has a substantial process-owner cohort, which limits its savings. The other edits have opportunities if their import-time effects or textual dependencies can be established. Their reference costs alone provide no such evidence.

## Evidence and decision rules

The offline exporter reads only the pinned sqlglot tree (`eb11aec4be8cb2122afe713a4816662c3f0fb2fa`), the Stage 3 coverage index, the Stage 5 resource and process map, and the Stage 7 class evidence. It checks each indexed source file hash. No fixture outcomes or mutated trees enter the exporter.

The graph inventory records functions, classes, assignments, references, import aliases, parent-package visibility, literal dynamic imports, opaque dynamic sites, and resolved class bases. For the supported existing scalar bindings, it retains possible reads and follows imported names, re-exports, and bare derived aliases to a fixed point. For ambiguous qualified reads it retains matching spelling across the available source rather than assuming a receiver. Class owners must have a resolved inheritance path and known class creation context. Coverage at resolved consumer sites supplies canonical test cohorts. An unobserved read widens to the containing function and can fall back if that evidence is also missing. Shared fixture consumers, covered process owners, and known source-inspection tests are included.

This is a limited reverse lookup inspired by NameRTS. NameRTS follows definition edges from a name to its possible definitions and use edges from an element to referenced names until it reaches a fixed point. The exporter instead precomputes the reverse reader sets for supported bindings and resolves those cohorts at numbered-test granularity. It does not implement NameRTS's general forward worklist for arbitrary new code, nor exclude definitions solely for lack of prior execution. Opaque import and member dispatch remain limitations. The prototype records opaque sites and includes scoped ambiguous consumers or rejects them where attribution remains unresolved, rather than treating the inventory as a complete trace of dynamic execution. [NameRTS Sections 3.1–3.6](https://arxiv.org/html/2605.25356v1#S3)

The three runtime routes accept existing same-shape uppercase scalar module and class assignments, and literal substitutions on continuation lines inside already-installed mapping lambdas. The AST comparison checks binding names, value type, enclosing structure, and lambda signature and references. An exact byte-span comparison of the remaining text rejects unrelated changes including comments. Every changed binding needs a matching route. The selector unions the result with Stage 7 decisions for other files in the same patch. It reconstructs each patch against the same immutable base.

Initialization reads are barriers. In the pinned source, `_Dialect.__new__` builds forward and inverse tries, creates or aliases tokenizer, parser, and generator classes, derives escaping tables, registers dialects, and can remove entries from an aliased generator `TRANSFORMS` mapping. `_TokenizerBase.__init_subclass__` constructs quote, escape, format, and keyword lookup data. `Expr.__init_subclass__` derives `required_args` from class metadata. The exporter rejects a candidate with an initialization or registry consumer lacking a supported model. Mutable mapping edits, new declarations and added or removed overrides, unknown base resolution, and changes to registration remain all-test routes. Prior lack of execution is not used to exclude a new binding or newly exposed inherited method.

The inventory and the runtime artifact are built with:

```sh
python3 tools/declaration_evidence.py .local/coverage-final/sqlglot \
  coverage_index/index.json coverage_index/resources.json coverage_index/declarations.json \
  --audit .local/stage8/declaration-audit.json
```

The runtime reads compact, range-encoded cohorts by qualified binding and verifies the hashes of the input evidence. Test IDs resolve against the incoming manifest. The normal selector parses only changed files. The diagnostic inventory stays outside the repository.

The graph scans all 245 tracked Python files under the pinned `sqlglot/` and `tests/` directories. The shipped index contains 998 of the 1,697 audited bindings. It retains 13 module scalars, 768 class scalars, and 217 deferred mapping lambdas with usable cohorts. Its 629,352 bytes include the source revision and the hashes of the exporter and input evidence. Two exports matched byte for byte.

## Public sample results

The combined policy saved **44.053 simulated seconds (8.47%)** on the same 30 public changes, with **zero missed changes, missed tests, or penalties**. The Dremio lambda went from 1,620 tests and 36.817 s to 5 tests and 2.127 s. The TSQL class attribute went from 1,620 tests and 36.817 s to 424 tests and 27.454 s. The six remaining full-suite fallbacks contribute 220.902 s, split evenly between structural/initialization changes and module text outside a recognized body. No public case used the module scalar route. Its evidence comes from the independent cases below.

| Policy | Simulated s | Test appearances | All-test fallbacks | Missed changes / tests | Penalty s | Median CPU s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Stage 7 | 520.281 | 16,615 | 8 | 0 / 0 | 0.000 | 3.215 |
| Module scalars | 520.281 | 16,615 | 8 | 0 / 0 | 0.000 | 3.337 |
| Class scalars | 510.918 | 15,419 | 7 | 0 / 0 | 0.000 | 3.517 |
| Deferred lambdas | 485.591 | 15,000 | 7 | 0 / 0 | 0.000 | 3.411 |
| Combined | 476.228 | 13,804 | 6 | 0 / 0 | 0.000 | 3.250 |

CPU is the median of three snapshots of `usage_usec` from `/sys/fs/cgroup/cpu.stat`, taken inside the container after the selector exits its main routine. It includes interpreter startup and the wrapper through the snapshot. The runs used the official CPU, memory and sandbox limits, with the comparison pinned to the same two Linux VM CPUs. All repetitions matched the original protocol output byte for byte. Docker Desktop ran Linux amd64 under Apple Silicon emulation. These are local CPU estimates. The competition uses its own accounting and hardware.

## Independent validation

Case trees were created separately against the pinned revision. Predictions from all five policies were saved and hashed before reading any outcomes. The SHA-256 of the freeze manifest (patches and predicted worker assignments) is `81f5057605ee9f27055fbbe7d97c096494ee05b70163d2064a92231d1ea0c28c`. The hardened exporter replayed the frozen assignments byte for byte. The patches, outcomes, and evaluation wrappers stay under `.local/stage8/`, excluded by Git and Docker. During prediction only patches and the numbered-test manifest were mounted as input.

Labeling ran in the existing pinned Linux amd64 pytest image (Python 3.13.18 and pytest 9.2.0) on Docker Desktop with Apple Silicon emulation. The full-suite classifier used pytest setup, call, and teardown reports, and mapped subtest failures to the parent numbered test and file collection errors to all numbered tests in that file. It registered a 600-second signal timeout, with reported timeouts counted as failures. A missing report, unmatched collection error, skipped numbered test, or interrupted container made the case inconclusive. Only fully accounted runs enter the comparison.

**All 17 cases completed**, each accounting for all 1,620 numbered tests. The complete runs found **35 failing numbered tests** across the cases. All five policies selected every one. The complete runs had call or subtest failures and did not encounter a flagged collection error or test timeout. Earlier attempts that exited 137 were excluded and rerun with more memory. The final comparison uses only the completed runs.

| Independent case | Combined route | Selected tests | Failing numbered tests | Missed tests |
| --- | --- | ---: | ---: | ---: |
| `added-inherited-override` | full suite | 1,620 | 0 | 0 |
| `class-cast-rounding` | class scalar | 823 | 1 | 0 |
| `class-copy-keyword` | class scalar | 823 | 1 | 0 |
| `class-json-separator` | class scalar | 825 | 2 | 0 |
| `class-oracle-week` | full suite | 1,620 | 0 | 0 |
| `global-domain-dot` | module scalar | 76 | 1 | 0 |
| `global-hive-time` | module scalar | 179 | 2 | 0 |
| `global-randstr` | module scalar | 120 | 0 | 0 |
| `init-derived-calendar` | full suite | 1,620 | 5 | 0 |
| `lambda-bigquery-millis` | deferred lambda | 76 | 1 | 0 |
| `lambda-hive-json` | deferred lambda | 331 | 7 | 0 |
| `lambda-spark-array` | deferred lambda | 203 | 2 | 0 |
| `mixed-supported` | deferred lambda, module scalar | 331 | 8 | 0 |
| `mixed-unresolved` | full suite | 1,620 | 3 | 0 |
| `package-registry-alias` | full suite | 1,620 | 0 | 0 |
| `removed-override` | full suite | 1,620 | 1 | 0 |
| `shared-transform-mapping` | full suite | 1,620 | 1 | 0 |

The evaluation includes standalone positive failing cases in all three narrowed families (2 module scalar, 3 class scalar, and 3 deferred lambda). The supported mixed-file edit also produced failures, all selected by the union of its two declaration cohorts. The held-out initialization, mutable mapping, registry alias, override addition/removal, sign-shape change, and mixed unsupported edits exercised the fallback. Cases with zero failing tests only attest to completeness and routing.

| Policy | Simulated s | Test appearances | All-test fallbacks | Missed changes / tests | Penalty s | Median CPU s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Stage 7 | 625.889 | 27,540 | 17 | 0 / 0 | 0.000 | 5.121 |
| Module scalars | 526.959 | 23,055 | 14 | 0 / 0 | 0.000 | 7.905 |
| Class scalars | 597.800 | 25,151 | 14 | 0 / 0 | 0.000 | 7.826 |
| Deferred lambdas | 544.779 | 23,290 | 14 | 0 / 0 | 0.000 | 8.384 |
| Combined | 394.450 | 15,127 | 7 | 0 / 0 | 0.000 | 8.585 |

All 7 combined fallbacks were for unsupported structural or initialization changes. Independent CPU estimates use the same three-run, in-container method as the public sample. The repeats reproduced the frozen predictions byte for byte.

## Package verification

The runtime adds `declarations.py` and `coverage_index/declarations.json`. The Docker build fetches only the previously pinned and checksum-verified source; selection and scheduling run without network access. The official scorer, samples, and Makefile are unchanged.

The verification exports the candidate commit with `git archive`, imports public evaluation inputs separately, and builds the exported tree with `docker build --no-cache --platform linux/amd64`. It checks the image file inventory and hashes, runs all 45 focused checks inside Docker, and runs `make -o build check` and `make -o build sample` against that exact image. The tree remains below 20 MB (5,629,441 bytes of Git blobs). The `/app` inventory is 17,363,819 bytes including the downloaded base. Outcome labels, mutated trees, instrumentation, and raw traces are excluded.

## Remaining gaps

The static inventory cannot enumerate arbitrary reflection, native interop, or independently loaded plugins. A scoped uncertain reference widens to its observable consumers where attribution is available. Unresolved initialization effects, class relationships, registry reads, and shared contexts without a supported cohort retain the full-suite route. The matcher only tracks bare scalar aliases through initialization. It does not model general computed derivatives or update a mutable class mapping in place. Several broad process and class cohorts remain expensive. Local recall on the sample and held-out changes measures observed failures only.
