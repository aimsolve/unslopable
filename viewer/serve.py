#!/usr/bin/env python3
"""The viewer's local server: one page with a document's timeline, read live from the document's folder.

  python3 viewer/serve.py [--port 8765] [<document folder>]           serve (in the foreground)
  python3 viewer/serve.py [--port 8765] --open [<document folder>]    open the page of the viewer that serves

Serves on 127.0.0.1 only and answers only requests addressed to 127.0.0.1 or localhost (a page elsewhere cannot
reach it through its own name). If a viewer of this same code already answers on the port, it is reused; one of
older code is stopped and replaced. Prints the page's URL (with the folder picked when one is given). `--open` never
serves: it waits a few seconds for the viewer, then opens the page in the default browser.

  GET /                                  the page (viewer/page.html)
  GET /api/documents                     the document folders the gate hook has seen, newest first
  GET /api/timeline?folder=F[&since=SIG] timeline.read_timeline(F), or {"unchanged": true} while its signature is SIG
  GET /api/input?folder=F&id=J           the prompt judge J got (.gates/inputs/J.md)
  GET /api/file?folder=F&file=R          a file of the document as it is now (R relative, not hidden)
  GET /api/blob?folder=F&blob=B          a kept version of a file (.gates/history/blobs/B)

A folder is served only when it has a BRIEF.md; files only from the places above, by names that cannot leave them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import timeline  # noqa: E402
import history  # noqa: E402  (gates/lib, put on the path by timeline)

PAGE = HERE / "page.html"
PORT = 8765


def _version() -> str:
    """The viewer's code: its hash and the time of its newest file, so a viewer started from older code (before the
    plugin was updated) is replaced, and one from newer code (another checkout) is left alone."""
    h, newest = hashlib.sha1(), 0
    for p in sorted(HERE.glob("*.py")) + [PAGE, Path(history.__file__)]:
        try:
            h.update(p.read_bytes())
            newest = max(newest, int(p.stat().st_mtime))
        except OSError:
            pass
    return f"{h.hexdigest()[:12]} {newest}"


PING = f"unslopable-viewer {_version()}"


def _older(other: str) -> bool:
    """Whether the viewer that answered `other` runs code older than this one."""
    try:
        return int(other.split()[2]) < int(PING.split()[2])
    except (IndexError, ValueError):
        return True  # a viewer from before the ping carried a time
_JUDGE_ID = re.compile(r"[A-Za-z0-9_-]+")
_BLOB = re.compile(r"[0-9a-f]{40}\.[A-Za-z0-9]+")
_LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (/.+?) (?:PLAN\.md|TEXT\.md|figures/|fact base)")


_LOG_CACHE: dict = {}


def _log_documents(log: Path) -> dict[str, str]:
    """folder -> last time, from the gate hook's log; read again only when the log changed."""
    try:
        st = log.stat()
    except OSError:
        return {}
    key = (str(log), st.st_mtime_ns, st.st_size)
    if _LOG_CACHE.get("key") != key:
        seen: dict[str, str] = {}
        with open(log, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _LOG_LINE.match(line)
                if m:
                    seen[m.group(2)] = max(seen.get(m.group(2), ""), m.group(1))
        _LOG_CACHE.update(key=key, documents=seen)
    return dict(_LOG_CACHE["documents"])


def documents() -> list[dict]:
    """Every document folder the gate hook has kept a version of (history.registry), and the ones its log names from
    before it kept any; only folders that still have a BRIEF.md."""
    seen = _log_documents(history.cache_dir() / "gate_run.log")
    for path in (history.cache_dir() / "runs.json", history.registry()):  # runs.json: the registry before 25.11
        try:
            reg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            reg = {}
        for folder, when in (reg.items() if isinstance(reg, dict) else []):
            seen[folder] = max(seen.get(folder, ""), str(when))
    out = [{"folder": f, "name": Path(f).name, "parent": Path(f).parent.name, "time": t}
           for f, t in seen.items() if (Path(f) / "BRIEF.md").is_file()]
    return sorted(out, key=lambda d: d["time"], reverse=True)


def doc_folder(value: str) -> Path | None:
    if not value:
        return None
    p = Path(value).expanduser()
    return p if p.is_absolute() and (p / "BRIEF.md").is_file() else None


class Handler(BaseHTTPRequestHandler):
    server_version = "unslopable-viewer"
    cache: dict = {}
    lock = threading.Lock()

    def log_message(self, *args) -> None:  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _text(self, text: str, code: int = 200) -> None:
        self._send(code, text.encode("utf-8"), "text/plain; charset=utf-8")

    def _file(self, path: Path, sandbox: bool = False) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            return self._text("not found", 404)
        # a document's own file (an .svg, an .html) opened from the page runs no script on the viewer's origin
        self._send(200, body, mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                   {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"} if sandbox else {})

    def do_GET(self) -> None:  # noqa: N802
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return self._text("this viewer answers only at 127.0.0.1 or localhost", 403)
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            self._route(url.path, q)
        except Exception as e:  # noqa: BLE001 — a broken document must not take the server down
            self._text(f"error: {e!r}", 500)

    def _route(self, path: str, q: dict) -> None:
        if path in ("/", "/index.html"):
            return self._file(PAGE) if PAGE.exists() else self._text("page.html is missing", 500)
        if path == "/api/ping":
            return self._text(PING)
        if path == "/api/documents":
            return self._json(documents())
        folder = doc_folder(q.get("folder", ""))
        if not path.startswith("/api/"):
            return self._text("not found", 404)
        if folder is None:
            return self._text("no document folder (a folder with BRIEF.md) given", 404)
        if path == "/api/timeline":
            sig = timeline.signature(folder)
            if q.get("since") == sig:
                return self._json({"unchanged": True, "signature": sig})
            with self.lock:
                hit = self.cache.get(str(folder))
                if not hit or hit[0] != sig:
                    hit = (sig, timeline.read_timeline(folder))
                    self.cache[str(folder)] = hit
            return self._json(hit[1])
        if path == "/api/input":
            jid = q.get("id", "")
            if not _JUDGE_ID.fullmatch(jid):
                return self._text("bad judge id", 400)
            return self._file(folder / ".gates" / "inputs" / f"{jid}.md")
        if path == "/api/file":
            rel = q.get("file", "")
            parts = Path(rel).parts
            if not rel or Path(rel).is_absolute() or ".." in parts or any(x.startswith(".") for x in parts):
                return self._text("bad file path", 400)
            target = (folder / rel).resolve()
            if folder.resolve() not in target.parents:  # a link that leads out of the document
                return self._text("bad file path", 400)
            return self._file(target, sandbox=True)
        if path == "/api/blob":
            blob = q.get("blob", "")
            if not _BLOB.fullmatch(blob):
                return self._text("bad blob name", 400)
            return self._file(history.blob_path(folder, blob), sandbox=True)
        return self._text("not found", 404)


def ping(port: int) -> str:
    """What answers on the port: this viewer's PING, another viewer's, or '' (nothing, or not a viewer)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            text = r.read().decode(errors="replace")
            return text if text.startswith("unslopable-viewer") else ""
    except (OSError, ValueError):
        return ""


def taken(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def stop_older(port: int) -> None:
    """Stop the viewer of older code that listens on the port (found by `lsof`), and wait until the port is free."""
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return
    for pid in {int(x) for x in out.split() if x.isdigit()} - {os.getpid()}:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(30):
        if not ping(port):
            return
        time.sleep(0.1)


def page_url(port: int, folder: Path | None) -> str:
    base = f"http://127.0.0.1:{port}/"
    return base + ("?folder=" + urllib.parse.quote(str(folder)) if folder else "")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="The unslopable document viewer.")
    ap.add_argument("folder", nargs="?", help="a document folder (one with BRIEF.md)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--open", action="store_true", help="open the page in the default browser")
    a = ap.parse_args(argv)
    folder = None
    if a.folder:
        folder = doc_folder(str(Path(a.folder).expanduser().resolve()))
        if folder is None:
            print(f"not a document folder (no BRIEF.md): {a.folder}")
            return 1
    url = page_url(a.port, folder)
    if a.open:  # never serves: the viewer is started on its own, so it outlives whoever opens the page
        deadline = time.time() + 5
        while time.time() < deadline:
            if ping(a.port):
                print(f"viewer: {url}", flush=True)
                webbrowser.open(url)
                return 0
            time.sleep(0.1)
        if taken(a.port):
            print(f"port {a.port} is taken by another program, not the viewer; use another port with --port")
        else:
            print(f"no viewer answers on port {a.port}; start it first: python3 {Path(__file__)} --port {a.port}")
        return 1
    found = ping(a.port)
    if found and (found == PING or not _older(found)):
        print(f"viewer already running: {url}", flush=True)
        return 0
    if found:
        stop_older(a.port)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    except OSError as e:
        print(f"port {a.port} is taken ({e}); pass another with --port")
        return 1
    print(f"viewer: {url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
