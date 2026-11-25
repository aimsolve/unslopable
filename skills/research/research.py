#!/usr/bin/env python3
"""The research stage's tool: the fact base of one document folder, for the lead agent and its readers.

    research.py fetch <folder> <url> [<url> ...]      save pages as plain text (stdlib, no model)
    research.py save <folder> <url>  < text            save a page read some other way (e.g. WebFetch)
    research.py add <folder> --url <url>  < json       add one fact (object) or several (array)
    research.py entities <folder>                      the entity names in the base
    research.py list <folder>                          the base, by entity
    research.py duplicates <folder>                    entities, or attributes, that may be one
    research.py merge <folder> <canonical> <alias>...  move the aliases' facts to one name
    research.py merge-attribute <folder> <entity> <canonical> <alias>...   one name for one attribute
    research.py remove <folder> <id> --reason <r>      take a fact that does not hold out of the base
    research.py gap <folder>  < text                   what the brief asked for and was not found
    research.py finish <folder>                        settle conflicts, write FACTS.md

Every answer is one line per result, for the agent to act on. The checks are in gates/lib/facts.py.
"""
from __future__ import annotations

import argparse
import http.client
import json
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gates" / "lib"))
import facts as fb  # noqa: E402

SKIP = {"script", "style", "noscript", "nav", "footer", "svg", "template", "iframe", "button", "select", "textarea"}
BLOCK = {"p", "div", "section", "article", "main", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5",
         "h6", "br", "dt", "dd", "blockquote", "pre", "figcaption", "td", "th"}
VOID = {"br", "img", "hr", "meta", "link", "input", "source", "wbr", "area", "base", "col", "embed", "track"}
AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def page_text(html: str) -> str:
    """The readable text of an HTML page: scripts, styles, navigation, footer and forms dropped (a header and an aside
    stay: an article's title, date and spec boxes are often there); one line per block."""
    p = _Text()
    p.feed(html)
    p.close()
    lines = [" ".join(line.split()) for line in "".join(p.out).split("\n")]
    return "\n".join(line for line in lines if line)


def _decode(raw: bytes, ctype: str) -> str:
    """The page's bytes as text: the charset of the header, else of a <meta> in the first 2 KB, else UTF-8."""
    m = re.search(r"charset=[\"']?([\w-]+)", ctype) or re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:2048], re.I)
    charset = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def download(url: str) -> str:
    """The page's text, or raises with a short reason."""
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5"})
    with urllib.request.urlopen(req, timeout=60) as r:
        ctype = r.headers.get("Content-Type", "")
        raw = r.read(5_000_000)
    if "html" not in ctype and "text" not in ctype and ctype:
        raise ValueError(f"not a web page ({ctype.split(';')[0]})")
    body = _decode(raw, ctype)
    return page_text(body) if "html" in ctype or "<html" in body[:2000].lower() else body


def _stdin() -> str:
    return sys.stdin.read() if not sys.stdin.isatty() else ""


def main(argv: list[str]) -> int:
    try:
        return run(argv)
    except fb.BaseUnreadable as e:
        print(f"refused: {e}")
        return 0


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="research.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "save", "add", "remove", "entities", "list", "duplicates", "merge", "merge-attribute", "gap",
                 "finish"):
        p = sub.add_parser(name)
        p.add_argument("folder")
        if name == "merge-attribute":
            p.add_argument("entity")
        if name in ("fetch", "merge", "merge-attribute"):
            p.add_argument("names", nargs="+")
        elif name in ("save", "remove"):
            p.add_argument("name")
        if name == "remove":
            p.add_argument("--reason", required=True)
        if name == "add":
            p.add_argument("--url", required=True)
    a = ap.parse_args(argv)
    folder = Path(a.folder).expanduser().resolve()
    base = fb.FactBase(folder)
    out: list[str] = []

    if a.cmd == "fetch":
        for url in a.names:
            with base.changing():
                why = base.may_fetch(url)
            if why:
                out.append(f"not fetched {url}: {why}")
                continue
            try:
                text = download(url)
            except (urllib.error.URLError, http.client.HTTPException, ValueError, OSError) as e:
                out.append(f"could not fetch {url} ({str(getattr(e, 'reason', e))[:100]}); read it with WebFetch "
                           "and pass its text to `save`")
                continue
            if len(text.strip()) < fb.MIN_PAGE_CHARS:
                out.append(f"empty {url}: the page has almost no text (a page drawn by scripts?); read it with "
                           "WebFetch and pass its text to `save`")
                continue
            with base.changing():  # the budget again: another fetch may have saved pages while this one downloaded
                why = base.may_save(url)
                out.append(f"not saved {url}: {why}" if why else base.save_page(url, text, fb.VIA_SCRIPT))
    elif a.cmd == "save":
        text = _stdin()
        with base.changing():
            why = base.may_save(a.name)
            if why:
                out.append(f"not saved {a.name}: {why}")
            elif len(text.strip()) < fb.MIN_PAGE_CHARS:
                out.append(f"empty {a.name}: the text is under {fb.MIN_PAGE_CHARS} characters")
            else:
                out.append(base.save_page(a.name, text, fb.VIA_WEBFETCH))
    elif a.cmd == "add":
        try:
            data = json.loads(_stdin() or "null")
        except ValueError as e:
            print(f"rejected: stdin is not JSON ({e})")
            return 0
        items = data if isinstance(data, list) else [data]
        with base.changing():
            for f in items:
                out.append(base.add(f, a.url) if isinstance(f, dict) else "rejected: a fact is a JSON object")
    elif a.cmd == "remove":
        with base.changing():
            out.append(base.remove(a.name, a.reason))
    elif a.cmd == "entities":
        out = base.load().entity_lines() or ["(none yet)"]
    elif a.cmd == "list":
        out = [base.load().compact()]
    elif a.cmd == "duplicates":
        out = base.load().duplicates() or ["no candidates"]
    elif a.cmd == "merge":
        with base.changing():
            out.append(base.merge(a.names[0], a.names[1:]))
    elif a.cmd == "merge-attribute":
        with base.changing():
            out.append(base.merge_attribute(a.entity, a.names[0], a.names[1:]) if len(a.names) > 1
                       else "refused: name the canonical attribute and at least one alias")
    elif a.cmd == "gap":
        text = _stdin()
        with base.changing():
            out.append(base.add_gap(text))
    elif a.cmd == "finish":
        with base.changing():
            bad = base.failing()
            if bad:
                print(f"refused: {len(bad)} facts of the base do not hold, {fb.DOSSIER} not written:\n" + "\n".join(
                    f"- {f.get('id', '?') if isinstance(f, dict) else '?'}: {why}" for f, why in bad))
                return 0
            dropped = base.settle()
            (folder / fb.DOSSIER).write_text(base.dossier(), encoding="utf-8")
            out.append(f"{fb.DOSSIER} written: {len(base.facts)} facts, {len(base.by_entity())} entities, "
                       f"{dropped} dropped in conflicts, {len(base.data['sources'])} pages")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
