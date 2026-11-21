# Stage 11 selection precision

The baseline is the published Stage 10 commit `85e2da65e97a7cb22c68e94e874ccd9e34a82297`, which
scored 419.446 simulated seconds on the local public sample. All preprocessing uses the clean
pinned sqlglot revision `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. Local sample seconds, local
container CPU and organizer-reported scores are three separate quantities and are never mixed.

## Frozen comparator

The Stage 10 image was rerun before any edit. It reproduced **419.446 simulated seconds, zero
missed changes, 30 protocol lines and 57,758 bytes**, with output SHA-256
`21938c5755f6c964ba469e3079faebbf5a2175e54ad48d8cb73d7d97ce23da7e`, matching the accepted Stage 10
record. That per-change table is the comparator for every measurement below. No development
measurement reads `sample/answers.json`; the scorer and the regression checker read labels only on
the host, after the containers exit.

## Results

| Evaluation | Stage 10 | Stage 11 | Note |
| --- | ---: | ---: | --- |
| Public sample simulated s | 419.446 | **394.212** | −25.234 s, −6.02% |
| Public sample test selections | 10,572 | 8,725 | three fallbacks unchanged |
| Public sample missed changes / tests | 0 / 0 | **0 / 0** | |
| Median container CPU s (same two VM CPUs) | 1.961 | 1.932 | medians of three |
| 59 preserved cases, simulated s | 1,434.955 | **1,420.817** | −14.138 s |
| 59 preserved cases, missed changes / tests | 0 / 0 | **0 / 0** | 270 failing occurrences |
| Protocol output bytes | 57,758 | 48,566 | 2 MB cap |
| Committed Git blob bytes | 5,998,183 | 6,013,615 | 13,986,385 free under 20 MB |
| Focused tests | 55 | 70 | |

## Class widening scoped to the recorded risk kind

`tools/class_evidence.py` raised `method_decorator` for any test-method decorator whose bare name
fell outside the inert skip set, and it computed that name with `dotted()`, which returns an empty
string for an `ast.Call`. Every parameterized skip, written `@unittest.skipIf(...)`, therefore
escaped the inert set and flagged its whole class as coupled. The pinned tree holds 27 test-method
decorator sites: 13 `patch` / `mock.patch` calls each with one constant string target, 9 skip-family
calls, and 5 bare `classmethod` on lifecycle hooks.

The generator now resolves a decorator through its call and classifies it as `inert`, `call_scoped`
or `unknown`, records per-method detail in a new `class_methods` section, and raises the risk only
for a non-inert decorator. `patch(target)` with exactly one constant string argument and no keywords
is `call_scoped`: it resolves and restores one module attribute around its own call, so it couples
its own method to the patched module rather than to its siblings.

At selection time a class whose risk set is exactly `{method_decorator}`, and which carries no
`unknown` decorator, widens a narrowed seed to that seed plus the class's patch-decorated methods.
Every other recorded risk keeps the complete class cohort: `class_write`, `class_state`,
`dynamic_class`, `dynamic_mutation`, `shared_class_lifecycle`, `shared_module_lifecycle`,
`nonlocal_binding`, `shared_pytest_fixture`, `unresolved_class_base` and an unknown class. An
artifact without `class_methods` keeps the complete cohort too, so an older map cannot silently
narrow anything.

Risk sets changed for ten classes and in only two ways: seven classes whose sole signal was a
parameterized skip or a lifecycle `classmethod` dropped to no recorded coupling, and three classes
kept their stronger state risks while losing the spurious decorator flag. Six classes retain
`method_decorator` with per-method detail, of which `TestOptimizer` and `TestTranspile` still widen
completely because they also carry `class_write` or `class_state`.

| Change | Stage 10 s | Stage 11 s | Tests | Class leave-one-out in the Stage 10 audit |
| --- | ---: | ---: | --- | ---: |
| `rszg` | 36.817 | 27.454 | 1,149 → 834 | 9.363 |
| `ary6` | 35.180 | 27.454 | 893 → 465 | 7.726 |
| `fryt` | 4.758 | 2.181 | 187 → 5 | 2.585 |
| `2qn5` | 5.086 | 2.544 | 189 → 7 | 2.550 |
| `9u5k` | 4.186 | 2.176 | 156 → 5 | 2.010 |
| `bvw2` | 3.127 | 2.206 | 77 → 7 | 0.929 |
| `986c` | 13.725 | 12.907 | 402 → 180 | — |
| `j6uz` | 12.920 | 12.754 | 239 → 169 | 8.521 |
| `2haz`, `3utz`, `535z` | unchanged | unchanged | fewer tests, same cost | 0.000 |

Each realized saving matches its recorded leave-one-out figure. The `j6uz` saving is small because
its busiest test belongs to `TestOptimizer`, which keeps complete widening, and `2haz`, `3utz` and
`535z` do not move because direct or process evidence already holds their busiest test. On `rszg`
the class and position reasons form a chain, so that 9.363 s is realized once and must not be added
to a position saving.

Regenerating `class_evidence.json` changes its hash, and `SelectionPolicy.__init__` discards all 998
declaration routes unless `declarations.json` carries a matching `class_evidence_sha256`, so both
artifacts were re-exported together. Each export is byte-identical on a repeat run from the same
inputs, the index, trace and source-inspection bindings are unchanged, and the 998 routes are
unchanged in content.

## Prose edits keep the narrow route and gain position observers

A standalone prose insertion outside the leading-import gap took the enclosing-body route and
received no source or position evidence at all, even though the file's bytes change and every later
definition shifts its first line. Stage 9's `new-position-reader` case is the recorded proof that
this failure mode is real: it failed because `co_firstlineno` changed.

Routing those files through the Stage 9 observer and shifted-execution cohort instead was built and
measured, then rejected: it cost **37.434 more** simulated seconds on the sample, because the
enclosing-body cohort is narrower than execution from the first shifted line to end of file. The
released behavior keeps the body route and unions only the file's recorded source and position
observers, which costs **0.889 s** on the sample and closes the gap. An unresolved observer record
for the path still falls back. The break-even miss probability for the added cost is 0.889 / 300,
about 0.3%.

| Change | Stage 10 s | Observer route s | Released s | Tests |
| --- | ---: | ---: | ---: | --- |
| `bap8` | 2.042 | 27.454 | 2.674 | 1 → 35 |
| `9u5k` | 2.176 | 13.397 | 2.307 | 5 → 10 |
| `f4xa` | 2.005 | 2.806 | 2.131 | 1 → 5 |

The `9u5k` figures are measured after the class increment.

## Two measured dead ends

**The scheduler is already optimal on this sample.** For every one of the 30 changes the emitted
partition equals `min over k of (max(longest test ms, ceil(total ms / k)) + 2000k)`, the busiest
worker's unavoidable load plus the official per-worker overhead. The measured gap is **0.000 s**, so
no partition search was added and no deterministic work limit was needed.

**Static attribute-read analysis cannot narrow two of the three structural fallbacks.** A
`literal_container` declaration family would admit the edits, but the route cohort is the union of
coverage over the sites that read the binding, and those reads happen in generic base-class code:

| Change | Binding | Reference sites | Route cohort | Verdict |
| --- | --- | ---: | --- | --- |
| `4d63` | `Snowflake.Tokenizer.NUMERIC_ESCAPES` | 4 | 1,570 / 1,620 tests, 95.844 s | no saving; `Tokenizer._init_core` at `sqlglot/tokens.py:606` alone covers 1,564 tests |
| `ktz3` | `TriggerProperties.arg_types` | 19 | 1,489 / 1,620 tests, 95.609 s | no saving; `Expression.error_messages` at `sqlglot/expressions/core.py:1317` alone covers 1,471 tests |
| `gbav` | `SingleStoreParser.SHOW_PARSERS` | 7 | **37 / 1,620 tests, 0.087 s** | the one remaining large target |

Both unroutable cohorts still contain the 28.817-second `TestParser.test_max_nodes`, so their cost
stays at 36.817 s whether 1,489, 1,570 or all 1,620 tests are scheduled. Reaching them needs a
different evidence kind, such as per-test class-usage attribution, not a wider declaration family.

## What is not released

`gbav` is worth about 34.7 s on the sample and is specified but unreleased. Its dict values are
calls to the module-local `_show_parser` factory evaluated at class creation, and the same dict feeds
`SHOW_TRIE = new_trie(key.split(" ") for key in SHOW_PARSERS)`, which iterates keys only and is
therefore insensitive to a value-only edit. Promoting it needs a pure-factory admission rule, the
`key_only` versus `value_observing` classification of initializer reads, and its own fresh positive
failing case. It is not narrowed today.

Also unreleased: the supported-empty outcome and the strict unreachable-path family, which measured
**0.000 s** of local sample headroom, and any selector CPU work, which at 1.932 s per 30-change
batch is about 0.5% of the score.

## Validation performed and validation still owed

Performed: the frozen Stage 10 comparator; per-change cost and selection comparison with zero
changes worsened; the 59 preserved independent and regression cases from Stages 5, 7, 8, 9 and 10,
every one with container exit 0, `complete == true` and `numbered_count == 1620`, replayed against
their stored labels with **270 failing numbered occurrences and zero misses**, including
`cached-class-setup` (60 failing, 60 selected), `shared-resource-setup` (61 failing), both
`new-position-reader` runs, `worker-reuse`, `worker-initializer`, `serialization-restore`,
`init-derived-calendar`, `decorator`, `inheritance`, `removed-override`,
`added-inherited-override`, `shared-transform-mapping` and `file-import-error`; 70 focused tests;
median-of-three container CPU on the same two VM CPUs; and exact-tree verification, meaning
`git archive` of the candidate commit, an uncached `linux/amd64` build, byte-identical
`make -o build check` and `make -o build sample`, a byte-identical repeat run, and the focused tests
inside the exact image.

Still owed before a submission, per the project's own release gate: fresh independent positive
failing cases produced after a prediction freeze, specifically at least one mutation whose failures
land inside a `method_decorator`-only class and one that fails inside a `patch`-decorated method;
and the public-ref push plus anonymous clone check. A replay against preserved labels is weaker
evidence than a fresh case, because every one of these patches was already available when the policy
was written.
