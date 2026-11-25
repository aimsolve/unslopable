"""links (script): every link of TEXT.md resolves; an external one opens, an internal one matches a heading."""
from __future__ import annotations

import re

from docs import Doc
from common import Failure, _raw_text_lines


# Links. External ones are opened (GET, headers only); every result is cached per URL in the document's
# `.gates/links.json`, so a write does not wait for a link checked recently.
LINK_TIMEOUT = 8          # seconds per request
LINK_DEADLINE = 25        # seconds for all the links of one write; the rest go to a note, unchecked
LINK_TTL_OK = 7 * 86400   # a link that opened is trusted this long
LINK_TTL_BAD = 30 * 60    # a failing or unchecked link is tried again after this
_URL_CHARS = r"(?:[^()\s<>]|\([^()\s<>]*\))"   # a URL may hold balanced brackets: …/Mercury_(planet)
_INLINE_LINK = re.compile(r"(!?)\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*(?:<([^>]*)>|(" + _URL_CHARS + r"*))"
                          r"(?:\s+[\"'(][^)]*[\"')])?\s*\)")
_REF_DEF = re.compile(r"^\s{0,3}\[(?!\^)[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")   # [^1]: is a footnote, not a link
_AUTOLINK = re.compile(r"<((?:https?|mailto):[^>\s]+)>", re.I)
_BARE_URL = re.compile(r"https?://(?:[^\s<>()\[\]]|\([^()\s<>]*\))+", re.I)


def _link_target(m: re.Match) -> str:
    return (m.group(2) if m.group(2) is not None else m.group(3) or "").strip()


def _slug(heading: str) -> str:
    t = _INLINE_LINK.sub(lambda m: m.group(0)[m.group(0).index("[") + 1:m.group(0).index("](")], heading)
    t = re.sub(r"[*`]", "", t).strip().lower()
    return re.sub(r"\s", "-", re.sub(r"[^\w\- ]", "", t))


def heading_anchors(doc: Doc) -> set[str]:
    """The anchors the headings of TEXT.md give: an explicit `{#id}`, else the GitHub-style slug (with -1, -2… for
    repeated headings)."""
    out, seen = set(), {}
    for n, line in _raw_text_lines(doc, blank_code=False):
        m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if not m:
            continue
        h = m.group(1)
        explicit = re.search(r"\{#([^}\s]+)\}\s*$", h)
        if explicit:
            out.add(explicit.group(1).lower())
            h = h[:explicit.start()]
        s = _slug(h)
        k = seen.get(s, 0)
        seen[s] = k + 1
        out.add(s if k == 0 else f"{s}-{k}")
    return out


def text_links(doc: Doc) -> list[tuple[int, str]]:
    """(line, target) of every link in TEXT.md: inline links, reference definitions, autolinks and bare URLs. Images
    are left out: a figure's file is the figure gates' business."""
    out = []
    for n, line in _raw_text_lines(doc):
        for m in _INLINE_LINK.finditer(line):
            if not m.group(1) and _link_target(m):
                out.append((n, _link_target(m)))
        rest = _INLINE_LINK.sub(lambda m: " " * len(m.group(0)), line)
        d = _REF_DEF.match(rest)
        if d:
            out.append((n, d.group(1)))
            continue
        for m in _AUTOLINK.finditer(rest):
            out.append((n, m.group(1)))
        rest = _AUTOLINK.sub(lambda m: " " * len(m.group(0)), rest)
        for m in _BARE_URL.finditer(rest):
            out.append((n, m.group(0).rstrip(".,;:!?»\"'")))
    return out


def open_url(url: str, timeout: float = LINK_TIMEOUT) -> tuple[str, str]:
    """('ok' | 'fail' | 'unknown', what happened) for one external URL, opened with GET (only the headers are read;
    many servers answer HEAD wrongly or slowly). 'unknown': the site would not tell (it refuses scripts, is down for a
    moment, or did not answer in time), so the link is neither passed nor failed. Never raises."""
    import http.client
    import socket
    import ssl
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; link-check)", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return "ok", f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return "fail", f"HTTP {e.code}: the page is not there"
        if e.code in (401, 403, 429, 999):
            return "unknown", f"HTTP {e.code}: the site refuses scripted requests"
        if e.code >= 500:
            return "unknown", f"HTTP {e.code}: the server failed, maybe for a moment"
        return "fail", f"HTTP {e.code}"
    except (socket.timeout, TimeoutError):
        return "unknown", f"no answer in {timeout:g} s"
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            return "unknown", f"no answer in {timeout:g} s"
        if isinstance(reason, socket.gaierror):
            return "fail", "the host does not exist"
        if isinstance(reason, ssl.SSLError):
            return "fail", f"broken HTTPS: {reason}"
        return "fail", str(reason)
    except (http.client.RemoteDisconnected, http.client.IncompleteRead) as e:
        return "unknown", f"the server dropped the connection ({type(e).__name__})"
    except http.client.HTTPException as e:
        return "fail", f"the server does not answer as a web page ({type(e).__name__})"
    except (ValueError, OSError) as e:
        return "fail", str(e)
    except Exception as e:  # one odd server must never stop the gates
        return "unknown", f"could not check ({type(e).__name__})"


def _check_external(doc: Doc, urls: list[str]) -> dict[str, tuple[str, str]]:
    """The result of every URL: from the cache when fresh, else opened, all at once in daemon threads under one
    deadline (a URL still open at the deadline is 'unknown' and not cached). Entries of URLs no longer in the text are
    dropped from the cache."""
    import threading
    import time

    import state as gstate
    cache_file = doc.folder / ".gates" / "links.json"
    cache = gstate.read(cache_file)
    now = time.time()
    out, todo = {}, []
    for u in urls:
        c = cache.get(u) or {}
        st = c.get("status")
        if st and now - c.get("time", 0) < (LINK_TTL_OK if st == "ok" else LINK_TTL_BAD):
            out[u] = (st, c.get("detail", ""))
        else:
            todo.append(u)
    got: dict[str, tuple[str, str]] = {}

    def work(u: str) -> None:
        got[u] = open_url(u)
    threads = []
    for i in range(0, len(todo), 8):  # at most 8 at a time
        batch = [threading.Thread(target=work, args=(u,), daemon=True) for u in todo[i:i + 8]]
        for t in batch:
            t.start()
        threads += batch
        for t in batch:
            t.join(max(0.0, now + LINK_DEADLINE - time.time()))
        if time.time() >= now + LINK_DEADLINE:
            break
    done = {u: got[u] for u in todo if u in got}
    for u in todo:
        out[u] = done.get(u, ("unknown", f"not checked within {LINK_DEADLINE} s of this write"))
    keep = set(urls)
    if done or any(u not in keep for u in cache):
        try:
            gstate.update(cache_file, lambda d: (
                [d.pop(k) for k in list(d) if k not in keep],
                d.update({u: {"status": s, "detail": det, "time": now} for u, (s, det) in done.items()})))
        except OSError:
            pass
    return out


def gate_links(doc: Doc, notices: list[str]) -> list[Failure]:
    """An internal link (#anchor) matches a heading of the text; a link to a file names a file inside the document's
    folder; an external link opens."""
    import difflib
    from urllib.parse import unquote
    links = text_links(doc)
    anchors = heading_anchors(doc)
    folder = doc.folder.resolve()
    out, external = [], []
    for n, target in links:
        scheme = re.match(r"^([a-z][a-z0-9+.-]*):", target, re.I)
        if scheme:
            if scheme.group(1).lower() in ("http", "https"):
                external.append((n, target))
            continue  # mailto:, tel: and the like are not opened
        path, _, frag = target.partition("#")
        if not path:
            a = unquote(frag).lower()
            if a not in anchors:
                near = difflib.get_close_matches(a, sorted(anchors), n=3)
                out.append(Failure("links", f"TEXT.md line {n}", target,
                                   "the link points to no heading of the text; link to an existing heading"
                                   + (f" (close: {', '.join('#' + x for x in near)})" if near else "")))
            continue
        p = (doc.folder / unquote(path)).resolve()
        if not p.exists() or (p != folder and folder not in p.parents):
            out.append(Failure("links", f"TEXT.md line {n}", target,
                               "the link names a file that is not in the document's folder"))
    if external:
        results = _check_external(doc, list(dict.fromkeys(u for _, u in external)))
        unknown = set()
        for n, u in external:
            status, detail = results[u]
            if status == "fail":
                out.append(Failure("links", f"TEXT.md line {n}", u, f"the link does not open ({detail})"))
            elif status == "unknown":
                unknown.add(f"{u} ({detail})")
        if unknown:
            notices.append("links that could not be checked, open them by hand: " + "; ".join(sorted(unknown)))
    return out
