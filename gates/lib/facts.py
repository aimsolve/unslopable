"""The research stage's fact base: records instead of a pile of text.

A fact enters the base only through `FactBase.add`, and everything code can check is checked there:
  - the source is a page that was really saved (`research/sources/`);
  - the quote is in that page's text, word for word (case, spacing, quote marks and dashes aside);
  - the numbers of the value are in the quote; every part of a date (year, month, day) is in the quote.
The answer is a line for the agent, `ok F12` or `rejected: <reason>`, so it can fix the record at once.

`settle` keeps one value per attribute of an entity: the stronger source wins, equally strong sources that disagree
leave no value; what is dropped stays listed with its reason. `gaps` are what the brief asked for and the research
could not find. `dossier` is FACTS.md, built from the base: the facts with their sources, what was left out and
why, the saved pages, and the gaps; no conclusions and no advice for the plan.

Files of a document folder: `research/facts.json` (the base), `research/sources/NN.txt` (saved pages), `FACTS.md`.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import date
from pathlib import Path

ENTITY_KINDS = ("product", "organization", "person", "place", "event", "concept", "other")
FACT_TYPES = ("date", "time", "number", "price", "address", "claim")
SINGLE_VALUED = ("date", "time", "number", "price", "address")  # one value per attribute of an entity
SOURCE_KINDS = ("official", "aggregator", "media", "review")
STRENGTH = {"official": 1, "aggregator": 2, "media": 2, "review": 3}  # the order matters: smaller is stronger
MAX_PAGES = 10          # pages saved per document
PAGE_CHARS = 300_000    # a page longer than this is cut, and `saved` says so
MIN_PAGE_CHARS = 200    # a shorter text is taken for a page drawn by scripts: it goes to WebFetch
BASE = Path("research") / "facts.json"
SOURCES = Path("research") / "sources"
DOSSIER = "FACTS.md"
VIA_SCRIPT, VIA_WEBFETCH = "script", "WebFetch"

# Month names, whole words with their inflected forms (English, German, French, Spanish, Italian, Portuguese,
# Polish, Russian, Ukrainian). A name counts only next to a number (a day or a year), as in every written date.
MONTHS = {
    1: "january jan januar jänner janvier janv enero ene gennaio gen janeiro styczeń stycznia январь января січень січня",
    2: "february feb februar février fevrier févr fevr febrero febbraio fevereiro luty lutego февраль февраля лютий "
       "лютого",
    3: "march mar märz maerz mars marzo março marzec marca март марта березень березня",
    4: "april apr avril avr abril abr aprile kwiecień kwietnia апрель апреля квітень квітня",
    5: "may mai mayo maggio mag maio maj maja май мая травень травня",
    6: "june jun juni juin junio giugno giu junho czerwiec czerwca июнь июня червень червня",
    7: "july jul juli juillet juil julio luglio lug julho lipiec lipca июль июля липень липня",
    8: "august aug août aout agosto ago sierpień sierpnia август августа серпень серпня",
    9: "september sep sept septembre septiembre setiembre settembre set setembro wrzesień września сентябрь "
       "сентября вересень вересня",
    10: "october oct oktober okt octobre octubre ottobre ott outubro październik października октябрь октября "
        "жовтень жовтня",
    11: "november nov novembre noviembre novembro listopad listopada ноябрь ноября листопад листопада",
    12: "december dec dezember dez décembre decembre déc diciembre dicembre dic dezembro grudzień grudnia декабрь "
        "декабря грудень грудня",
}
NEAR = 2  # a month name's day or year is at most this many tokens away


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[‐-―−]", "-", text)                  # dashes and minus
    text = re.sub(r"[‘-‟«»\"'`]", "", text)         # quote marks are not compared
    return re.sub(r"\s+", " ", text).strip()


_NUMBER = re.compile(r"(\d{1,3}(?:[,. ]\d{3})+(?!\d)|\d+[.,](?!0+(?!\d))\d+|\d+)(?:[.,]0+(?!\d))?")


def _number(n: str) -> str:
    if re.fullmatch(r"\d+[.,]\d+", n) and not re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", n):
        whole, frac = re.split(r"[.,]", n)
        return f"{whole.lstrip('0') or '0'}.{frac.rstrip('0')}"
    return re.sub(r"\D", "", n).lstrip("0") or "0"


def numbers(text: str) -> list[str]:
    """Numbers of a text; a digit group with thousands separators is one number («1,500» = «1500»), a decimal is one
    number («1.5» ≠ «5.1»), and a decimal part of zeros is no number of its own («1.250,00» = «1250»)."""
    return [_number(n) for n in _NUMBER.findall(unicodedata.normalize("NFKC", text or ""))]


def words(text: str) -> list[str]:
    """The words of a value without its numbers: units, currencies, names."""
    return re.findall(r"[^\W\d_]+|[^\w\s.,;:/()-]", norm(text))


def parse_date(value: str) -> list[tuple[int, int | None, int | None]] | None:
    """`YYYY`, `YYYY-MM`, `YYYY-MM-DD`, or a span `A/B` of those with A <= B -> [(year, month, day), ...]."""
    out = []
    for part in [p.strip() for p in value.split("/")]:
        m = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", part)
        if not m:
            return None
        y, mo, d = int(m.group(1)), m.group(2) and int(m.group(2)), m.group(3) and int(m.group(3))
        try:
            date(y, mo or 1, d or 1)
        except ValueError:
            return None
        out.append((y, mo, d))
    if len(out) > 2 or (len(out) == 2 and (out[0][0], out[0][1] or 0, out[0][2] or 0) >
                        (out[1][0], out[1][1] or 0, out[1][2] or 0)):
        return None
    return out


_NUMERIC_DATE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})(?!\d)"
                           r"|(?<!\d)(\d{4})-(\d{2})(?:-(\d{2}))?(?!\d)")


def _numeric_dates(quote: str) -> list[tuple[int, tuple[int, int] | None, int | None]]:
    """(year, (day, month) readings, ...) of the numeric dates of the quote: 5.3.2024 reads as day 5 of March or day 3
    of May; 2024-03-05 and 2024-03 read one way."""
    out = []
    for m in _NUMERIC_DATE.finditer(quote):
        if m.group(4):
            day = int(m.group(6)) if m.group(6) else None
            out.append((int(m.group(4)), int(m.group(5)), day))
        else:
            a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
            year = int(y) if len(y) == 4 else 2000 + int(y)
            out += [(year, b, a), (year, a, b)]
    return out


def _is_day(token: str, day: int) -> bool:
    return bool(re.fullmatch(rf"0?{day}(?:st|nd|rd|th|er|e|o|º|°)?", token))


def date_in(quote: str, year: int, month: int | None, day: int | None) -> str:
    """'' when every given part of the date is in the quote, else which is not. The year as a number; the month and
    the day together in a numeric date, or the month by its name next to a number and the day a number next to it."""
    q = norm(quote)
    if not re.search(rf"(?<!\d){year}(?!\d)", q):
        return "the year of the date is not in the quote; record only what the page says"
    if month is None:
        return ""
    if any(y == year and mo == month and (day is None or d == day) for y, mo, d in _numeric_dates(q)):
        return ""
    tokens = re.findall(r"\w+", q)
    names = set(MONTHS[month].split())

    def near(i: int) -> range:
        return range(max(0, i - NEAR), min(len(tokens), i + NEAR + 1))

    at = [i for i, t in enumerate(tokens) if t in names and any(re.match(r"\d", tokens[k]) for k in near(i) if k != i)]
    if not at:
        return "the month of the date is not in the quote"
    if day is not None and not any(_is_day(tokens[k], day) for i in at for k in near(i) if k != i):
        return "the day of the date is not in the quote next to its month"
    return ""


def same_value(a: str, b: str) -> bool:
    """One value written two ways: the same numbers, and every word of one starts a word of the other
    («1,250 EUR» = «1250 EUR», «Main St 5» = «Main Street 5», «1500 l» = «1,500 litres»; «35 EUR» ≠ «35 PLN»,
    «8 m» ≠ «8 ft»)."""
    if numbers(a) != numbers(b):
        return False
    wa, wb = words(a), words(b)
    if not numbers(a) and not wa and not wb:
        return norm(a) == norm(b)
    return prefixes_of(wa, wb) or prefixes_of(wb, wa)


def prefixes_of(short: list[str], long_: list[str]) -> bool:
    """Every word of `short` starts a word of `long_`."""
    return all(any(w.startswith(s) for w in long_) for s in short)


def check_fact(f: dict, pages: dict[str, str]) -> str:
    """'' when the fact holds, else why not. `pages`: url -> saved text."""
    entity, ftype = (f.get("entity") or "").strip(), f.get("type")
    value, quote = str(f.get("value") or "").strip(), (f.get("quote") or "").strip()
    url = f.get("source_url") or ""
    if not entity or not value:
        return "entity and value are required"
    if ftype not in FACT_TYPES:
        return f"type must be one of {', '.join(FACT_TYPES)}"
    if f.get("entity_kind") not in ENTITY_KINDS:
        return f"entity_kind must be one of {', '.join(ENTITY_KINDS)}"
    if f.get("source_kind") not in SOURCE_KINDS:
        return f"source_kind must be one of {', '.join(SOURCE_KINDS)}"
    if ftype in SINGLE_VALUED and not (f.get("attribute") or "").strip():
        return f"attribute is required for a {ftype}: say what the value is of"
    if url not in pages:
        return "source url is not a saved page; cite the exact url you were given"
    if not quote:
        return "quote is required: copy the exact words from the page"
    if norm(quote) not in norm(pages[url]):
        return "quote not found verbatim in the saved page"
    if ftype == "date":
        parts = parse_date(value)
        if parts is None:
            return "a date value is YYYY, YYYY-MM, YYYY-MM-DD, or a span A/B of those"
        for y, mo, d in parts:
            why = date_in(quote, y, mo, d)
            if why:
                return why
        return ""
    missing = [n for n in numbers(value) if n not in numbers(quote)]
    if missing:
        return f"numbers {', '.join(missing)} of the value are not in the quote"
    if ftype in ("number", "price", "address"):
        qw = words(quote)
        absent = [w for w in words(value) if not any(q.startswith(w) or w.startswith(q) for q in qw)]
        if absent:
            return f"{', '.join(absent)} of the value not in the quote; write the value in the page's words"
    if ftype == "claim" and len(quote.split()) < 3:
        return "a claim's quote is the page's sentence that states it: three words at least"
    return ""


class BaseUnreadable(Exception):
    """research/facts.json exists but is not a fact base: nothing is written over it."""


class FactBase:
    """The base of one document folder. Every change runs under a lock and is written back atomically, so readers
    adding facts at once never lose each other's facts or share an id."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.path = self.folder / BASE
        self.data: dict = {}

    # ---------------------------------------------------------------- storage

    @contextmanager
    def changing(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.parent / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                self.data = self._read()
                yield self
                fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".tmp-")
                with os.fdopen(fd, "w", encoding="utf-8") as out:
                    json.dump(self.data, out, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def load(self) -> "FactBase":
        self.data = self._read()
        return self

    def _read(self) -> dict:
        if not self.path.exists():
            data = {}
        else:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise BaseUnreadable(f"{BASE} is not valid JSON ({e}); restore it, nothing was written") from e
            if not isinstance(data, dict):
                raise BaseUnreadable(f"{BASE} is not a fact base (a JSON object); restore it, nothing was written")
        for key, empty in (("next_id", 1), ("sources", {}), ("tried", []), ("facts", []), ("rejected", []),
                           ("dropped", []), ("gaps", [])):
            data.setdefault(key, empty)
        return data

    @property
    def facts(self) -> list[dict]:
        return self.data["facts"]

    def pages(self) -> dict[str, str]:
        out = {}
        for url, src in self.data["sources"].items():
            try:
                out[url] = (self.folder / src["file"]).read_text(encoding="utf-8")
            except (OSError, KeyError, TypeError):
                pass
        return out

    # ---------------------------------------------------------------- sources

    def may_fetch(self, url: str) -> str:
        """'' when the script may fetch `url` now, else why not. Only saved pages use the budget."""
        if url in self.data["sources"]:
            return "saved already"
        if url in self.data["tried"]:
            return "tried already; read it with WebFetch and pass its text to `save`"
        if len(self.data["sources"]) >= MAX_PAGES:
            return f"page budget used up ({MAX_PAGES} pages saved)"
        self.data["tried"].append(url)
        return ""

    def may_save(self, url: str) -> str:
        if url in self.data["sources"]:
            return "saved already"
        if len(self.data["sources"]) >= MAX_PAGES:
            return f"page budget used up ({MAX_PAGES} pages saved)"
        return ""

    def save_page(self, url: str, text: str, via: str) -> str:
        rel = str(SOURCES / f"{len(self.data['sources']) + 1:02d}.txt")
        page = text[:PAGE_CHARS]
        (self.folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.folder / rel).write_text(page, encoding="utf-8")
        self.data["sources"][url] = {"file": rel, "via": via, "saved": date.today().isoformat()}
        cut = f", cut at {PAGE_CHARS} of {len(text)} chars" if len(text) > PAGE_CHARS else ""
        return f"saved {url} -> {rel} ({len(page)} chars{cut})"

    # ---------------------------------------------------------------- facts

    def add(self, f: dict, url: str) -> str:
        f = {**f, "source_url": url}
        why = check_fact(f, self.pages())
        if not why:
            for g in self.facts:
                if (g.get("entity") == f["entity"].strip() and norm(g.get("attribute") or "") == norm(f.get("attribute") or "")
                        and g.get("source_url") == url and numbers(str(g.get("value"))) == numbers(str(f["value"]))
                        and words(str(g.get("value"))) == words(str(f["value"]))):
                    why = f"already in the base as {g['id']}"
                    break
        if why:
            self.data["rejected"].append({"entity": f.get("entity", ""), "value": str(f.get("value", "")),
                                          "source_url": url, "reason": why})
            return f"rejected: {why}"
        fid = f"F{self.data['next_id']}"
        self.data["next_id"] += 1
        self.facts.append({"id": fid, "entity": f["entity"].strip(), "entity_kind": f["entity_kind"],
                           "type": f["type"], "attribute": (f.get("attribute") or "").strip(),
                           "value": str(f["value"]).strip(), "quote": f["quote"].strip(), "source_url": url,
                           "source_kind": f["source_kind"]})
        return f"ok {fid}"

    def by_entity(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for f in self.facts:
            out.setdefault(f.get("entity"), []).append(f)
        return out

    def failing(self) -> list[tuple[dict, str]]:
        """The facts of the base that do not hold (written some other way than `add`), with why."""
        pages, seen, out = self.pages(), set(), []
        for f in self.facts:
            if not isinstance(f, dict):
                out.append(({}, "not a record"))
                continue
            fid = f.get("id")
            why = check_fact(f, pages)
            if not why and not (isinstance(fid, str) and re.fullmatch(r"F\d+", fid)):
                why = "no fact number (`id` F<n>)"
            elif not why and fid in seen:
                why = f"{fid} is the number of another fact too"
            seen.add(fid)
            if why:
                out.append((f, why))
        return out

    def remove(self, fid: str, reason: str) -> str:
        """Take a fact out of the base (one that does not hold, or was added by mistake); it is kept as rejected."""
        for f in self.facts:
            if isinstance(f, dict) and f.get("id") == fid:
                self.facts.remove(f)
                self.data["rejected"].append({"entity": f.get("entity", ""), "value": str(f.get("value", "")),
                                              "source_url": f.get("source_url", ""), "reason": f"removed: {reason}"})
                return f"ok: {fid} removed"
        return f"no fact {fid} in the base"

    def entity_lines(self) -> list[str]:
        out = []
        for name, fs in self.by_entity().items():
            attrs = list(dict.fromkeys(f.get("attribute") for f in fs if f.get("attribute")))
            out.append(name + (f" — attributes: {'; '.join(attrs)}" if attrs else ""))
        return out

    def duplicates(self) -> list[str]:
        """Entities that may be one thing (one name inside the other) and attributes of one entity that may be one
        attribute (every word of one starts a word of the other). The lead agent decides; code only points."""
        def key(name: str) -> str:
            return re.sub(r"\s+", " ", re.sub(r"[^\w ]", " ", norm(name).split("(")[0])).strip()

        groups = self.by_entity()
        names, out = list(groups), []
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ka, kb = key(a), key(b)
                if groups[a][0]["entity_kind"] == groups[b][0]["entity_kind"] and ka and kb and (ka in kb or kb in ka):
                    out.append(f"- entities {a!r} <-> {b!r} (one name contains the other)")
        for name, fs in groups.items():
            attrs = list(dict.fromkeys((f.get("type"), f.get("attribute")) for f in fs if f.get("attribute")))
            for i, (ta, a) in enumerate(attrs):
                for tb, b in attrs[i + 1:]:
                    wa, wb = re.findall(r"\w+", norm(a)), re.findall(r"\w+", norm(b))
                    if ta == tb and norm(a) != norm(b) and wa and wb and (prefixes_of(wa, wb) or prefixes_of(wb, wa)):
                        out.append(f"- attributes of {name!r}: {a!r} <-> {b!r} (one may be the other)")
        return out

    def merge(self, canonical: str, aliases: list[str]) -> str:
        names = set(self.by_entity())
        missing = [a for a in [canonical, *aliases] if a not in names]
        if missing:
            return f"unknown entities: {', '.join(missing)}"
        for f in self.facts:
            if f["entity"] in aliases:
                f["entity"] = canonical
        return f"ok: {len(aliases)} merged into {canonical!r}"

    def merge_attribute(self, entity: str, canonical: str, aliases: list[str]) -> str:
        fs = self.by_entity().get(entity)
        if not fs:
            return f"unknown entity: {entity}"
        have = {f.get("attribute") for f in fs}
        missing = [a for a in [canonical, *aliases] if a not in have]
        if missing:
            return f"unknown attributes of {entity!r}: {', '.join(missing)}"
        for f in fs:
            if f.get("attribute") in aliases:
                f["attribute"] = canonical
        return f"ok: {len(aliases)} attributes of {entity!r} merged into {canonical!r}"

    # ---------------------------------------------------------------- gaps

    def add_gap(self, text: str) -> str:
        """Something the brief asked for that the research could not find, so the planner builds no section on it."""
        text = " ".join((text or "").split())
        if not text:
            return "rejected: the gap is empty; say what the brief asked for and was not found"
        if text not in self.data["gaps"]:
            self.data["gaps"].append(text)
        return "ok"

    # ---------------------------------------------------------------- conflicts

    @staticmethod
    def _key(f: dict) -> tuple:
        return (f.get("entity"), f.get("type"), norm(f.get("attribute") or ""))

    @staticmethod
    def _agree(fs: list[dict]) -> bool:
        """Every two values of these facts are the same value («35» agrees with «35 EUR» and with «35 PLN», but
        those two do not agree, so the three do not)."""
        return all(same_value(str(a.get("value")), str(b.get("value"))) for i, a in enumerate(fs) for b in fs[i + 1:])

    def conflicts(self) -> list[list[dict]]:
        """Groups of facts of one entity and one single-valued attribute whose values are not all the same."""
        groups: dict[tuple, list[dict]] = {}
        for f in self.facts:
            if f.get("type") in SINGLE_VALUED:
                groups.setdefault(self._key(f), []).append(f)
        return [fs for fs in groups.values() if not self._agree(fs)]

    def settle(self) -> int:
        """One value per attribute of an entity: the strongest source's stays; when the strongest sources disagree,
        the whole group goes. The facts dropped before take part, so a value added after a dispute does not stand
        alone. Dropped facts leave the base and are kept in `dropped` with the reason."""
        n = 0
        dropped: dict[tuple, list[dict]] = {}
        for f in self.data["dropped"]:
            dropped.setdefault(self._key(f), []).append(f)
        groups: dict[tuple, list[dict]] = {}
        for f in self.facts:
            if f.get("type") in SINGLE_VALUED:
                groups.setdefault(self._key(f), []).append(f)
        for key, same in groups.items():
            every = same + dropped.get(key, [])
            if self._agree(every):
                continue
            tiers: dict[int, list[dict]] = {}
            for f in every:
                tiers.setdefault(STRENGTH.get(f.get("source_kind"), 9), []).append(f)
            order = sorted(tiers)
            top = tiers[order[0]]
            # the strongest tier wins when it agrees; each weaker tier keeps the facts that agree with every fact
            # kept so far, and only while they also agree among themselves («35» kept, then «35 EUR» and «35 PLN»
            # of one weaker tier disagree, so both go)
            kept = list(top) if self._agree(top) else []
            if kept:
                for strength in order[1:]:
                    cand = [f for f in tiers[strength]
                            if all(same_value(str(k.get("value")), str(f.get("value"))) for k in kept)]
                    if cand and self._agree(kept + cand):
                        kept += cand
            for f in same:
                if any(f is k for k in kept):
                    continue
                self.facts.remove(f)
                self.data["dropped"].append({**f, "reason": "conflict: weaker source" if kept
                                             else "disputed: equal sources disagree"})
                n += 1
        return n

    # ---------------------------------------------------------------- output

    def compact(self) -> str:
        lines = []
        for name, fs in self.by_entity().items():
            lines.append(f"{name} ({fs[0].get('entity_kind')})")
            lines += [f"  {f.get('id')} {_what(f)}: {f.get('value')} [{f.get('source_kind')}]" for f in fs]
        return "\n".join(lines) or "(empty)"

    def dossier(self) -> str:
        """FACTS.md: every fact with its number, by entity kind and entity, strongest source first; then what was left
        out and why; then the saved pages; then what was not found."""
        out = ["# Facts", "",
               "Built by code from the research's fact base `research/facts.json` (each fact with its verbatim quote; "
               "the saved pages are in `research/sources/`).", ""]
        groups = self.by_entity()
        for kind in ENTITY_KINDS:
            rows = [(n, fs) for n, fs in groups.items() if fs[0].get("entity_kind") == kind]
            if not rows:
                continue
            out += [f"## {kind.capitalize()}", ""]
            for name, fs in rows:
                out.append(f"### {name}")
                for f in sorted(fs, key=lambda x: (STRENGTH.get(x.get("source_kind"), 9), _num_id(x))):
                    quote = f" «{f.get('quote')}»" if f.get("type") == "claim" else ""
                    out.append(f"- {f.get('id')} {f.get('attribute') or f.get('type')}: {f.get('value')}{quote} — "
                               f"{f.get('source_kind')}: {f.get('source_url')}")
                out.append("")
        if self.data["dropped"]:
            out += ["## Left out", ""]
            for f in self.data["dropped"]:
                out.append(f"- {f.get('id')} {f.get('entity')} · {f.get('attribute') or f.get('type')}: "
                           f"{f.get('value')} — {f.get('source_kind')}: {f.get('source_url')} — {f.get('reason')}")
            out.append("")
        if self.data["sources"]:
            out += ["## Sources", ""]
            for url, src in self.data["sources"].items():
                via = (" — read through WebFetch: the text a model returned, not the page itself"
                       if src.get("via") == VIA_WEBFETCH else "")
                out.append(f"- {url} — `{src['file']}`, saved {src.get('saved', '')}{via}")
            out.append("")
        if self.data["gaps"]:
            out += ["## Not found", "", *[f"- {g}" for g in self.data["gaps"]], ""]
        return "\n".join(out).rstrip() + "\n"


def _what(f: dict) -> str:
    return f"{f.get('type')} {f['attribute']}" if f.get("attribute") else str(f.get("type"))


def _num_id(f: dict) -> int:
    m = re.fullmatch(r"F(\d+)", str(f.get("id")))
    return int(m.group(1)) if m else 10 ** 9
