#!/usr/bin/env python3
"""Dev server: serve docs/, and rebuild the bundle whenever data/cmip7_request.yaml changes.

`make dev` runs this. The repo is bind-mounted into the container, so edits on
the host are visible immediately; this closes the two gaps that leaves:

  * editing the request YAML leaves docs/data.json stale until you remember to build
  * the browser has no idea anything changed

Files are served with no-store so a reload always gets the current bytes, and
the page's own dev-reload poller (see docs/index.html, localhost only) watches
Last-Modified and reloads itself.

Stdlib only, polling mtimes -- a dozen files every half second costs nothing and
beats taking a dependency on a file-watching library.
"""

import http.server
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WATCH = ROOT / "data"
SERVE = ROOT / "docs"
PORT = 8000


def snapshot():
    return {p: p.stat().st_mtime for p in sorted(WATCH.glob("cmip7_request.yaml"))}


def build():
    """Regenerate docs/data.json, reporting either the summary or the error."""
    done = subprocess.run([sys.executable, str(ROOT / "build.py")],
                          capture_output=True, text=True)
    stamp = time.strftime("%H:%M:%S")
    if done.returncode == 0:
        print(f"[{stamp}] {done.stdout.strip()}", flush=True)
    else:
        # A bad edit should be loud but must not kill the server -- fix the YAML
        # and the next save rebuilds.
        tail = (done.stderr.strip() or done.stdout.strip()).splitlines()
        print(f"[{stamp}] BUILD FAILED", *tail[-12:], sep="\n  ", flush=True)


def watch():
    seen = snapshot()
    while True:
        time.sleep(0.5)
        now = snapshot()
        if now != seen:
            seen = now
            build()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(SERVE), **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        # The reload poller sends a request a second; only report problems.
        if not str(args[1] if len(args) > 1 else "").startswith("2"):
            super().log_message(fmt, *args)


def main():
    build()
    threading.Thread(target=watch, daemon=True).start()
    print(f"serving {SERVE.name}/ on http://localhost:{PORT}  "
          f"(watching {WATCH.name}/cmip7_request.yaml; the page reloads itself)", flush=True)
    try:
        http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
