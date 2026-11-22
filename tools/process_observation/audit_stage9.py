"""Offline reason and scheduling audit of the exact Stage 9 image."""
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
from math import factorial, floor
from pathlib import Path
import sys

sys.path.insert(0, '/app')
from selection import SelectionPolicy, members
from selector import _partition_cost_ms, schedule

source = Path('/app/selection.py')
assert hashlib.sha256(source.read_bytes()).hexdigest() == '7ecbff41cde68b9dfd1c7cccb04f74b9d8f70cfe62ddcd1f6691e697b46a56cc'
tests = json.loads(Path('/data/tests.json').read_text())['tests']
baseline = {row['commit']: row['workers'] for row in map(json.loads, Path('/baseline.jsonl').read_text().splitlines())}
policy = SelectionPolicy(tests, '/app/coverage_index', '/app/base')
seconds = {t['number']: t['seconds'] for t in tests}
ms = {n: floor(s * 1000 + 0.5) for n,s in seconds.items()}
ids = {t['number']: t['id'] for t in tests}
labels = ('direct','process','position','class')
pool_evidence = Path('/pool-evidence.json')
if pool_evidence.is_file():
    pool_artifact = json.loads(pool_evidence.read_text())
    # A map is produced only after a clean, fully reconciled run.
    pool_bits = [sum(1 << i for i in tests) for tests in pool_artifact['pool_tests']]
    pool_rows = {file: {line: (mask, outside) for first, last, mask, outside in rows
                       for line in range(first, last + 1)}
                 for file, rows in pool_artifact['paths'].items()}
else:
    pool_rows = None

@lru_cache(maxsize=None)
def scheduled(numbers):
    workers = schedule(numbers, seconds)
    return _partition_cost_ms(workers, ms), workers


def audit(patch):
    added = defaultdict(int)
    widenable = defaultdict(int)
    class_bits = 0
    process_lines = defaultdict(set)
    process_context = next(i for i, entry in enumerate(policy.index['shared_contexts'])
                           if entry['id'] == 'shared:process')
    def note(reason, bits, widen=True):
        added[reason] |= bits
        if widen:
            widenable[reason] |= bits
    def trace(frame, event, _):
        nonlocal class_bits
        if frame.f_code.co_filename != str(source) or frame.f_code.co_name not in {
            'select','shared_consumers','source_and_position_cohort'}:
            return None
        if event == 'line':
            loc = frame.f_locals
            line = frame.f_lineno
            if line == 308:
                note('process', policy.identity_bits(loc['process']['tests']))
            elif line == 315:
                note('fixture', loc['consumers'])
            elif line == 329:
                note('source_observer', loc['bits'])
            elif line == 334:
                note('position', policy.sets[loc['tests']])
            elif line == 375:
                note('resource', loc['readers'], False)
            elif line == 379:
                note('resource', loc['readers'])
            elif line == 403:
                note('declaration', loc['cohort'])
            elif line == 413:
                note('test_import', loc['cohort'])
            elif line in (443,455,465):
                note('direct', policy.sets[loc['tests']])
            elif line == 458:
                note('source_observer', policy.inspection_tests)
            elif line == 472:
                note('test_import', policy.dependency_cohort([loc['file']]))
            elif line == 493:
                class_bits |= policy.class_cohort[loc['ordinal']] & ~(1 << loc['ordinal'])
            if (pool_rows is not None and line in (334,443,455,465)
                    and policy.shared_sets[loc['contexts']] & (1 << process_context)):
                if line == 334:
                    # The positional loop only binds the record's last line.
                    first = loc['_']
                    lines = range(max(first, loc['start']), loc['last'] + 1)
                elif line == 455:
                    lines = [n for n in loc['removed'] if loc['first'] <= n <= loc['last']]
                else:
                    scope = loc['scope']
                    lines = range(max(loc['first'], scope['body_start']), min(loc['last'], scope['end']) + 1)
                process_lines[loc['file']].update(lines)
        return trace
    text = patch.read_text()
    sys.settrace(trace)
    try:
        selected, info = policy.select(text)
    finally:
        sys.settrace(None)
    complete = 15
    if info['fallback']:
        added.clear()
        widenable.clear()
    def resolve(bits):
        return {policy.number_by_ordinal[i] for i in members(bits) if i in policy.number_by_ordinal}
    def coalition(mask, process_override=None):
        if info['fallback']:
            return selected
        bits = wings = 0
        for name, value in added.items():
            if name in labels and not mask & (1 << labels.index(name)):
                continue
            if name == 'process' and process_override is not None:
                bits |= process_override
                wings |= process_override
            else:
                bits |= value
                wings |= widenable[name]
        if mask & 8:
            for i in members(wings):
                if policy.class_risks.get(policy.canonical[i].rsplit('::',1)[0], ['unknown']):
                    bits |= policy.class_cohort[i]
        return frozenset(policy.mandatory | resolve(bits))
    assert coalition(complete) == selected, patch
    totals = [scheduled(coalition(mask))[0] for mask in range(16)]
    optimum, partition = scheduled(selected)
    assert partition == baseline[patch.stem], patch
    reason_by_test = defaultdict(list)
    for reason, bits in {**added,'class':class_bits}.items():
        for number in resolve(bits): reason_by_test[number].append(reason)
    for n in selected:
        if info['fallback']: reason_by_test[n].append('full_suite')
        if n in policy.mandatory: reason_by_test[n].append('mandatory')
        assert reason_by_test[n], (patch,n)
    loads = [sum(ms[n] for n in w) for w in partition]
    peak = max(loads, default=0)
    leads = sorted({n for w,load in zip(partition,loads) if load==peak for n in w},key=lambda n:(-ms[n], n))
    critical = []
    for n in leads[:4]:
        critical.append({'number': n,'id':ids[n],'ms':ms[n],'reasons':sorted(reason_by_test[n]),
                         'without_ms': scheduled(selected-{n})[0]})
    alternatives = {}
    if pool_rows is not None and added['process']:
        assert process_lines, patch
        observed = [pool_rows.get(file, {}).get(line, (0, True))
                    for file, lines in process_lines.items() for line in lines]
        for mode in ('whole_pool','known_task_only'):
            unresolved = sum(not mask or (outside and mode == 'known_task_only') for mask, outside in observed)
            candidate = added['process']
            if not unresolved:
                candidate = 0
                for mask, _ in observed:
                    for i in members(mask):
                        candidate |= pool_bits[i]
            chosen = coalition(complete, candidate)
            alternatives[mode] = {'line_count':len(observed), 'unresolved':unresolved,
                                  'selected_tests':len(chosen),'cohort_count':len(resolve(candidate)),
                                  'score_ms':scheduled(chosen)[0]}
    return dict(change=patch.stem, score_ms=optimum, makespan_ms=peak, workers=partition, loads_ms=loads,
                busiest_tests=leads, anchors=critical, reason_by_test=reason_by_test,
                reason_counts={reason:sum(reason in values for values in reason_by_test.values())
                               for reason in sorted({r for v in reason_by_test.values() for r in v})},
                overlap_process_class=len(resolve(added['process'] & class_bits)),
                fallback=info['fallback'], diagnostics=info['reasons'],
                marginal={name:optimum-totals[complete^(1<<i)] for i,name in enumerate(labels)},
                shapley={name:sum((totals[mask|(1<<i)]-totals[mask])*factorial(mask.bit_count())*
                                  factorial(3-mask.bit_count()) for mask in range(16) if not mask&(1<<i))/24
                         for i,name in enumerate(labels)}, fixed_ms=totals[0], pool_alternatives=alternatives)

rows = [audit(p) for p in sorted(Path('/data/commits').glob('*.patch'))]
assert len(rows) == 30
assert sum(row['score_ms'] for row in rows) == 433175
print(json.dumps(rows, sort_keys=True, separators=(',',':')))
