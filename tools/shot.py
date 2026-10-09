#!/usr/bin/env python3
"""Screenshot a page in headless Chromium and print its console. For LLM agents.

`chromium --screenshot` cannot wait for a condition or run script first, so it
photographs this repo's page mid-load and can only ever capture the default
state. This drives the DevTools Protocol instead, which can do both.

    python3 tools/shot.py http://localhost:8000/ -o /tmp/shot.png \
        --wait 'document.querySelector("tr[data-i]")'

No dependencies: the WebSocket client below is the slice of RFC 6455 that the
protocol needs.

With no Chromium on PATH it falls back to Docker: it runs the public
`chromedp/headless-shell` image (host networking, DevTools on port 9222) and
removes the container afterwards. Pages on the host are reached as
`localhost`, so `make dev`'s server works unchanged.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import select
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

CHROME_FLAGS = [
    "--headless=new",
    "--no-sandbox",
    "--disable-gpu",          # nothing here draws; skipping GPU init starts faster
    "--hide-scrollbars",
    "--disable-extensions",
    "--no-first-run",
    "--disable-background-timer-throttling",
]


DOCKER_IMAGE = "chromedp/headless-shell:latest"


class WebSocket:
    """Client for one connection. Text frames only, which is all CDP uses."""

    def __init__(self, url: str, timeout: float = 30.0):
        host, _, path = url.removeprefix("ws://").partition("/")
        name, _, port = host.partition(":")
        self.sock = socket.create_connection((name, int(port or 80)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            f"GET /{path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("the browser closed the connection")
            buf += chunk
        head, _, self.rest = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError(f"handshake refused: {head.splitlines()[0]!r}")

    def readable(self, timeout: float) -> bool:
        """True if a message is waiting. Lets the caller wait on a clock without
        ever timing out partway through a frame."""
        return bool(self.rest) or bool(select.select([self.sock], [], [], timeout)[0])

    def _read(self, n: int) -> bytes:
        while len(self.rest) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("the browser closed the connection")
            self.rest += chunk
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def send(self, text: str) -> None:
        payload = text.encode()
        n = len(payload)
        header = bytearray([0x81])
        if n < 126:
            header.append(0x80 | n)
        elif n < 1 << 16:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4]
                                                for i, b in enumerate(payload)))

    def recv(self) -> str:
        chunks = []
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            data = self._read(n) if n else b""
            opcode = b0 & 0x0F
            if opcode == 0x8:
                raise ConnectionError("the browser closed the connection")
            if opcode == 0x9:                       # ping
                self.sock.sendall(b"\x8a\x00")
                continue
            chunks.append(data)
            if b0 & 0x80:                           # fin
                return b"".join(chunks).decode("utf-8", "replace")


class Browser:
    """A headless Chromium and its DevTools connection, as a context manager."""

    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.events: list[dict] = []
        self.next_id = 0

    def __enter__(self) -> "Browser":
        binary = next((shutil.which(n) for n in
                       ("chromium", "chromium-browser", "google-chrome-stable",
                        "google-chrome") if shutil.which(n)), None)
        self.profile = tempfile.mkdtemp(prefix="shot-")
        self.container = None
        if binary:
            port = random.randint(45000, 60000)
            self.process = subprocess.Popen(
                [binary, *CHROME_FLAGS, f"--window-size={self.width},{self.height}",
                 f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}",
                 "about:blank"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("docker"):
            port = 9222                              # fixed by the image's run.sh
            self.process = subprocess.Popen(
                ["docker", "run", "--rm", "--network", "host", DOCKER_IMAGE,
                 "--hide-scrollbars", f"--window-size={self.width},{self.height}", "about:blank"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.container = True
        else:
            sys.exit("shot: no chromium on PATH and no docker to fetch one")

        deadline = time.time() + (90 if self.container else 25)      # the image may need pulling
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
                    page = next((t for t in json.load(response)
                                 if t.get("type") == "page"
                                 and t.get("webSocketDebuggerUrl")), None)
                if page:
                    self.ws = WebSocket(page["webSocketDebuggerUrl"])
                    self.call("Runtime.enable")
                    self.call("Log.enable")
                    self.call("Page.enable")
                    # --window-size alone leaves the viewport short of what was
                    # asked for; this pins it to the exact size.
                    self.call("Emulation.setDeviceMetricsOverride",
                              {"width": self.width, "height": self.height,
                               "deviceScaleFactor": 1, "mobile": False})
                    return self
            except (urllib.error.URLError, ConnectionError, OSError,
                    json.JSONDecodeError):
                pass
            time.sleep(0.1)
        self.__exit__(None, None, None)
        sys.exit("shot: the browser never offered a page target")

    def __exit__(self, *_) -> None:
        if self.container:                           # `docker run --rm` stops when the client is killed
            ids = subprocess.run(["docker", "ps", "-q", "--filter", f"ancestor={DOCKER_IMAGE}"],
                                 capture_output=True, text=True).stdout.split()
            if ids:
                subprocess.run(["docker", "rm", "-f", *ids], capture_output=True)
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    def _pump(self, want: int | None, timeout: float):
        """Read messages until reply `want` arrives, keeping events. With
        want=None, just collect events for `timeout` seconds."""
        deadline = time.time() + timeout
        while (left := deadline - time.time()) > 0:
            if not self.ws.readable(min(0.1, left)):
                continue
            message = json.loads(self.ws.recv())
            if "method" in message:
                self.events.append(message)
            elif message.get("id") == want:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message.get("result", {})
        if want is not None:
            raise TimeoutError("the browser did not reply")

    def call(self, method: str, params: dict | None = None, timeout: float = 60.0):
        self.next_id += 1
        self.ws.send(json.dumps(
            {"id": self.next_id, "method": method, "params": params or {}}))
        return self._pump(self.next_id, timeout)

    def evaluate(self, expression: str):
        return self.call("Runtime.evaluate",
                         {"expression": expression, "returnByValue": True,
                          "awaitPromise": True})

    def settle(self, seconds: float) -> None:
        self._pump(None, seconds)

    def until(self, expression: str, timeout: float = 30.0) -> bool:
        """Poll a JS expression until it is truthy.

        Coerced to a boolean here so the expression may return anything -- a DOM
        element is the obvious thing to wait on, and cannot cross the protocol
        by value.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.evaluate(f"!!({expression})").get("result", {}).get("value"):
                return True
            self.settle(0.05)
        return False

    def console(self) -> list[str]:
        out = []
        for event in self.events:
            method, params = event["method"], event["params"]
            if method == "Runtime.consoleAPICalled":
                text = " ".join(str(a.get("value", a.get("description", "")))
                                for a in params["args"])
                out.append(f"[{params['type']}] {text}")
            elif method == "Runtime.exceptionThrown":
                detail = params["exceptionDetails"]
                out.append("[error] " + (
                    detail.get("exception", {}).get("description")
                    or detail.get("text", "")))
            elif method == "Log.entryAdded":
                entry = params["entry"]
                # Every page asks for a favicon it hasn't got; that 404 is noise.
                if (entry.get("level") in ("error", "warning")
                        and "favicon.ico" not in entry.get("url", "")):
                    out.append(f"[{entry['level']}] {entry.get('text', '')}")
        return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("-o", "--out", default="shot.png")
    parser.add_argument("-s", "--size", default="1280x800", help="WIDTHxHEIGHT")
    parser.add_argument("--wait", help="poll this JS until truthy, then capture")
    parser.add_argument("--eval", dest="script", help="run this JS before capturing")
    parser.add_argument("--settle", type=float, default=0.3,
                        help="extra seconds to let the page run (default 0.3)")
    parser.add_argument("--quiet", action="store_true", help="omit the console")
    args = parser.parse_args()

    width, _, height = args.size.partition("x")
    with Browser(int(width), int(height)) as browser:
        browser.call("Page.navigate", {"url": args.url})
        deadline = time.time() + 30
        while time.time() < deadline:
            if any(e["method"] == "Page.loadEventFired" for e in browser.events):
                break
            browser.settle(0.05)

        if args.wait and not browser.until(args.wait):
            print("shot: --wait never became true", file=sys.stderr)
        if args.script:
            result = browser.evaluate(args.script)
            if "exceptionDetails" in result:
                print(f"shot: --eval threw: {result['exceptionDetails']}",
                      file=sys.stderr)
        browser.settle(args.settle)

        data = base64.b64decode(browser.call(
            "Page.captureScreenshot", {"format": "png"})["data"])
        with open(args.out, "wb") as handle:
            handle.write(data)
        if not args.quiet:
            print("\n".join(browser.console()))
        print(f"shot: {args.out} {len(data)} bytes {width}x{height}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
