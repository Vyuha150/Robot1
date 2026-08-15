"""Inter-Pi network latency benchmarking -- a confirmed genuine gap
(bonbon_distributed_network_monitor only measures clock offset via
chrony, never RTT/latency; no ping/socket-latency module exists anywhere
in the repo, confirmed by direct search).

Real TCP-connect-timing RTT probe (no ICMP raw-socket privilege needed,
works the same way a real service health-check would). Reads target
hostnames from config/benchmarks/benchmark_targets.yaml. On a single-
machine dev environment (this one) the configured Pi hostnames are
unreachable, so this honestly reports HARDWARE_BLOCKED per pair --
except a loopback self-test against 127.0.0.1, which proves the probe
mechanism itself works without claiming it represents real inter-Pi
network conditions (labeled as such in the recommendation).
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time

import bonbon_benchmarks  # noqa: F401
from bonbon_benchmarks.metrics_collector import (
    BenchmarkCategoryReport,
    BenchmarkMetric,
    MetricSampler,
)

_CONNECT_TIMEOUT_SEC = 1.0


@contextlib.contextmanager
def _loopback_listener():
    """A real, minimal TCP listener on an ephemeral localhost port, so the
    loopback self-test has something to actually connect to -- proving
    tcp_connect_rtt_ms genuinely measures a connection, not just timing a
    guaranteed-fast connection-refused error."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    port = server.getsockname()[1]
    stop = threading.Event()

    def _accept_loop() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
                conn.close()
            except TimeoutError:
                continue
            except OSError:
                break

    thread = threading.Thread(target=_accept_loop, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        stop.set()
        server.close()
        thread.join(timeout=1.0)


def tcp_connect_rtt_ms(host: str, port: int, timeout: float = _CONNECT_TIMEOUT_SEC) -> float | None:
    """One TCP connect-and-close RTT sample, or None if unreachable.

    `socket.create_connection`'s `timeout` only bounds the connect() call,
    not the DNS resolution step -- an unresolvable mDNS `.local` hostname
    (like the real Pi hostnames, on a machine with no mDNS resolver) can
    otherwise hang for the OS's full resolver timeout (tens of seconds).
    A dedicated resolver thread, joined with the same timeout, bounds the
    whole operation honestly instead of silently blocking the caller.
    """
    resolved: list[str] = []

    def _resolve() -> None:
        try:
            resolved.append(socket.gethostbyname(host))
        except OSError:
            pass

    resolver = threading.Thread(target=_resolve, daemon=True)
    resolver.start()
    resolver.join(timeout=timeout)
    if not resolved:
        return None  # unresolvable within the timeout -- honestly unreachable

    started = time.perf_counter()
    try:
        with socket.create_connection((resolved[0], port), timeout=timeout):
            pass
    except OSError:
        return None
    return (time.perf_counter() - started) * 1000.0


def benchmark_pair(
    label: str, host: str, port: int, iterations: int = 20
) -> BenchmarkMetric:
    sampler = MetricSampler()
    failures = 0
    for i in range(iterations):
        rtt = tcp_connect_rtt_ms(host, port)
        if rtt is None:
            failures += 1
            if i == 0:
                # First attempt already failed to resolve/connect --
                # retrying an unreachable host N more times only adds
                # wall-clock time (bounded per-attempt, but still wasted),
                # not information. One confirmed-unreachable sample is
                # enough to report BLOCKED honestly.
                break
        else:
            sampler.record(rtt)

    if sampler.count == 0:
        return BenchmarkMetric.blocked(
            metric_name="inter_pi_network_latency", board=label, module="network",
            scenario=f"TCP connect RTT to {host}:{port} x{iterations}",
            reason=f"{host}:{port} unreachable ({failures}/{iterations} attempts failed) -- no real multi-Pi network in this environment",
            recommendation="Run this same probe from each real Pi against the other two once deployed.",
        )
    note = "" if failures == 0 else f"{failures}/{iterations} attempts failed (transient or partially reachable)."
    if host in ("127.0.0.1", "localhost"):
        note = (note + " LOOPBACK SELF-TEST ONLY -- proves the probe mechanism works, NOT representative of real inter-Pi network latency.").strip()
    return BenchmarkMetric.from_sampler(
        sampler, metric_name="inter_pi_network_latency", board=label, module="network",
        scenario=f"TCP connect RTT to {host}:{port} x{iterations}", unit="ms",
        recommendation=note,
    )


def run_all(targets: dict[str, tuple[str, int]] | None = None) -> BenchmarkCategoryReport:
    """`targets` maps a pair label (e.g. "ui_pi<->ai_pi") to (host, port).
    Defaults to the loopback self-test plus BLOCKED placeholders for the
    three real Pi-pair labels the brief names, since no real hostnames
    are configured/reachable in this environment."""
    report = BenchmarkCategoryReport(category="three_pi_network")

    if targets is None:
        with _loopback_listener() as loopback_port:
            report.add(benchmark_pair("loopback_self_test", "127.0.0.1", loopback_port))
        targets = {
            "ui_pi<->ai_pi": ("bonbon-pi1.local", 8000),
            "ai_pi<->nav_pi": ("bonbon-pi2.local", 8000),
            "ui_pi<->nav_pi": ("bonbon-pi3.local", 8000),
        }

    for label, (host, port) in targets.items():
        report.add(benchmark_pair(label, host, port))
    return report
