"""bonbon_distributed_network_monitor.core.rtt_probe -- 3-Pi Phase 7
remainder. Uses a real local TCP listener for the reachable case (proves
the probe genuinely measures a connection, not just a fast connection-
refused error) and an unroutable address for the unreachable case."""

from __future__ import annotations

import contextlib
import socket
import threading
import unittest


@contextlib.contextmanager
def _loopback_listener():
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


class TestTcpConnectRttMs(unittest.TestCase):
    def test_reachable_host_returns_a_positive_float(self):
        from bonbon_distributed_network_monitor.core.rtt_probe import tcp_connect_rtt_ms

        with _loopback_listener() as port:
            rtt = tcp_connect_rtt_ms("127.0.0.1", port)
        self.assertIsNotNone(rtt)
        self.assertGreaterEqual(rtt, 0.0)

    def test_unreachable_port_returns_none(self):
        from bonbon_distributed_network_monitor.core.rtt_probe import tcp_connect_rtt_ms

        # Port 1 is a reserved/typically-closed port on loopback.
        rtt = tcp_connect_rtt_ms("127.0.0.1", 1, timeout=0.3)
        self.assertIsNone(rtt)

    def test_unresolvable_host_returns_none_within_timeout(self):
        from bonbon_distributed_network_monitor.core.rtt_probe import tcp_connect_rtt_ms

        rtt = tcp_connect_rtt_ms("this-host-does-not-resolve.invalid", 22, timeout=0.5)
        self.assertIsNone(rtt)


class TestProbeHost(unittest.TestCase):
    def test_all_successes_zero_loss(self):
        from bonbon_distributed_network_monitor.core.rtt_probe import probe_host

        with _loopback_listener() as port:
            result = probe_host("127.0.0.1", port, attempts=5)
        self.assertEqual(result.successes, 5)
        self.assertEqual(result.packet_loss_pct, 0.0)
        self.assertIsNotNone(result.avg_rtt_ms)
        self.assertIsNotNone(result.max_rtt_ms)

    def test_all_failures_full_loss(self):
        from bonbon_distributed_network_monitor.core.rtt_probe import probe_host

        result = probe_host("127.0.0.1", 1, attempts=3, timeout=0.3)
        self.assertEqual(result.successes, 0)
        self.assertEqual(result.packet_loss_pct, 100.0)
        self.assertIsNone(result.avg_rtt_ms)
        self.assertIsNone(result.max_rtt_ms)

    def test_attempts_below_one_is_clamped_to_one(self):
        from bonbon_distributed_network_monitor.core.rtt_probe import probe_host

        result = probe_host("127.0.0.1", 1, attempts=0, timeout=0.2)
        self.assertEqual(result.attempts, 1)


if __name__ == "__main__":
    unittest.main()
