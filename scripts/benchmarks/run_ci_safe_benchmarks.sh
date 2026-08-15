#!/bin/bash
# scripts/benchmarks/run_ci_safe_benchmarks.sh
#
# Categories that are pure-Python and genuinely fast/deterministic on any
# machine, no external hardware/network/model runtime required -- safe to
# run on every commit in CI. Hardware-dependent categories (speech_ai,
# vision, llm, ros2_latency, three_pi_network) belong in
# run_hardware_benchmarks.sh instead -- running them here would either
# be slow (DNS timeouts against unreachable hosts) or always report the
# same BLOCKED result on every CI machine, adding no signal.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

python3 -c "
from bonbon_benchmarks.benchmark_runner import run
from bonbon_benchmarks.benchmark_reporter import persist, append_history, to_markdown

CI_SAFE_CATEGORIES = ['resource', 'cache_efficiency', 'safety_under_load', 'dashboard']
result = run(categories=CI_SAFE_CATEGORIES)
path = persist(result)
append_history(result)
print(to_markdown(result))
print(f'\nPersisted to {path}')

summary = result.summary()
print(f'Summary: {summary}')
import sys
sys.exit(1 if summary['FAIL'] > 0 else 0)
"
