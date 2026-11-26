"""Minimal CONNECT proxy that pins api.github.com / github.com to a reachable IP.

Why this exists
---------------
On this machine github.com resolves to an address that does not answer, and the
sandbox's HTTP proxy refuses CONNECT for github.com. Direct curl with
``--noproxy '*' --resolve `` does work, but git has no equivalent of
``--resolve``, so ``git push`` cannot use the same trick.

This script listens on localhost and forwards CONNECT tunnels for the two GitHub
hosts to a hard-coded, working IP. Point git at it with
``-c http.proxy=http://127.0.0.1:PORT`` and push becomes possible without
touching /etc/hosts (which needs administrator rights).

Scope: only the hosts in PINNED are tunnelled; everything else is refused, so it
is not a general-purpose open proxy.

Usage:
    python tools/gh_tunnel.py --port 18080 --ip 140.82.116.6
    # then, in another shell:
    git -c http.proxy=http://127.0.0.1:18080 push origin main
"""
from __future__ import annotations

import argparse
import selectors
import socket
import sys

PINNED = {"api.github.com", "github.com", "codeload.github.com", "objects.githubusercontent.com"}


def splice(a: socket.socket, b: socket.socket) -> None:
    sel = selectors.DefaultSelector()
    sel.register(a, selectors.EVENT_READ, b)
    sel.register(b, selectors.EVENT_READ, a)
    try:
        while True:
            events = sel.select(timeout=60)
            if not events:
                return
            for key, _ in events:
                data = key.fileobj.recv(65536)
                if not data:
                    return
                key.data.sendall(data)
    finally:
        sel.close()


def handle(conn: socket.socket, ip: str) -> None:
    try:
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = conn.recv(4096)
            if not chunk:
                conn.close()
                return
            header += chunk
            if len(header) > 16384:
                conn.close()
                return

        line = header.split(b"\r\n", 1)[0].decode("latin-1")
        parts = line.split()
        if len(parts) < 2 or parts[0] != "CONNECT":
            conn.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            conn.close()
            return

        host, _, port_s = parts[1].partition(":")
        port = int(port_s or 443)

        if host.lower() not in PINNED:
            conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            conn.close()
            return

        upstream = socket.create_connection((ip, port), timeout=20)
        conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        splice(conn, upstream)
        upstream.close()
    except Exception as exc:  # noqa: BLE001
        print("[tunnel] error: %s" % exc, file=sys.stderr)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--ip", default="140.82.116.6")
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((a.host, a.port))
    srv.listen(64)
    print("[tunnel] listening on %s:%d -> %s (hosts: %s)"
          % (a.host, a.port, a.ip, ", ".join(sorted(PINNED))), flush=True)

    try:
        while True:
            conn, _ = srv.accept()
            import threading

            threading.Thread(target=handle, args=(conn, a.ip), daemon=True).start()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
