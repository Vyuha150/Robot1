#!/bin/bash
# scripts/benchmarks/run_hardware_benchmarks.sh
#
# Categories that need real target hardware (ROS2 topics, microphone/
# speaker/model runtimes, camera, real 3-Pi network) to produce a
# non-BLOCKED result. Intended to run ON a real Pi (or a machine with the
# ROS2 workspace sourced + models installed), not this dev sandbox --
# running it here will honestly report every metric BLOCKED, which is
# itself useful confirmation that this environment is correctly
# NOT claiming hardware it doesn't have.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

echo "NOTE: run on the real target Pi/board for a non-BLOCKED result."
echo "      On a dev sandbox, every metric below is expected to report BLOCKED honestly."
echo ""

python3 -c "
from bonbon_benchmarks.benchmark_runner import run
from bonbon_benchmarks.benchmark_reporter import persist, append_history, to_markdown

HARDWARE_CATEGORIES = ['ros2_latency', 'speech_ai', 'vision', 'llm', 'three_pi_network']
result = run(categories=HARDWARE_CATEGORIES)
path = persist(result)
append_history(result)
print(to_markdown(result))
print(f'\nPersisted to {path}')
print(f'Summary: {result.summary()}')
"
