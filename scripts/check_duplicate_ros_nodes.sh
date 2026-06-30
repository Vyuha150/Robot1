#!/usr/bin/env bash
# Runtime check for duplicate ROS2 nodes — above all, more than one
# safety_supervisor_node, which means a duplicate-topology deployment is
# live (two publishers on /bonbon/safety/state → nondeterministic safety
# state). Run on the robot with a sourced ROS2 workspace.
#
#   bash scripts/check_duplicate_ros_nodes.sh
#
# Exit 0 = no duplicates; 1 = a duplicate node (or duplicate safety
# supervisor) is running.
set -uo pipefail

if ! command -v ros2 >/dev/null 2>&1; then
  echo "[WARN] ros2 not on PATH — source the workspace install/setup.bash first." >&2
  echo "RESULT: UNKNOWN (cannot enumerate nodes)"
  exit 0
fi

echo "== Duplicate ROS2 node check =="
mapfile -t nodes < <(ros2 node list 2>/dev/null | sed 's/^[[:space:]]*//' | grep -v '^$')

if [[ ${#nodes[@]} -eq 0 ]]; then
  echo "[WARN] no nodes visible — is the stack running?"
  echo "RESULT: UNKNOWN"
  exit 0
fi

fail=0

# Critical: exactly one safety supervisor.
safety_count=$(printf '%s\n' "${nodes[@]}" | grep -c 'safety_supervisor_node' || true)
if [[ "$safety_count" -gt 1 ]]; then
  echo "[FAIL] $safety_count safety_supervisor_node processes running — MUST be exactly 1."
  echo "       This is the duplicate-safety-supervisor deployment bug."
  echo "       Remediate: bash scripts/select_deployment_mode.sh status"
  fail=1
elif [[ "$safety_count" -eq 1 ]]; then
  echo "[PASS] exactly one safety_supervisor_node."
else
  echo "[FAIL] no safety_supervisor_node running — the robot must never run without one."
  fail=1
fi

# Any other node name appearing more than once also indicates a duplicate stack.
dupes=$(printf '%s\n' "${nodes[@]}" | sort | uniq -d || true)
if [[ -n "$dupes" ]]; then
  echo "[FAIL] duplicate node name(s) detected (a second stack is running):"
  printf '   %s\n' $dupes
  fail=1
else
  echo "[PASS] no duplicate node names."
fi

echo "================================"
if [[ $fail -ne 0 ]]; then
  echo "RESULT: DUPLICATE TOPOLOGY DETECTED"
  exit 1
fi
echo "RESULT: clean — single stack, single safety supervisor."
