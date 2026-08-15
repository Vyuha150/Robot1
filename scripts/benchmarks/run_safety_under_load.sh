#!/bin/bash
# scripts/benchmarks/run_safety_under_load.sh
#
# Runs the safety_under_load category alone -- real load-injection
# against the real SafetySeparationGuard -- and exits non-zero if any
# safety-critical metric FAILs. Intended to gate a deploy: a safety
# regression under load must block the pipeline, not just be logged.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

python3 -c "
from bonbon_benchmarks.benchmark_runner import run
from bonbon_benchmarks.benchmark_reporter import persist, append_history, to_markdown

result = run(categories=['safety_under_load'])
path = persist(result)
append_history(result)
print(to_markdown(result))
print(f'\nPersisted to {path}')

failures = [m for cat in result.categories for m in cat.metrics if m.status == 'FAIL']
if failures:
    print(f'\nSAFETY REGRESSION: {len(failures)} metric(s) FAILED under load:')
    for m in failures:
        print(f'  - {m.metric_name}: p95={m.p95:.2f}{m.unit} > target {m.target}{m.unit}')
    import sys
    sys.exit(1)
print('\nAll safety-under-load metrics passed their target.')
"
