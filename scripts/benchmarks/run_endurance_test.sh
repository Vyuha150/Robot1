#!/bin/bash
# scripts/benchmarks/run_endurance_test.sh --duration <15m|30m|2h|8h>
#
# Actually runs for the requested duration, sampling CPU/RAM/temperature
# (bonbon_benchmarks.resource_monitor.FullResourceMonitor) at a fixed
# interval and reporting real growth trends at the end -- never
# extrapolates a multi-hour result from a few seconds of data. Can be
# interrupted (Ctrl-C) at any time; partial results up to that point are
# still reported honestly, labeled as partial.
#
# Usage:
#   bash scripts/benchmarks/run_endurance_test.sh --duration 15m   # smoke
#   bash scripts/benchmarks/run_endurance_test.sh --duration 30m   # thermal (needs real Pi thermal sensor for a meaningful result)
#   bash scripts/benchmarks/run_endurance_test.sh --duration 2h    # pilot
#   bash scripts/benchmarks/run_endurance_test.sh --duration 8h    # production soak

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

DURATION="15m"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --duration) DURATION="$2"; shift 2 ;;
        *) echo "unknown argument: $1"; exit 2 ;;
    esac
done

python3 -c "
import re
import sys
import time
from pathlib import Path

from bonbon_benchmarks.resource_monitor import FullResourceMonitor

duration_str = '$DURATION'
match = re.fullmatch(r'(\d+)([mh])', duration_str)
if not match:
    print(f'BLOCKED: could not parse duration {duration_str!r} -- use e.g. 15m, 30m, 2h, 8h')
    sys.exit(1)
value, unit = int(match.group(1)), match.group(2)
duration_sec = value * (3600 if unit == 'h' else 60)
sample_interval_sec = min(30.0, max(1.0, duration_sec / 60.0))

print(f'Running endurance sampling for {duration_str} ({duration_sec}s), sampling every {sample_interval_sec:.1f}s...')
print('Press Ctrl-C to stop early -- partial results are still reported.')

monitor = FullResourceMonitor()
samples = []
started = time.time()
try:
    while (time.time() - started) < duration_sec:
        snap = monitor.sample()
        samples.append((time.time() - started, snap))
        if len(samples) % 10 == 0 or not samples[:-1]:
            print(f'  t={time.time()-started:6.0f}s  cpu={snap.cpu_percent:.1f}%  mem={snap.memory_mb:.0f}MB  temp={snap.temperature_c}')
        time.sleep(sample_interval_sec)
except KeyboardInterrupt:
    print('\nInterrupted -- reporting partial results.')

elapsed = time.time() - started
partial = elapsed < duration_sec * 0.95
available_samples = [s for _, s in samples if s.available]

print(f'\n=== Endurance run summary ({elapsed:.0f}s of {duration_sec}s requested{\", PARTIAL\" if partial else \"\"}) ===')
if len(available_samples) < 2:
    print('BLOCKED: fewer than 2 resource samples with real readings (psutil unavailable in this environment) -- no growth trend computable.')
    sys.exit(0)

mem_growth = available_samples[-1].memory_mb - available_samples[0].memory_mb
cpu_values = [s.cpu_percent for s in available_samples]
print(f'Samples: {len(samples)} total, {len(available_samples)} with real readings')
print(f'Memory: {available_samples[0].memory_mb:.0f}MB -> {available_samples[-1].memory_mb:.0f}MB (growth: {mem_growth:+.1f}MB)')
print(f'CPU: min={min(cpu_values):.1f}% max={max(cpu_values):.1f}% avg={sum(cpu_values)/len(cpu_values):.1f}%')
temps = [s.temperature_c for s in available_samples if s.temperature_c is not None]
if temps:
    print(f'Temperature: min={min(temps):.1f}C max={max(temps):.1f}C')
else:
    print('Temperature: BLOCKED -- no thermal_zone sysfs path on this platform')
throttled = any(s.throttled for s in available_samples if s.throttled is not None)
print(f'Thermal throttling observed: {throttled}')
"
