# Stage 7 selection precision

The submitted Stage 6 commit was `38ce56f56dedf739c4f2fed2207253b57e12f6b0`. Its reported competition score was **824.2 s** including server CPU, with **816.696 s simulated** and zero missed changes in all three runs. The measurements below use the separate public sample and locally labeled cases.

## Opportunity audit

Before changing the policy, a development evaluator ran the Stage 6 selector with a hook that recorded its selection immediately before class expansion. Only after that run did the evaluator load the sample answers. The reference schedules exactly the labeled failing tests with the existing scheduler. It provides an oracle reference for this scheduler and these labels, without proving optimal scheduling.

The submitted policy cost **617.271 s** on the sample versus **94.351 s** for the reference, a **522.920 s** gap. Class expansion accounted for **119.102 s** and **3,641** additional test appearances. Unconditionally removing that expansion on this sample would give 498.169 s with no misses. That was an audit, not a candidate. Shared setup, cached resources, and state can introduce dependencies that appear in only one trace context.

| Selection mechanism | Excess over reference, s | Added by class expansion, s | Added test appearances |
| --- | ---: | ---: | ---: |
| structural or initialization change | 179.488 | 0.000 | 0 |
| body + process owners | 118.406 | 8.972 | 1,078 |
| outside function body | 100.297 | 0.000 | 0 |
| resource readers | 82.948 | 82.948 | 1,328 |
| body coverage | 41.781 | 27.182 | 1,235 |


| Change | Stage 6, s | Reference, s | Excess, s | Class expansion, s | Tests before → after expansion |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2haz | 27.454 | 0.000 | 27.454 | 0.000 | 398 → 568 |
| 2jrq | 27.454 | 25.454 | 2.000 | 0.000 | 342 → 342 |
| 2qn5 | 6.119 | 0.000 | 6.119 | 3.583 | 6 → 341 |
| 2vdj | 12.606 | 2.083 | 10.523 | 10.523 | 1 → 167 |
| 3utz | 27.454 | 25.454 | 2.000 | 0.000 | 352 → 487 |
| 4d63 | 36.817 | 0.000 | 36.817 | 0.000 | 1620 → 1620 |
| 535z | 36.817 | 2.596 | 34.221 | 0.000 | 1620 → 1620 |
| 5y72 | 27.454 | 0.000 | 27.454 | 0.000 | 340 → 340 |
| 66ks | 27.454 | 0.000 | 27.454 | 0.000 | 340 → 340 |
| 6vvp | 12.606 | 2.037 | 10.569 | 10.569 | 1 → 167 |
| 6ze8 | 36.817 | 2.001 | 34.816 | 0.000 | 1620 → 1620 |
| 8y7j | 2.708 | 0.000 | 2.708 | 0.677 | 1 → 73 |
| 986c | 36.817 | 2.329 | 34.488 | 0.000 | 1620 → 1620 |
| 9u5k | 4.774 | 0.000 | 4.774 | 2.598 | 5 → 177 |
| ary6 | 36.426 | 4.382 | 32.044 | 8.972 | 410 → 1183 |
| bap8 | 2.093 | 0.000 | 2.093 | 0.051 | 1 → 8 |
| bj7g | 12.778 | 2.011 | 10.767 | 9.131 | 3 → 209 |
| bvw2 | 36.817 | 2.061 | 34.756 | 0.000 | 1620 → 1620 |
| egys | 12.606 | 2.596 | 10.010 | 10.010 | 1 → 167 |
| f4bn | 12.606 | 2.007 | 10.599 | 10.599 | 1 → 167 |
| f4xa | 2.008 | 0.000 | 2.008 | 0.003 | 1 → 3 |
| fryt | 4.791 | 0.000 | 4.791 | 2.618 | 4 → 208 |
| gbav | 36.817 | 0.000 | 36.817 | 0.000 | 1620 → 1620 |
| gbhk | 12.606 | 2.061 | 10.545 | 10.545 | 1 → 167 |
| j6uz | 12.920 | 4.399 | 8.521 | 8.521 | 2 → 239 |
| ktz3 | 36.817 | 0.000 | 36.817 | 0.000 | 1620 → 1620 |
| mthh | 12.606 | 3.016 | 9.590 | 9.590 | 1 → 167 |
| nwnx | 12.606 | 2.092 | 10.514 | 10.514 | 1 → 167 |
| rszg | 36.817 | 5.764 | 31.053 | 0.000 | 1620 → 1620 |
| st8f | 12.606 | 2.008 | 10.598 | 10.598 | 1 → 167 |


## Selection changes

- Class expansion uses clean-source lifecycle hooks, resolved bases, mutable class bindings, dynamic decorators and writes, and the existing clean fixture trace. Stateless classes can retain individual coverage. Unknown class evidence still widens. The existing fixture-consumer and process-owner cohorts stay in place. Pytest creates a unittest class wrapper even for inherited no-op hooks, so a wrapper alone does not establish shared state. The generated evidence covers 58 classes, of which 41 have no detected coupling.
- A resource edit can stay with its direct readers if every observed open is attributed to an individual call and it changes the contents of an existing SQL or JSON file. Changed fixture metadata and lines with state-changing SQL keywords retain the class guard. File membership changes and unresolved readers retain existing conservative behavior. In particular, the optimizer's raw SQL fixtures are read during individual calls, while its shared class setup handles the connection and worker pool. The executor's class-loaded resources still carry the complete fixture consumers.
- Statement precision accepts observed single-line replacements of same-type literal returns or plain local assignments. It also accepts an observed standalone pass removal if the surrounding function survives the edit. It excludes async and decorated bodies. Insertions, condition changes, structural edits, and statements that lack old coverage still use enclosing coverage or the existing fallback. Shared contexts and known source-inspection test files are included when choosing statement precision.
- Import graph work that only explains a fallback is now opt-in through `SelectionPolicy(..., diagnostic_imports=True)`. Reverse dependencies are still calculated when a supported test-source change uses them for selection. The same scheduler and runtime sandbox apply.

The committed class evidence can be regenerated from the clean Stage 3 trace, without running changed tests or reading labels.

```sh
python3 tools/class_evidence.py .local/coverage-final/sqlglot \
  .local/coverage-final/raw/full/run.json coverage_index/index.json \
  coverage_index/class_evidence.json
```

Re-export produced identical bytes. Class coupling detection is static and cannot prove independence from all mutable state. The resource keyword guard is deliberately lexical and cannot resolve every possible SQL side effect. Source inspection outside the detected readers, native I/O, unobserved fixture accesses, and test ordering remain open risks. The production structural and outside-body fallbacks still account for eight sample changes.

## Independent validation

Each policy was frozen before predictions were written for the independent patches. All four variants predicted the same case set before any test outcomes were read. The extra Spark case was added while the original inserted optimizer branch was slow. The original later completed and remains in the results. The confirmation run used the pinned Linux amd64 pytest image and the Stage 5 report classifier. Every complete case accounted for each of the 1,620 numbered identities. Collection failures map to the numbered identities in the failed file, and failing subtests map to their parent test. The classifier uses a 600-second signal-based test timeout and treats incomplete collections as inconclusive.

| Independent case | Accounted for | Failing numbered tests | Combined misses |
| --- | ---: | ---: | ---: |
| bounded inserted branch | 1,620 | 4 | 0 |
| cached class setup | 1,620 | 60 | 0 |
| companion class tests | 1,620 | 3 | 0 |
| decorator | 1,620 | 1 | 0 |
| direct sql | 1,620 | 1 | 0 |
| global initialization | 1,620 | 0 | 0 |
| inheritance | 1,620 | 2 | 0 |
| inserted branch | 1,620 | 4 | 0 |
| literal nested branch | 1,620 | 1 | 0 |
| literal return | 1,620 | 3 | 0 |
| mixed files | 1,620 | 6 | 0 |
| shared resource setup | 1,620 | 61 | 0 |
| two direct readers | 1,620 | 2 | 0 |

**All 13 cases completed**, with **148 failing numbered tests** and **zero missed tests or changes in all four variants**. The global initialization case produced zero failing tests. The inserted optimizer branch took about 341 seconds under emulation and produced four failing parent tests. All generated patches and reports stay in ignored local storage.

| Policy | Independent simulated s | Test appearances | All-test fallbacks | Missed changes / tests | Penalty s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Submitted policy | 279.492 | 8,602 | 4 | 0 / 0 | 0.000 |
| Conditional classes | 260.793 | 7,907 | 4 | 0 / 0 | 0.000 |
| Statement precision | 269.248 | 8,237 | 4 | 0 / 0 | 0.000 |
| Combined | 250.815 | 7,635 | 4 | 0 / 0 | 0.000 |

## Public sample ablations

The combined candidate saved **96.990 s (15.713%)** against the submitted policy on the same 30 cases. It selected 2,199 fewer test appearances. Each ablation uses the existing scheduler. The submitted policy retains the old fallback diagnostics. All three alternatives use the cheaper diagnostics path, so the CPU comparison includes that change.

| Policy | Simulated s | Test appearances | All-test fallbacks | Missed changes / tests | Penalty s | Median local CPU s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Submitted policy | 617.271 | 18,814 | 8 | 0 / 0 | 0.000 | 2.779 |
| Conditional classes | 530.601 | 16,778 | 8 | 0 / 0 | 0.000 | 1.688 |
| Statement precision | 607.134 | 18,651 | 8 | 0 / 0 | 0.000 | 1.713 |
| Combined | 520.281 | 16,615 | 8 | 0 / 0 | 0.000 | 1.746 |

Conditional class expansion alone saved 86.670 simulated seconds. Statement precision alone saved 10.137 seconds. Applying statement precision after conditional classes saved 10.320 seconds. The class and body improvements both preserved full recall on the sample and independent sets.

CPU estimates are the median of three snapshots from `/sys/fs/cgroup/cpu.stat` taken inside the Linux amd64 Docker container under ARM64 emulation. The snapshots include interpreter startup and the measurement wrapper up to the snapshot. The ablation wrapper only changes the two policy options and records the CPU estimate. All repeated runs produced byte-identical outputs per policy. The server uses its own hardware and accounting.

Validation uses the official `make check` and `make sample` targets with public data mounted separately from the commit. The 38 focused tests cover the class and resource guards, observed and unobserved statements, shared contexts, new branches, and the diagnostics path. The clean-image inventory contains about 16.69 MB of pinned source, resources, and maps. The committed tree is about 4.95 MB. Evaluation patches, test outcomes, raw traces, and measurement output are excluded from the submission image.
