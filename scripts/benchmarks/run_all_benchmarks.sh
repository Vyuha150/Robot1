#!/bin/bash
# scripts/benchmarks/run_all_benchmarks.sh
#
# Runs every bonbon_benchmarks category, plus the two existing benchmark
# scripts this suite reuses rather than duplicates (edge_ai runtime layer,
# real model inference) -- one command for a full efficiency picture.
# Never fakes a hardware-dependent result: categories without real
# hardware in this environment report BLOCKED, which is still a real,
# honest output, not a script failure.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

echo "=== 1/3: bonbon_benchmarks (all 9 categories) ==="
python3 -c "
from bonbon_benchmarks.benchmark_runner import run
from bonbon_benchmarks.benchmark_reporter import persist, append_history, to_markdown
result = run()
path = persist(result)
append_history(result)
print(to_markdown(result))
print(f'\nPersisted to {path}')
print(f'Summary: {result.summary()}')
"

echo ""
echo "=== 2/3: edge_ai runtime layer (task routing, safety separation, caching, resource guard, accelerator selection) ==="
python3 scripts/edge_ai/benchmark_edge_ai_stack.py || true

echo ""
echo "=== 3/3: real model inference (ASR/TTS/LLM/vision) ==="
python3 scripts/ai_models/benchmark_all_models.py || true

echo ""
echo "All benchmark categories run. See docs/project-status/efficiency_benchmark_results.json for full detail."
