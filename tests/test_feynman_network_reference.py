from __future__ import annotations

import socket
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tooling.feynman_network_reference import endpoint_identity, verify_reachable


class NetworkReferenceTests(unittest.TestCase):
    def test_reachable_endpoint_produces_verified_reference(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        host, port = server.getsockname()
        accepted = threading.Event()

        def serve_once():
            try:
                conn, _ = server.accept()
                conn.close()
                accepted.set()
            finally:
                server.close()

        thread = threading.Thread(target=serve_once, daemon=True)
        thread.start()
        result = verify_reachable(host, port, timeout=1.0)
        thread.join(timeout=2.0)

        self.assertTrue(accepted.is_set())
        self.assertTrue(result["reachable_from_control_plane"])
        self.assertEqual(result["probe_method"], "tcp-connect:v1")
        self.assertEqual(result["endpoint_identity_sha256"], endpoint_identity(host, port))

    def test_bound_but_not_listening_endpoint_is_rejected(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        host, port = sock.getsockname()
        try:
            with self.assertRaises(ValueError):
                verify_reachable(host, port, timeout=0.2)
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
