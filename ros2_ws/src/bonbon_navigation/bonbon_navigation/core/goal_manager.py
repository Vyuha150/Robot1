"""
bonbon_navigation.core.goal_manager
=====================================
Navigation goal queue, lifecycle management, and failure classification.

Responsibilities
----------------
* Maintain a priority-ordered queue of NavigationGoal objects
* Enforce goal timeouts — fail a goal that takes too long
* Detect unreachable goals (repeated planning failure)
* Track goal history for logging and health reporting
* Provide atomic goal state transitions: PENDING→ACTIVE→DONE/FAILED

Thread-safe: all mutating operations hold the internal lock.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock

logger = logging.getLogger(__name__)

# Result codes mirror NavigationStatus.msg constants
RESULT_NONE = 0
RESULT_SUCCESS = 1
RESULT_TIMEOUT = 2
RESULT_UNREACHABLE = 3
RESULT_STUCK = 4
RESULT_SAFETY_STOP = 5
RESULT_CANCELLED = 6
RESULT_PLAN_FAILED = 7


# ── Goal state ────────────────────────────────────────────────────────────────


class GoalState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# ── Goal object ───────────────────────────────────────────────────────────────


@dataclass
class NavigationGoalEntry:
    goal_id: str
    goal_type: int  # 0=waypoint, 1=named, 2=charger, 3=person
    priority: int  # 0=low, 1=normal, 2=high, 3=urgent
    target_x: float
    target_y: float
    target_yaw: float
    named_location: str = ""
    timeout_sec: float = 120.0
    arrival_tol_m: float = 0.30
    require_precise: bool = False
    requester_id: str = ""
    recommendation_id: str = ""

    # State (mutable)
    state: GoalState = GoalState.PENDING
    result_code: int = RESULT_NONE
    result_message: str = ""
    plan_fail_count: int = 0
    enqueue_time: float = field(default_factory=time.monotonic)
    start_time: float | None = None
    end_time: float | None = None

    @property
    def elapsed_sec(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.monotonic()
        return end - self.start_time

    @property
    def timed_out(self) -> bool:
        return (
            self.start_time is not None
            and self.timeout_sec > 0
            and (time.monotonic() - self.start_time) > self.timeout_sec
        )

    def distance_to(self, x: float, y: float) -> float:
        return math.hypot(self.target_x - x, self.target_y - y)


# ── Goal manager ──────────────────────────────────────────────────────────────


class GoalManager:
    """
    Priority-ordered navigation goal queue with timeout enforcement.

    Usage::

        gm = GoalManager(max_queue_size=10, default_timeout_sec=120.0,
                         max_plan_failures=3)
        goal_id = gm.enqueue(...)
        goal    = gm.activate_next()   # called by nav node
        gm.mark_succeeded(goal.goal_id)
        gm.mark_failed(goal.goal_id, RESULT_TIMEOUT)
    """

    def __init__(
        self,
        max_queue_size: int = 10,
        default_timeout_sec: float = 120.0,
        max_plan_failures: int = 3,
    ) -> None:
        self._max_queue = max_queue_size
        self._default_timeout = default_timeout_sec
        self._max_plan_fail = max_plan_failures
        self._lock = Lock()
        self._queue: deque[NavigationGoalEntry] = deque()
        self._active: NavigationGoalEntry | None = None
        self._history: list[NavigationGoalEntry] = []  # last 50 completed goals

    # ── Enqueueing ────────────────────────────────────────────────────────────

    def enqueue(
        self,
        target_x: float,
        target_y: float,
        target_yaw: float,
        goal_type: int = 1,
        priority: int = 1,
        named_location: str = "",
        timeout_sec: float = 0.0,
        arrival_tol_m: float = 0.30,
        require_precise: bool = False,
        requester_id: str = "",
        recommendation_id: str = "",
        preempt: bool = False,
        goal_id: str = "",
    ) -> str:
        """
        Add a goal to the queue.  Returns the goal_id.

        Parameters
        ----------
        preempt:  If True, cancel the active goal and clear the queue first.
        """
        gid = goal_id or str(uuid.uuid4())
        entry = NavigationGoalEntry(
            goal_id=gid,
            goal_type=goal_type,
            priority=priority,
            target_x=target_x,
            target_y=target_y,
            target_yaw=target_yaw,
            named_location=named_location,
            timeout_sec=timeout_sec if timeout_sec > 0 else self._default_timeout,
            arrival_tol_m=arrival_tol_m,
            require_precise=require_precise,
            requester_id=requester_id,
            recommendation_id=recommendation_id,
        )

        with self._lock:
            if preempt:
                self._cancel_active("preempted by new goal")
                self._queue.clear()

            if len(self._queue) >= self._max_queue:
                # Drop lowest-priority queued goal
                self._drop_lowest_priority()

            self._insert_by_priority(entry)
            logger.info(
                "Goal enqueued: %s  type=%d  priority=%d  named=%r  pos=(%.2f,%.2f)",
                gid[:8],
                goal_type,
                priority,
                named_location,
                target_x,
                target_y,
            )
        return gid

    def _insert_by_priority(self, entry: NavigationGoalEntry) -> None:
        """Insert in priority order (highest priority first, FIFO within priority)."""
        for i, g in enumerate(self._queue):
            if entry.priority > g.priority:
                self._queue.insert(i, entry)
                return
        self._queue.append(entry)

    def _drop_lowest_priority(self) -> None:
        if not self._queue:
            return
        worst_idx = max(
            range(len(self._queue)),
            key=lambda i: -self._queue[i].priority,
        )
        dropped = self._queue[worst_idx]
        del self._queue[worst_idx]  # type: ignore[arg-type]
        logger.warning("Goal dropped (queue full): %s", dropped.goal_id[:8])

    # ── Activation / completion ────────────────────────────────────────────────

    def activate_next(self) -> NavigationGoalEntry | None:
        """
        Dequeue and activate the next pending goal.
        Returns None if queue is empty or a goal is already active.
        """
        with self._lock:
            if self._active is not None:
                return None
            if not self._queue:
                return None
            goal = self._queue.popleft()
            goal.state = GoalState.ACTIVE
            goal.start_time = time.monotonic()
            self._active = goal
            logger.info(
                "Goal activated: %s  named=%r  pos=(%.2f,%.2f)  timeout=%.0fs",
                goal.goal_id[:8],
                goal.named_location,
                goal.target_x,
                goal.target_y,
                goal.timeout_sec,
            )
            return goal

    def mark_succeeded(self, goal_id: str) -> bool:
        with self._lock:
            goal = self._find_active(goal_id)
            if goal is None:
                return False
            goal.state = GoalState.SUCCEEDED
            goal.result_code = RESULT_SUCCESS
            goal.end_time = time.monotonic()
            self._active = None
            self._history.append(goal)
            self._trim_history()
            logger.info("Goal SUCCEEDED: %s  elapsed=%.1fs", goal_id[:8], goal.elapsed_sec)
            return True

    def mark_failed(
        self,
        goal_id: str,
        result_code: int = RESULT_PLAN_FAILED,
        message: str = "",
    ) -> bool:
        with self._lock:
            goal = self._find_active(goal_id)
            if goal is None:
                return False
            goal.state = GoalState.FAILED
            goal.result_code = result_code
            goal.result_message = message
            goal.end_time = time.monotonic()
            self._active = None
            self._history.append(goal)
            self._trim_history()
            logger.warning(
                "Goal FAILED: %s  code=%d  msg=%r  elapsed=%.1fs",
                goal_id[:8],
                result_code,
                message,
                goal.elapsed_sec,
            )
            return True

    def cancel_goal(
        self,
        goal_id: str = "",
        reason: str = "",
    ) -> int:
        """Cancel a specific goal (or all if goal_id is empty). Returns count cancelled."""
        count = 0
        with self._lock:
            if goal_id:
                # Cancel specific goal
                if self._active and self._active.goal_id == goal_id:
                    self._cancel_active(reason)
                    count += 1
                else:
                    for i, g in enumerate(self._queue):
                        if g.goal_id == goal_id:
                            del self._queue[i]  # type: ignore
                            g.state = GoalState.CANCELLED
                            g.result_code = RESULT_CANCELLED
                            g.result_message = reason
                            self._history.append(g)
                            count += 1
                            break
            else:
                # Cancel all
                if self._active:
                    self._cancel_active(reason)
                    count += 1
                while self._queue:
                    g = self._queue.popleft()
                    g.state = GoalState.CANCELLED
                    g.result_code = RESULT_CANCELLED
                    self._history.append(g)
                    count += 1
        return count

    def _cancel_active(self, reason: str) -> None:
        if self._active:
            self._active.state = GoalState.CANCELLED
            self._active.result_code = RESULT_CANCELLED
            self._active.result_message = reason
            self._active.end_time = time.monotonic()
            self._history.append(self._active)
            logger.info("Active goal cancelled: %s  reason=%r", self._active.goal_id[:8], reason)
            self._active = None

    # ── Timeout + plan failure ────────────────────────────────────────────────

    def check_timeout(self) -> NavigationGoalEntry | None:
        """
        Check if the active goal has timed out.
        Returns the timed-out goal (still active — caller must call mark_failed).
        """
        with self._lock:
            if self._active and self._active.timed_out:
                logger.warning(
                    "Goal TIMEOUT: %s  elapsed=%.1fs > %.1fs",
                    self._active.goal_id[:8],
                    self._active.elapsed_sec,
                    self._active.timeout_sec,
                )
                return self._active
        return None

    def record_plan_failure(self, goal_id: str) -> bool:
        """
        Increment plan failure counter for the active goal.
        Returns True if the failure limit is reached (goal should be failed).
        """
        with self._lock:
            goal = self._find_active(goal_id)
            if goal is None:
                return False
            goal.plan_fail_count += 1
            if goal.plan_fail_count >= self._max_plan_fail:
                logger.warning(
                    "Goal UNREACHABLE: %s  plan_failures=%d",
                    goal_id[:8],
                    goal.plan_fail_count,
                )
                return True
            return False

    # ── Accessors ─────────────────────────────────────────────────────────────

    def get_active(self) -> NavigationGoalEntry | None:
        return self._active

    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    def get_history(self, n: int = 10) -> list[NavigationGoalEntry]:
        return self._history[-n:]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_active(self, goal_id: str) -> NavigationGoalEntry | None:
        if self._active and self._active.goal_id == goal_id:
            return self._active
        return None

    def _trim_history(self) -> None:
        if len(self._history) > 50:
            self._history = self._history[-50:]
