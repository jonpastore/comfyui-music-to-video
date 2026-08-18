#!/usr/bin/env python3
"""Rate-limited HTTP/HTTPS proxy for Reddit egress.

Listen on localhost + Tailscale only. Allowlisted hosts. Token auth.
Backs off hard on 429 / 403-Blocked so we do not trip Reddit again.
"""
from __future__ import annotations

import argparse
import base64
import json
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ALLOW_SUFFIXES = (
    ".reddit.com",
    ".redd.it",
    ".redditmedia.com",
    ".redditstatic.com",
)
ALLOW_EXACT = {
    "reddit.com",
    "redd.it",
    "redditmedia.com",
    "redditstatic.com",
}

MIN_INTERVAL_S = 2.5
MAX_PER_MINUTE = 12
MAX_IN_FLIGHT = 1
DAILY_CAP = 400
COOLDOWN_429_S = 15 * 60
COOLDOWN_403_S = 30 * 60
CONNECT_TIMEOUT_S = 20
IO_TIMEOUT_S = 60


def host_allowed(host: str) -> bool:
    h = (host or "").split(":")[0].lower().rstrip(".")
    if h in ALLOW_EXACT:
        return True
    return any(h.endswith(s) for s in ALLOW_SUFFIXES)


class Gate:
    def __init__(self, state_path: Path):
        self.state_path = state_path
        self.lock = threading.Lock()
        self.last = 0.0
        self.minute = []
        self.in_flight = 0
        self.day = time.strftime("%Y-%m-%d")
        self.count = 0
        self.cool_until = 0.0
        self.cool_why = ""
        self._load()

    def _load(self):
        try:
            d = json.loads(self.state_path.read_text())
        except Exception:
            return
        if d.get("day") == self.day:
            self.count = int(d.get("count") or 0)
        self.cool_until = float(d.get("cool_until") or 0)
        self.cool_why = d.get("cool_why") or ""

    def _save(self):
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "day": self.day,
                    "count": self.count,
                    "cool_until": self.cool_until,
                    "cool_why": self.cool_why,
                }
            )
        )
        tmp.replace(self.state_path)

    def acquire(self) -> str | None:
        with self.lock:
            now = time.time()
            today = time.strftime("%Y-%m-%d")
            if today != self.day:
                self.day = today
                self.count = 0
            if now < self.cool_until:
                left = int(self.cool_until - now)
                return f"cooldown {self.cool_why} {left}s remaining"
            if self.count >= DAILY_CAP:
                return f"daily cap {DAILY_CAP}"
            if self.in_flight >= MAX_IN_FLIGHT:
                return "in-flight limit"
            self.minute = [t for t in self.minute if now - t < 60]
            if len(self.minute) >= MAX_PER_MINUTE:
                return f"over {MAX_PER_MINUTE}/min"
            wait = MIN_INTERVAL_S - (now - self.last)
            if wait > 0:
                time.sleep(wait)
                now = time.time()
            self.last = now
            self.minute.append(now)
            self.in_flight += 1
            self.count += 1
            self._save()
            return None

    def release(self):
        with self.lock:
            self.in_flight = max(0, self.in_flight - 1)

    def trip(self, why: str, seconds: int):
        with self.lock:
            self.cool_until = max(self.cool_until, time.time() + seconds)
            self.cool_why = why
            self._save()


def log(msg: str):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"{ts} {msg}", flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = IO_TIMEOUT_S

    def log_message(self, fmt, *args):
        log("%s - " % self.address_string() + fmt % args)

    def _auth_ok(self) -> bool:
        token = self.server.token  # type: ignore[attr-defined]
        raw = self.headers.get("Proxy-Authorization") or self.headers.get(
            "Authorization"
        )
        if not raw or not token:
            return False
        kind, _, rest = raw.partition(" ")
        kind = kind.lower()
        if kind == "bearer":
            return rest.strip() == token
        if kind == "basic":
            try:
                user, _, pw = base64.b64decode(rest).decode().partition(":")
            except Exception:
                return False
            return pw == token or (user == token and not pw)
        return False

    def _deny(self, code: int, msg: str):
        body = (msg + "\n").encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _target_host(self) -> str | None:
        if self.command == "CONNECT":
            return self.path.split("/")[0]
        parsed = urlparse(self.path)
        if parsed.scheme and parsed.netloc:
            return parsed.netloc
        return self.headers.get("Host")

    def _gate(self, host: str) -> bool:
        if not self._auth_ok():
            self.send_response(407)
            self.send_header("Proxy-Authenticate", 'Basic realm="reddit-egress"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        if not host_allowed(host):
            self._deny(403, f"host not allowlisted: {host}")
            return False
        err = self.server.gate.acquire()  # type: ignore[attr-defined]
        if err:
            self._deny(429, f"local rate limit: {err}")
            return False
        return True

    def do_CONNECT(self):
        hostport = self.path
        host = hostport.split(":")[0]
        port = int(hostport.split(":")[1]) if ":" in hostport else 443
        if not self._gate(hostport if ":" in hostport else host):
            return
        try:
            remote = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S)
        except OSError as e:
            self.server.gate.release()  # type: ignore[attr-defined]
            self._deny(502, f"connect failed: {e}")
            return
        self.send_response(200, "Connection Established")
        self.send_header("Proxy-Agent", "reddit-egress")
        self.end_headers()
        try:
            _pump(self.connection, remote)
        finally:
            remote.close()
            self.server.gate.release()  # type: ignore[attr-defined]

    def do_GET(self):
        self._proxy_http()

    def do_HEAD(self):
        self._proxy_http()

    def do_POST(self):
        self._proxy_http()

    def do_PUT(self):
        self._proxy_http()

    def _proxy_http(self):
        parsed = urlparse(self.path)
        if not parsed.scheme:
            self._deny(400, "absolute URL required")
            return
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not self._gate(host):
            return
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        try:
            remote = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S)
        except OSError as e:
            self.server.gate.release()  # type: ignore[attr-defined]
            self._deny(502, f"connect failed: {e}")
            return
        try:
            if parsed.scheme == "https":
                import ssl

                ctx = ssl.create_default_context()
                remote = ctx.wrap_socket(remote, server_hostname=host)
            skip = {"proxy-authorization", "proxy-connection", "connection"}
            hdrs = []
            for k, v in self.headers.items():
                if k.lower() in skip:
                    continue
                hdrs.append(f"{k}: {v}")
            req = (
                f"{self.command} {path} HTTP/1.1\r\n"
                + "\r\n".join(hdrs)
                + "\r\n\r\n"
            ).encode() + body
            remote.sendall(req)
            chunks = []
            remote.settimeout(IO_TIMEOUT_S)
            while True:
                data = remote.recv(65536)
                if not data:
                    break
                chunks.append(data)
            blob = b"".join(chunks)
            self.wfile.write(blob)
            self._maybe_trip(blob)
        except OSError as e:
            log(f"http proxy error {host}: {e}")
        finally:
            remote.close()
            self.server.gate.release()  # type: ignore[attr-defined]

    def _maybe_trip(self, blob: bytes):
        head = blob.split(b"\r\n\r\n", 1)[0][:400]
        line = head.split(b"\r\n", 1)[0].decode("latin1", "replace")
        if " 429" in line:
            self.server.gate.trip("upstream-429", COOLDOWN_429_S)  # type: ignore
            log("tripped cooldown: upstream 429")
        elif " 403" in line and b"Blocked" in blob[:2000]:
            self.server.gate.trip("upstream-403", COOLDOWN_403_S)  # type: ignore
            log("tripped cooldown: upstream 403 Blocked")


def _pump(a: socket.socket, b: socket.socket):
    a.setblocking(False)
    b.setblocking(False)
    sockets = [a, b]
    idle = 0.0
    while True:
        r, _, x = select.select(sockets, [], sockets, 1.0)
        if x:
            break
        if not r:
            idle += 1
            if idle > IO_TIMEOUT_S:
                break
            continue
        idle = 0.0
        for src in r:
            dst = b if src is a else a
            try:
                data = src.recv(65536)
            except OSError:
                return
            if not data:
                return
            try:
                dst.sendall(data)
            except OSError:
                return


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, token: str, gate: Gate):
        super().__init__(addr, Handler)
        self.token = token
        self.gate = gate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bind", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8118)
    p.add_argument("--token-file", required=True)
    p.add_argument("--state-file", required=True)
    args = p.parse_args()
    token = Path(args.token_file).read_text().strip()
    if not token:
        raise SystemExit("empty token")
    gate = Gate(Path(args.state_file))
    httpd = Server((args.bind, args.port), token, gate)
    log(f"listening {args.bind}:{args.port} allow=reddit min={MIN_INTERVAL_S}s {MAX_PER_MINUTE}/min")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
