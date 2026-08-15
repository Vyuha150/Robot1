"""bonbon_distributed_network_monitor.core.rtt_probe -- TCP-connect-timing
RTT probe for continuous inter-Pi link-quality monitoring (3-Pi Phase 7
remainder). No ICMP raw-socket privilege needed; measures the same way a
real service health-check would.

Mirrors the probe technique bonbon_benchmarks/three_pi_network_benchmark.py
already proved out for one-shot benchmarking -- this is the production,
continuously-polled counterpart, living in the package that actually runs
on every deployed Pi rather than the benchmark suite.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass


def tcp_connect_rtt_ms(host: str, port: int, timeout: float = 1.0) -> float | None:
    """One TCP connect-and-close RTT sample, or None if unreachable.

    `socket.create_connection`'s `timeout` only bounds the connect() call,
    not DNS resolution -- an unresolvable hostname could otherwise hang for
    the OS's full resolver timeout. A dedicated resolver thread, joined
    with the same timeout, bounds the whole operation honestly instead of
    silently blocking the caller.
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


@dataclass(frozen=True)
class ProbeResult:
    host: str
    port: int
    attempts: int
    successes: int
    rtt_samples_ms: tuple[float, ...]

    @property
    def packet_loss_pct(self) -> float:
        if self.attempts == 0:
            return 100.0
        return 100.0 * (self.attempts - self.successes) / self.attempts

    @property
    def avg_rtt_ms(self) -> float | None:
        if not self.rtt_samples_ms:
            return None
        return sum(self.rtt_samples_ms) / len(self.rtt_samples_ms)

    @property
    def max_rtt_ms(self) -> float | None:
        if not self.rtt_samples_ms:
            return None
        return max(self.rtt_samples_ms)


def probe_host(host: str, port: int, attempts: int, timeout: float = 1.0) -> ProbeResult:
    """Run `attempts` TCP-connect probes against host:port and summarise
    RTT/loss. Never raises -- an entirely unreachable host simply produces
    a ProbeResult with zero successes and 100% loss."""
    samples: list[float] = []
    successes = 0
    for _ in range(max(1, attempts)):
        rtt = tcp_connect_rtt_ms(host, port, timeout=timeout)
        if rtt is not None:
            successes += 1
            samples.append(rtt)
    return ProbeResult(
        host=host,
        port=port,
        attempts=max(1, attempts),
        successes=successes,
        rtt_samples_ms=tuple(samples),
    )
