"""Tests of the research stage's code: the fact base and its CLI (skills/research/research.py), the gates
fact-quoted and sources-conflict, and the gate hook's branch for the fact base.

A document folder has BRIEF.md. The research keeps its fact base in `research/facts.json`, the saved pages in
`research/sources/`, and writes the dossier `FACTS.md`. Pages are served by a local http.server on 127.0.0.1 in a
thread: no test reaches the internet.

The tests read the fact base only through the CLI (`list`, `entities`) and FACTS.md. Where a test edits facts.json by
hand, it replaces a value it put there through `add`, inside the fact records (objects with a `quote` key), so it
does not depend on the rest of the file's layout.

  python3 -m unittest tests.test_research -v
"""
from __future__ import annotations

try:  # first: the plugin's cache goes to a temp folder (tests/isolate.py)
    from tests import isolate  # noqa: F401
except ImportError:
    import isolate  # noqa: F401

import collections
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "skills" / "research" / "research.py"
HOOK = ROOT / "hooks" / "gate_run.py"
RECORDED = ROOT / "tests" / "fixtures" / "hook_posttooluse_write.json"
LIBRARY = ROOT / "gates" / "library.md"
ENV = dict(os.environ, no_proxy="127.0.0.1,localhost", NO_PROXY="127.0.0.1,localhost")
BUDGET = 10

# Every page text is longer than 200 characters, so no test depends on what `save` does with a short text.
FILLER = (" The rest of the page tells how to set the pump up, clean its filter and store it dry for the winter, "
          "so that it starts again without trouble when spring comes back.")


# ---------------------------------------------------------------- pages

PUMP_URL = "https://pumps.example/garden-pump"
PUMP_TEXT = (
    "The Garden Pump GP is built for small gardens and rain barrels. "
    "It reaches a maximum pressure of 6 bar and moves 1,500 litres per hour. "
    "It lifts water from a max depth of 8 m. "
    "The pump went on sale on 14 June 2025 and has been sold since June 2025. "
    "The manual is dated 2025-06-14. "
    "A service visit took place on 5 March 2024; the crew came back on the 5th of the next month. "
    "Spare parts arrived in Mar 2024. "
    "It costs 129 euros in the shop at 12 Mill Street. The full set costs 1,250 EUR. A spare hose costs 35 EUR. "
    "The service point is at Main St 5. "
    "The maker was founded in 2019 and made pumps from 2019 to 2024 in one plant. "
    "Its housing is made of “weatherproof” plastic — light and easy to carry. "
    "The pump weighs 7 kg. The pump does not reach 16 bar under any load." + FILLER
)
REVIEW_URL = "https://reviews.example/garden-pump-test"
REVIEW_TEXT = (
    "We tested the Garden Pump at home for a month. In our test it reached a maximum pressure of 8 bar, "
    "and it moved 1500 litres per hour. It lifted water from a maximum well depth of 8 ft. "
    "The shop at 12 Mill Street, Riverton sold it to us; another shop at 14 Mill Street had it too. "
    "We paid 1250 EUR for the full set. Abroad a spare hose costs 35 USD. "
    "We found the service point at Main Street 5. It weighed 8 kg on our scale." + FILLER
)
CATALOGUE_URL = "https://catalogue.example/pumps"
CATALOGUE_TEXT = "Catalogue entry: the Garden Pump weighs 9 kg and is sold in garden shops across the region." + FILLER
NEWS_URL = "https://news.example/pump-story"
NEWS_TEXT = "A local paper wrote that the Garden Pump weighs 10 kg, heavier than most pumps of its size." + FILLER
SPEC_URL = "https://pumps.example/spec-sheet"
SPEC_TEXT = "Spec sheet: the Garden Pump weighs 9 kg without the hose." + FILLER
BAKERY_URL = "https://bakery.example/about"
BAKERY_TEXT = (
    "The Riverside Bakery bakes bread every morning. The Riverside Bakery! is how the sign over the door reads. "
    "North Mill Bakery stands at 30 Oak Lane. Corner Bread Shop also stands at 30 Oak Lane. "
    "Apple is a sweet variety. Apple Orchard is the farm the apples come from. "
    "Plum Cake Corner sells cakes. The apples are sweet and crisp." + FILLER
)


def pump_fact(**kw) -> dict:
    """A valid fact on PUMP_TEXT, fields overridden by `kw` (a value of None removes the field)."""
    f = {"entity": "Garden Pump", "entity_kind": "product", "type": "number", "attribute": "maximum pressure",
         "value": "6 bar", "quote": "It reaches a maximum pressure of 6 bar", "source_kind": "official"}
    f.update(kw)
    return {k: v for k, v in f.items() if v is not None}


def claim(entity: str, quote: str, entity_kind="organization", value="exists", **kw) -> dict:
    f = {"entity": entity, "entity_kind": entity_kind, "type": "claim", "value": value, "quote": quote,
         "source_kind": "official"}
    f.update(kw)
    return f


# ---------------------------------------------------------------- helpers

def cli(*args, stdin: str = "") -> list[str]:
    """research.py <args>, its non-empty output lines. It exits 0 also on rejections."""
    r = subprocess.run([sys.executable, str(RESEARCH), *[str(a) for a in args]], input=stdin, capture_output=True,
                       text=True, timeout=120, env=ENV)
    assert r.returncode == 0, f"research.py {' '.join(map(str, args))} exited {r.returncode}\n{r.stdout}\n{r.stderr}"
    return [line for line in r.stdout.splitlines() if line.strip()]


def _gate_paths():
    for p in (ROOT / "gates" / "scripts", ROOT / "gates" / "lib"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def fact_quoted_gate():
    _gate_paths()
    import fact_quoted
    return fact_quoted.gate_fact_quoted


def sources_conflict_gate():
    _gate_paths()
    import sources_conflict
    return sources_conflict.gate_sources_conflict


def norm(s: str) -> str:
    return " ".join(s.lower().split())


def replace_in_json(obj, old: str, new: str, in_fact: bool = False):
    """(obj with every string equal to `old` — or equal up to case and whitespace — replaced by `new`, count).
    Only strings inside a fact record (a JSON object with a `quote` key) are replaced: a page index kept in the
    same file stays as it is, so the edit stays an edit of one fact."""
    if isinstance(obj, str):
        return (new, 1) if in_fact and (obj == old or norm(obj) == norm(old)) else (obj, 0)
    if isinstance(obj, list):
        out, n = [], 0
        for x in obj:
            y, k = replace_in_json(x, old, new, in_fact)
            out.append(y)
            n += k
        return out, n
    if isinstance(obj, dict):
        inside = in_fact or "quote" in obj
        out, n = {}, 0
        for key, x in obj.items():
            y, k = replace_in_json(x, old, new, inside)
            out[key] = y
            n += k
        return out, n
    return obj, 0


def ids(lines: list[str]) -> list[str]:
    return [m.group(1) for line in lines for m in [re.match(r"ok (F\d+)\b", line)] if m]


def lines_with(text: str, *needles: str) -> list[str]:
    return [line for line in text.splitlines() if all(n.lower() in line.lower() for n in needles)]


def id_lines(text: str, fid: str) -> list[str]:
    return [line for line in text.splitlines() if re.search(rf"\b{fid}\b", line)]


def section(text: str, heading: str) -> list[str]:
    """The lines under `heading` (a whole line) up to the next heading."""
    lines = text.splitlines()
    if heading not in lines:
        return []
    after = lines[lines.index(heading) + 1:]
    return after[:next((i for i, line in enumerate(after) if line.startswith("#")), len(after))]


def today_dates() -> set[str]:
    return {datetime.date.today().isoformat(), datetime.datetime.now(datetime.timezone.utc).date().isoformat()}


class Site:
    """A local web server in a thread: path -> (status, html). Counts the requests per path."""

    def __init__(self, pages: dict[str, tuple[int, str]]):
        self.pages = pages
        self.hits: collections.Counter = collections.Counter()
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                site.hits[self.path] += 1
                status, body = site.pages.get(self.path, (404, "<html><body>not found</body></html>"))
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}{path}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


LONG_PARAGRAPH = ("The garden pump draws water from a rain barrel and sends it to the beds through a hose. "
                  "It starts when a tap opens and stops when the tap closes again, so the garden gets water "
                  "only when it is needed. A float switch keeps it from running dry.")


def page_html(body: str, junk: bool = True) -> str:
    head = ("<script>var trackerScriptWord = 1;</script>"
            "<style>.bannerStyleWord { color: red; }</style>") if junk else ""
    top = ("<header>HeaderKeptWord</header><nav>NavChromeWord Home Shop</nav>"
           "<aside>AsideKeptWord</aside>") if junk else ""
    foot = "<footer>FooterChromeWord all rights kept</footer>" if junk else ""
    return (f"<!doctype html><html><head><title>Garden pump</title>{head}</head><body>{top}"
            f"<main>{body}</main>{foot}</body></html>")


class DocCase(unittest.TestCase):
    """A fresh document folder with BRIEF.md in a temp dir."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.folder = Path(self.tmp) / "doc"
        self.folder.mkdir()
        (self.folder / "BRIEF.md").write_text("# Brief\n\nA leaflet about a garden pump.\n", encoding="utf-8")

    def save(self, url: str, text: str) -> None:
        out = cli("save", self.folder, url, stdin=text)
        self.assertTrue(out and out[0].startswith(f"saved {url}"), out)

    def add(self, url: str, facts) -> list[str]:
        return cli("add", self.folder, "--url", url, stdin=json.dumps(facts))

    def add_ok(self, url: str, fact: dict) -> str:
        out = self.add(url, fact)
        self.assertEqual(len(out), 1, out)
        self.assertRegex(out[0], r"^ok F\d+$", fact)
        return out[0].split()[1]

    def source_files(self) -> list[Path]:
        d = self.folder / "research" / "sources"
        return sorted(p for p in d.rglob("*") if p.is_file()) if d.exists() else []

    def sources_text(self) -> str:
        return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in self.source_files())

    def file_with(self, needle: str) -> Path:
        found = [p for p in self.source_files() if needle in p.read_text(encoding="utf-8", errors="replace")]
        self.assertTrue(found, f"no saved page holds «{needle}»")
        return found[0]

    def facts_json(self):
        return json.loads((self.folder / "research" / "facts.json").read_text(encoding="utf-8"))

    def edit_facts_json(self, old: str, new: str) -> None:
        data, n = replace_in_json(self.facts_json(), old, new)
        self.assertGreater(n, 0, f"«{old}» is in no fact of facts.json")
        (self.folder / "research" / "facts.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def dossier(self) -> str:
        return (self.folder / "FACTS.md").read_text(encoding="utf-8")

    def listing(self) -> str:
        return "\n".join(cli("list", self.folder))

    def listed_ids(self) -> list[str]:
        return re.findall(r"\b(F\d+) ", self.listing())

    def entity_lines(self) -> dict[str, str]:
        """{entity name: its line of `entities`}; the name is what comes before ` — attributes:`."""
        return {line.split(" — attributes:")[0].strip(): line for line in cli("entities", self.folder)}


# ---------------------------------------------------------------- condition 1: a quote not on the page never enters

class AddChecksTheQuote(DocCase):
    def setUp(self):
        super().setUp()
        self.save(PUMP_URL, PUMP_TEXT)

    def test_a_fact_quoted_from_the_page_is_accepted(self):
        self.assertEqual(self.add(PUMP_URL, pump_fact()), ["ok F1"])
        self.assertIn("F1 number maximum pressure: 6 bar [official]", self.listing())

    def test_a_quote_not_on_the_page_is_rejected(self):
        out = self.add(PUMP_URL, pump_fact(quote="It reaches a top pressure of 6 bar"))
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("rejected: "), out)
        self.assertNotIn("Garden Pump", "\n".join(cli("entities", self.folder)))
        self.assertEqual(self.listed_ids(), [])

    def test_the_quote_is_compared_ignoring_case_spaces_quote_marks_and_dashes(self):
        f = claim("Garden Pump", 'its HOUSING is made of  "weatherproof"\nplastic - light', entity_kind="product",
                  attribute="housing", value="weatherproof plastic, light")
        self.assertEqual(self.add(PUMP_URL, f), ["ok F1"])

    def test_the_url_must_be_a_saved_page(self):
        out = self.add("https://pumps.example/never-saved", pump_fact())
        self.assertTrue(out[0].startswith("rejected: "), out)

    def test_a_number_of_the_value_must_be_in_the_quote(self):
        out = self.add(PUMP_URL, pump_fact(value="7 bar"))
        self.assertTrue(out[0].startswith("rejected: "), out)
        out = self.add(PUMP_URL, claim("Garden Pump", "built for small gardens and rain barrels",
                                       entity_kind="product", value="for 2 or 3 rain barrels"))
        self.assertTrue(out[0].startswith("rejected: "), out)  # a claim is checked too

    def test_a_number_inside_a_longer_number_does_not_count(self):
        # «6» is not in «16 bar»: numbers are compared whole
        out = self.add(PUMP_URL, pump_fact(value="6 bar", quote="The pump does not reach 16 bar under any load"))
        self.assertTrue(out[0].startswith("rejected: "), out)

    def test_thousands_separators_count_as_one_number(self):
        self.assertEqual(self.add(PUMP_URL, pump_fact(attribute="flow per hour", value="1500 litres",
                                                      quote="moves 1,500 litres per hour")), ["ok F1"])
        self.assertEqual(self.add(PUMP_URL, pump_fact(attribute="flow", value="1,500 l",
                                                      quote="moves 1,500 litres per hour")), ["ok F2"])
        self.save(REVIEW_URL, REVIEW_TEXT)
        self.assertEqual(self.add(REVIEW_URL, pump_fact(attribute="flow per hour", value="1,500 litres",
                                                        quote="it moved 1500 litres per hour",
                                                        source_kind="review")), ["ok F3"])

    def test_required_fields_and_their_enums(self):
        bad = {
            "no entity": pump_fact(entity=None),
            "no quote": pump_fact(quote=None),
            "no value": pump_fact(value=None),
            "no source_kind": pump_fact(source_kind=None),
            "entity_kind out of enum": pump_fact(entity_kind="animal"),
            "type out of enum": pump_fact(type="percentage"),
            "description is no type any more": pump_fact(type="description", attribute="housing",
                                                         value="weatherproof plastic",
                                                         quote="Its housing is made of"),
            "source_kind out of enum": pump_fact(source_kind="blog"),
            "a number with no attribute": pump_fact(attribute=None),
            "a price with no attribute": pump_fact(type="price", attribute=None, value="129 euros",
                                                   quote="It costs 129 euros"),
            "an address with no attribute": pump_fact(type="address", attribute=None, value="12 Mill Street",
                                                      quote="in the shop at 12 Mill Street"),
        }
        for why, f in bad.items():
            with self.subTest(why):
                out = self.add(PUMP_URL, f)
                self.assertEqual(len(out), 1, out)
                self.assertTrue(out[0].startswith("rejected: "), out)
        self.assertEqual(self.listed_ids(), [])
        # a claim needs no attribute
        self.assertEqual(self.add(PUMP_URL, claim("Garden Pump", "is built for small gardens", entity_kind="product",
                                                  value="built for small gardens")), ["ok F1"])

    def test_dates(self):
        cases = [
            # every part given must be in the quote: the year and the day as numbers, the month as a number or name
            ("2025-06-14", "The pump went on sale on 14 June 2025", True),
            ("2025-06-14", "The manual is dated 2025-06-14", True),
            ("2024-03-05", "A service visit took place on 5 March 2024", True),
            ("2024-03", "Spare parts arrived in Mar 2024", True),
            ("2025-06", "has been sold since June 2025", True),
            ("2019", "The maker was founded in 2019", True),
            ("2019/2024", "made pumps from 2019 to 2024", True),
            ("2025-06-14", "has been sold since June 2025", False),             # the day is not in the quote
            ("2024-03-05", "the crew came back on the 5th", False),             # no year, no month
            ("2024-03-05", "A service visit took place on 5 March", False),     # no year: no guessing
            ("2024-03", "made pumps from 2019 to 2024", False),                 # no month
            ("2024-06", "Spare parts arrived in Mar 2024", False),              # the wrong month
            ("2018", "The maker was founded in 2019", False),                   # the year is not in the quote
            ("2024/2019", "made pumps from 2019 to 2024", False),               # a span must not run backwards
            ("14 June 2025", "The pump went on sale on 14 June 2025", False),   # not YYYY, YYYY-MM or YYYY-MM-DD
            ("2025-6-14", "The pump went on sale on 14 June 2025", False),
        ]
        for n, (value, quote, ok) in enumerate(cases):
            with self.subTest(value=value, quote=quote):
                out = self.add(PUMP_URL, pump_fact(type="date", attribute=f"date {n}", value=value, quote=quote))
                self.assertEqual(len(out), 1, out)
                if ok:
                    self.assertRegex(out[0], r"^ok F\d+$")
                else:
                    self.assertTrue(out[0].startswith("rejected: "), out)

    def test_the_same_fact_twice_is_rejected(self):
        self.assertEqual(self.add(PUMP_URL, pump_fact()), ["ok F1"])
        out = self.add(PUMP_URL, pump_fact(quote="a maximum pressure of 6 bar"))
        self.assertTrue(out[0].startswith("rejected: "), out)
        self.assertEqual(self.listed_ids(), ["F1"])

    def test_an_array_gives_one_line_per_fact_in_order(self):
        out = self.add(PUMP_URL, [pump_fact(), pump_fact(attribute="weight", value="5 kg", quote="weighs 7 kg"),
                                  pump_fact(type="price", attribute="price", value="129 euros",
                                            quote="It costs 129 euros")])
        self.assertEqual(len(out), 3, out)
        self.assertEqual(out[0], "ok F1")
        self.assertTrue(out[1].startswith("rejected: "), out)
        self.assertEqual(out[2], "ok F2")


class FactQuotedGate(DocCase):
    """A fact written into facts.json by hand, past `add`, is caught by the gate fact-quoted."""

    def setUp(self):
        super().setUp()
        self.save(PUMP_URL, PUMP_TEXT)
        self.add_ok(PUMP_URL, pump_fact())
        self.add_ok(PUMP_URL, pump_fact(type="price", attribute="price", value="129 euros",
                                        quote="It costs 129 euros"))

    def test_a_base_built_through_add_passes(self):
        self.assertEqual(fact_quoted_gate()(self.folder), [])

    def test_a_quote_edited_by_hand_fails(self):
        self.edit_facts_json("It reaches a maximum pressure of 6 bar", "It reaches a top pressure of 6 bar")
        fs = fact_quoted_gate()(self.folder)
        self.assertTrue(fs)
        self.assertEqual({f.gate for f in fs}, {"fact-quoted"})
        self.assertTrue(all(f.line().startswith("[fact-quoted]") for f in fs))

    def test_a_url_edited_by_hand_to_an_unsaved_page_fails(self):
        self.edit_facts_json(PUMP_URL, "https://pumps.example/never-saved")
        self.assertIn("fact-quoted", [f.gate for f in fact_quoted_gate()(self.folder)])

    def test_a_value_edited_by_hand_to_a_number_not_in_the_quote_fails(self):
        self.edit_facts_json("129 euros", "99 euros")
        fs = fact_quoted_gate()(self.folder)
        self.assertEqual(len(fs), 1, [f.line() for f in fs])
        self.assertEqual(fs[0].gate, "fact-quoted")

    def test_a_saved_page_changed_by_hand_fails(self):
        p = self.file_with("maximum pressure")
        p.write_text(p.read_text(encoding="utf-8").replace("maximum pressure", "top pressure"), encoding="utf-8")
        self.assertIn("fact-quoted", [f.gate for f in fact_quoted_gate()(self.folder)])

    def test_a_folder_with_no_fact_base_passes(self):
        empty = Path(self.tmp) / "other"
        empty.mkdir()
        (empty / "BRIEF.md").write_text("# Brief\n", encoding="utf-8")
        self.assertEqual(fact_quoted_gate()(empty), [])


# ---------------------------------------------------------------- condition 3: plain text by code, at most 10 pages

class Fetch(DocCase):
    def setUp(self):
        super().setUp()
        pages = {
            "/pump": (200, page_html(f"<h1>The pump</h1><p>{LONG_PARAGRAPH}</p>"
                                     "<p>It reaches <b>6&nbsp;bar</b> at most, says the &ldquo;maker&rdquo;.</p>")),
            "/short": (200, page_html("<p>Short page.</p>" + "<script>" + "var x = 1; " * 100 + "</script>")),
            "/gone": (404, "<html><body>not found</body></html>"),
            "/big": (200, page_html("<p>" + "water " * 41000 + "bigpageclosingword</p>", junk=False)),
            "/huge": (200, page_html("<p>" + "water " * 60000 + "hugepageclosingword</p>", junk=False)),
        }
        for i in range(15):
            pages[f"/p{i}"] = (200, page_html(f"<p>Page number {i}. {LONG_PARAGRAPH}</p>", junk=False))
        self.site = Site(pages)
        self.addCleanup(self.site.close)

    def fetch(self, *paths: str) -> list[str]:
        return cli("fetch", self.folder, *[self.site.url(p) for p in paths])

    def test_a_page_is_saved_as_plain_text(self):
        url = self.site.url("/pump")
        out = self.fetch("/pump")
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith(f"saved {url}"), out)
        self.assertNotIn("cut", out[0])
        text = self.sources_text()
        self.assertIn(LONG_PARAGRAPH[:80], text)
        self.assertIn("at most", text)
        for kept in ("HeaderKeptWord", "AsideKeptWord"):
            self.assertIn(kept, text, kept)
        for junk in ("trackerScriptWord", "bannerStyleWord", "NavChromeWord", "FooterChromeWord",
                     "<p>", "<b>", "&nbsp;", "&ldquo;"):
            self.assertNotIn(junk, text, junk)

    def test_a_long_page_is_cut_only_past_300000_characters(self):
        out = self.fetch("/big")  # about 246000 characters of text
        self.assertTrue(out[0].startswith(f"saved {self.site.url('/big')}"), out)
        self.assertNotIn("cut", out[0])
        self.assertIn("bigpageclosingword", self.sources_text())
        out = self.fetch("/huge")  # about 360000 characters of text
        self.assertTrue(out[0].startswith(f"saved {self.site.url('/huge')}"), out)
        self.assertIn("cut", out[0])
        self.assertNotIn("hugepageclosingword", self.sources_text())

    def test_a_fact_can_be_quoted_from_a_fetched_page_across_tags(self):
        url = self.site.url("/pump")
        self.fetch("/pump")
        self.assertEqual(self.add(url, pump_fact(quote='It reaches 6 bar at most, says the "maker"')), ["ok F1"])
        self.assertEqual(fact_quoted_gate()(self.folder), [])

    def test_a_page_that_cannot_be_read_or_is_empty(self):
        out = self.fetch("/gone", "/short")
        self.assertEqual(len(out), 2, out)
        self.assertTrue(out[0].startswith(f"could not fetch {self.site.url('/gone')}"), out)
        self.assertTrue(out[1].startswith(f"empty {self.site.url('/short')}"), out)
        out = cli("fetch", self.folder, "http://127.0.0.1:1/nothing-listens-here")
        self.assertTrue(out[0].startswith("could not fetch http://127.0.0.1:1/nothing-listens-here"), out)

    def test_at_most_ten_pages_saved_in_one_call(self):
        out = self.fetch(*[f"/p{i}" for i in range(12)])
        self.assertEqual(len(out), 12, out)
        for i in range(BUDGET):
            self.assertTrue(out[i].startswith(f"saved {self.site.url(f'/p{i}')}"), out[i])
        for i in (10, 11):
            self.assertIn("page budget used up", out[i])
            self.assertEqual(self.site.hits[f"/p{i}"], 0, f"/p{i} was downloaded past the budget")

    def test_pages_that_were_not_saved_use_no_slot(self):
        self.fetch("/gone", "/short", "/p0", "/p1")
        out = self.fetch(*[f"/p{i}" for i in range(2, 11)])  # 2 saved before + 8 more = 10; /p10 is past it
        self.assertEqual(sum(1 for line in out if line.startswith("saved ")), 8, out)
        self.assertIn("page budget used up", out[-1])
        self.assertEqual(self.site.hits["/p10"], 0)

    def test_the_budget_counts_across_calls(self):
        self.fetch(*[f"/p{i}" for i in range(6)])
        out = self.fetch(*[f"/p{i}" for i in range(6, 12)])
        self.assertEqual([line.startswith("saved ") for line in out], [True] * 4 + [False] * 2, out)
        self.assertEqual(self.site.hits["/p10"] + self.site.hits["/p11"], 0)

    def test_a_url_already_tried_is_not_fetched_again(self):
        for path in ("/p0", "/gone"):
            with self.subTest(path):
                self.fetch(path)
                out = self.fetch(path)
                self.assertEqual(self.site.hits[path], 1)
                self.assertTrue(out[0].startswith(f"not fetched {self.site.url(path)}:"), out)
        out = self.fetch(*[f"/p{i}" for i in range(1, 10)])  # /p0 + 9 = 10 saved pages: all within the budget
        self.assertTrue(all(line.startswith("saved ") for line in out), out)

    def test_save_keeps_a_page_fetch_could_not_read(self):
        gone = self.site.url("/gone")
        self.fetch("/gone")
        out = cli("save", self.folder, gone, stdin=f"The page as a reader copied it. {LONG_PARAGRAPH}")
        self.assertTrue(out[0].startswith(f"saved {gone}"), out)
        self.assertEqual(self.add(gone, claim("Garden Pump", "The page as a reader copied it",
                                              entity_kind="product")), ["ok F1"])
        self.assertEqual(fact_quoted_gate()(self.folder), [])

    def test_save_refuses_a_page_already_saved(self):
        url = self.site.url("/pump")
        self.fetch("/pump")
        out = cli("save", self.folder, url, stdin=f"Another copy of the page. {LONG_PARAGRAPH}")
        self.assertTrue(out[0].startswith("not saved"), out)
        self.assertNotIn("Another copy of the page.", self.sources_text())
        self.save("https://garden.example/copied", f"A copied page. {LONG_PARAGRAPH}")
        out = cli("save", self.folder, "https://garden.example/copied", stdin=f"Copied twice. {LONG_PARAGRAPH}")
        self.assertTrue(out[0].startswith("not saved"), out)

    def test_save_counts_toward_the_budget(self):
        self.fetch(*[f"/p{i}" for i in range(5)])
        for i in range(5):
            self.save(f"https://garden.example/page{i}", f"Saved page {i}. {LONG_PARAGRAPH}")
        out = cli("save", self.folder, "https://garden.example/page10", stdin=f"Saved page ten. {LONG_PARAGRAPH}")
        self.assertTrue(out[0].startswith("not saved"), out)
        self.assertNotIn("Saved page ten.", self.sources_text())
        out = self.fetch("/p5")
        self.assertIn("page budget used up", out[0])
        self.assertEqual(self.site.hits["/p5"], 0)


# ---------------------------------------------------------------- the base: ids, entities, list, duplicates, merges

class Base(DocCase):
    def setUp(self):
        super().setUp()
        self.save(PUMP_URL, PUMP_TEXT)
        self.save(BAKERY_URL, BAKERY_TEXT)

    def test_entities_with_their_attributes(self):
        self.add_ok(PUMP_URL, pump_fact())
        self.add_ok(PUMP_URL, pump_fact(type="price", attribute="price", value="129 euros",
                                        quote="It costs 129 euros"))
        self.add_ok(BAKERY_URL, claim("Riverside Bakery", "The Riverside Bakery bakes bread every morning",
                                      value="bakes bread every morning"))
        lines = self.entity_lines()
        self.assertEqual(sorted(lines), ["Garden Pump", "Riverside Bakery"])
        self.assertTrue(lines["Garden Pump"].startswith("Garden Pump — attributes: "), lines)
        attrs = lines["Garden Pump"].split("attributes: ", 1)[1].split("; ")
        self.assertEqual(sorted(a.strip() for a in attrs), ["maximum pressure", "price"])
        self.assertEqual(lines["Riverside Bakery"], "Riverside Bakery")

    def test_list_grouped_by_entity(self):
        self.add_ok(PUMP_URL, pump_fact())
        self.add_ok(BAKERY_URL, claim("Riverside Bakery", "The Riverside Bakery bakes bread every morning",
                                      value="bakes bread every morning"))
        self.add_ok(PUMP_URL, pump_fact(type="price", attribute="price", value="129 euros",
                                        quote="It costs 129 euros"))
        listing = cli("list", self.folder)
        text = "\n".join(listing)
        self.assertIn("F1 number maximum pressure: 6 bar [official]", text)
        self.assertIn("F3 price price: 129 euros [official]", text)
        pos = {fid: next(i for i, line in enumerate(listing) if re.search(rf"\b{fid}\b", line))
               for fid in ("F1", "F2", "F3")}
        pump_head = next(i for i, line in enumerate(listing) if "Garden Pump" in line and not re.search(r"\bF\d", line))
        self.assertLess(pump_head, min(pos["F1"], pos["F3"]))
        # grouped: the bakery's fact does not sit between the pump's two
        self.assertFalse(min(pos["F1"], pos["F3"]) < pos["F2"] < max(pos["F1"], pos["F3"]), listing)

    def test_ids_are_never_reused(self):
        self.save(REVIEW_URL, REVIEW_TEXT)
        self.assertEqual(self.add_ok(PUMP_URL, pump_fact()), "F1")
        self.add_ok(REVIEW_URL, pump_fact(value="8 bar", quote="it reached a maximum pressure of 8 bar",
                                          source_kind="review"))  # F2, dropped by finish
        cli("finish", self.folder)
        self.assertEqual(self.listed_ids(), ["F1"])
        self.assertEqual(self.add_ok(PUMP_URL, pump_fact(type="price", attribute="price", value="129 euros",
                                                         quote="It costs 129 euros")), "F3")

    def test_parallel_adds_lose_no_fact_and_share_no_id(self):
        procs = []
        for letter in "ABCDEFGH":
            f = claim(f"Apple {letter}", "The apples are sweet and crisp", entity_kind="product", value="sweet")
            procs.append(subprocess.Popen([sys.executable, str(RESEARCH), "add", str(self.folder), "--url",
                                           BAKERY_URL], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, text=True, env=ENV))
            procs[-1].stdin.write(json.dumps(f))
            procs[-1].stdin.close()
        got = []
        for p in procs:
            p.wait(timeout=120)
            self.assertEqual(p.returncode, 0, p.stderr.read())
            got += ids(p.stdout.read().splitlines())
        self.assertEqual(sorted(got, key=lambda s: int(s[1:])), [f"F{i}" for i in range(1, 9)])
        self.assertEqual(len([n for n in self.entity_lines() if n.startswith("Apple ")]), 8)
        self.assertEqual(sorted(self.listed_ids()), sorted(got))

    def test_duplicate_entities(self):
        facts = [
            claim("Riverside Bakery", "The Riverside Bakery bakes bread every morning", value="bakes bread"),
            claim("The Riverside Bakery!", "The Riverside Bakery! is how the sign over the door reads",
                  value="the sign over the door"),
            {**claim("North Mill Bakery", "North Mill Bakery stands at 30 Oak Lane", value="30 Oak Lane"),
             "type": "address", "attribute": "address"},
            {**claim("Corner Bread Shop", "Corner Bread Shop also stands at 30 Oak Lane", value="30 Oak Lane"),
             "type": "address", "attribute": "address"},
            claim("Apple", "Apple is a sweet variety", entity_kind="product", value="a sweet variety"),
            claim("Apple Orchard", "Apple Orchard is the farm the apples come from", entity_kind="place",
                  value="the farm the apples come from"),
            claim("Plum Cake Corner", "Plum Cake Corner sells cakes", value="sells cakes"),
        ]
        self.assertEqual(len(ids(self.add(BAKERY_URL, facts))), 7)
        out = cli("duplicates", self.folder)
        # one name in the other (case and punctuation aside): the line names both
        self.assertEqual(len([line for line in out if "The Riverside Bakery!" in line
                              and "Riverside Bakery" in line.replace("The Riverside Bakery!", "", 1)]), 1, out)
        self.assertEqual(lines_with("\n".join(out), "North Mill Bakery", "Corner Bread Shop"), [], out)  # one address
        self.assertEqual([line for line in out if "Apple Orchard" in line], [], out)  # a product and a place
        self.assertEqual([line for line in out if "Plum Cake Corner" in line], [], out)
        self.assertEqual(len(out), 1, out)

    def test_duplicate_attributes(self):
        self.save(REVIEW_URL, REVIEW_TEXT)
        self.add_ok(PUMP_URL, pump_fact(attribute="max depth", value="8 m", quote="from a max depth of 8 m"))
        self.add_ok(REVIEW_URL, pump_fact(attribute="maximum well depth", value="8 ft", source_kind="review",
                                          quote="from a maximum well depth of 8 ft"))
        self.add_ok(PUMP_URL, pump_fact())  # maximum pressure: not a pair of «max depth»
        out = cli("duplicates", self.folder)
        self.assertEqual(len(lines_with("\n".join(out), "max depth", "maximum well depth")), 1, out)
        self.assertEqual([line for line in out if "maximum pressure" in line], [], out)

    def test_merge_entities(self):
        a = self.add_ok(BAKERY_URL, claim("Riverside Bakery", "The Riverside Bakery bakes bread every morning",
                                          value="bakes bread"))
        b = self.add_ok(BAKERY_URL, claim("The Riverside Bakery!", "The Riverside Bakery! is how the sign over "
                                          "the door reads", value="the sign over the door"))
        cli("merge", self.folder, "Riverside Bakery", "The Riverside Bakery!")
        self.assertEqual(list(self.entity_lines()), ["Riverside Bakery"])
        self.assertEqual(sorted(self.listed_ids()), sorted([a, b]))

    def test_merge_refuses_an_unknown_name(self):
        self.add_ok(BAKERY_URL, claim("Riverside Bakery", "The Riverside Bakery bakes bread every morning",
                                      value="bakes bread"))
        self.add_ok(BAKERY_URL, claim("Plum Cake Corner", "Plum Cake Corner sells cakes", value="sells cakes"))
        before = sorted(self.entity_lines())
        out = cli("merge", self.folder, "Riverside Bakery", "Nobody Bakes Here")
        self.assertTrue(out and not out[0].startswith("ok"), out)
        self.assertEqual(sorted(self.entity_lines()), before)
        cli("merge", self.folder, "Nobody Bakes Here", "Plum Cake Corner")
        self.assertEqual(sorted(self.entity_lines()), before)

    def test_merge_attribute(self):
        self.save(REVIEW_URL, REVIEW_TEXT)
        a = self.add_ok(PUMP_URL, pump_fact(attribute="max depth", value="8 m", quote="from a max depth of 8 m"))
        b = self.add_ok(REVIEW_URL, pump_fact(attribute="maximum well depth", value="8 ft", source_kind="review",
                                              quote="from a maximum well depth of 8 ft"))
        out = cli("merge-attribute", self.folder, "Garden Pump", "maximum well depth", "max depth")
        self.assertTrue(out and out[0].startswith("ok"), out)
        listing = self.listing()
        self.assertIn(f"{a} number maximum well depth: 8 m [official]", listing)
        self.assertIn(f"{b} number maximum well depth: 8 ft [review]", listing)
        self.assertEqual(self.entity_lines()["Garden Pump"], "Garden Pump — attributes: maximum well depth")

    def test_merge_attribute_refuses_an_unknown_entity_or_attribute(self):
        self.add_ok(PUMP_URL, pump_fact(attribute="max depth", value="8 m", quote="from a max depth of 8 m"))
        before = self.listing()
        for args in (("Lawn Mower", "maximum well depth", "max depth"),
                     ("Garden Pump", "maximum well depth", "max height")):
            with self.subTest(args):
                out = cli("merge-attribute", self.folder, *args)
                self.assertTrue(out and not out[0].startswith("ok"), out)
                self.assertEqual(self.listing(), before)


# ---------------------------------------------------------------- condition 2: finish settles conflicts

class Finish(DocCase):
    def setUp(self):
        super().setUp()
        for url, text in ((PUMP_URL, PUMP_TEXT), (REVIEW_URL, REVIEW_TEXT), (CATALOGUE_URL, CATALOGUE_TEXT),
                          (NEWS_URL, NEWS_TEXT)):
            self.save(url, text)

    def weight(self, url, value, quote, kind) -> str:
        return self.add_ok(url, pump_fact(attribute="weight", value=value, quote=quote, source_kind=kind))

    def test_the_strongest_source_wins(self):
        official = self.add_ok(PUMP_URL, pump_fact())
        review = self.add_ok(REVIEW_URL, pump_fact(attribute="Maximum Pressure", value="8 bar",  # attribute any case
                                                   quote="it reached a maximum pressure of 8 bar",
                                                   source_kind="review"))
        cli("finish", self.folder)
        self.assertEqual(self.listed_ids(), [official])
        d = self.dossier()
        self.assertTrue(id_lines(d, official) and lines_with(d, "6 bar"), d)
        dropped = lines_with(d, "8 bar")
        self.assertTrue(any("conflict: weaker source" in line for line in dropped), d)
        self.assertNotIn(review, self.listed_ids())

    def test_aggregator_or_media_beat_a_review(self):
        kept = self.weight(CATALOGUE_URL, "9 kg", "the Garden Pump weighs 9 kg", "aggregator")
        self.weight(REVIEW_URL, "8 kg", "It weighed 8 kg on our scale", "review")
        cli("finish", self.folder)
        self.assertEqual(self.listed_ids(), [kept])

    def test_equal_sources_that_disagree_leave_no_value(self):
        self.weight(CATALOGUE_URL, "9 kg", "the Garden Pump weighs 9 kg", "aggregator")
        self.weight(NEWS_URL, "10 kg", "the Garden Pump weighs 10 kg", "media")
        self.weight(REVIEW_URL, "8 kg", "It weighed 8 kg on our scale", "review")
        other = self.add_ok(PUMP_URL, pump_fact())
        cli("finish", self.folder)
        self.assertEqual(self.listed_ids(), [other])
        d = self.dossier()
        for value in ("9 kg", "10 kg"):
            self.assertTrue(any("disputed: equal sources disagree" in line for line in lines_with(d, value)),
                            f"{value}:\n{d}")
        self.assertTrue(any(("disputed: equal sources disagree" in line or "conflict: weaker source" in line)
                            for line in lines_with(d, "8 kg")), d)

    def test_two_official_sources_that_disagree_leave_no_value(self):
        self.save(SPEC_URL, SPEC_TEXT)
        self.weight(PUMP_URL, "7 kg", "The pump weighs 7 kg", "official")
        self.weight(SPEC_URL, "9 kg", "the Garden Pump weighs 9 kg", "official")
        self.weight(REVIEW_URL, "8 kg", "It weighed 8 kg on our scale", "review")
        cli("finish", self.folder)
        self.assertEqual(self.listed_ids(), [])

    def test_values_that_differ_only_in_writing_are_the_same(self):
        pairs = [
            ("number", "flow per hour", ("1,500 litres", "moves 1,500 litres per hour"),
             ("1500 l", "it moved 1500 litres per hour")),
            ("price", "full set price", ("1,250 EUR", "The full set costs 1,250 EUR"),
             ("1250 EUR", "We paid 1250 EUR for the full set")),
            ("address", "service point", ("Main St 5", "The service point is at Main St 5"),
             ("Main Street 5", "the service point at Main Street 5")),
            ("address", "shop address", ("12 Mill Street", "in the shop at 12 Mill Street"),
             ("12 Mill Street, Riverton", "The shop at 12 Mill Street, Riverton")),
        ]
        kept = []
        for typ, attr, (v1, q1), (v2, q2) in pairs:
            kept.append(self.add_ok(PUMP_URL, pump_fact(type=typ, attribute=attr, value=v1, quote=q1)))
            kept.append(self.add_ok(REVIEW_URL, pump_fact(type=typ, attribute=attr, value=v2, quote=q2,
                                                          source_kind="review")))
        cli("finish", self.folder)
        self.assertEqual(sorted(self.listed_ids()), sorted(kept))

    def test_another_number_or_unit_is_a_conflict(self):
        pairs = [
            ("address", "shop address", ("12 Mill Street", "in the shop at 12 Mill Street"),
             ("14 Mill Street", "another shop at 14 Mill Street")),
            ("price", "spare hose price", ("35 EUR", "A spare hose costs 35 EUR"),
             ("35 USD", "Abroad a spare hose costs 35 USD")),
        ]
        kept = []
        for typ, attr, (v1, q1), (v2, q2) in pairs:
            kept.append(self.add_ok(PUMP_URL, pump_fact(type=typ, attribute=attr, value=v1, quote=q1)))
            self.add_ok(REVIEW_URL, pump_fact(type=typ, attribute=attr, value=v2, quote=q2, source_kind="review"))
        cli("finish", self.folder)
        self.assertEqual(sorted(self.listed_ids()), sorted(kept))

    def test_a_conflict_made_by_merging_attributes(self):
        kept = self.add_ok(PUMP_URL, pump_fact(attribute="max depth", value="8 m", quote="from a max depth of 8 m"))
        self.add_ok(REVIEW_URL, pump_fact(attribute="maximum well depth", value="8 ft", source_kind="review",
                                          quote="from a maximum well depth of 8 ft"))
        cli("merge-attribute", self.folder, "Garden Pump", "maximum well depth", "max depth")
        cli("finish", self.folder)
        self.assertEqual(self.listed_ids(), [kept])  # «8 m» and «8 ft» are not the same value

    def test_no_conflict_across_attributes_entities_or_claims(self):
        kept = [
            self.add_ok(PUMP_URL, pump_fact()),
            self.add_ok(REVIEW_URL, pump_fact(attribute="pressure in our test", value="8 bar",
                                              quote="it reached a maximum pressure of 8 bar", source_kind="review")),
            self.add_ok(REVIEW_URL, pump_fact(entity="Test Pump", value="8 bar",
                                              quote="it reached a maximum pressure of 8 bar", source_kind="review")),
            self.add_ok(PUMP_URL, claim("Garden Pump", "is built for small gardens", entity_kind="product",
                                        attribute="use", value="small gardens")),
            self.add_ok(REVIEW_URL, claim("Garden Pump", "We tested the Garden Pump at home", entity_kind="product",
                                          attribute="use", value="tested at home", source_kind="review")),
        ]
        cli("finish", self.folder)
        self.assertEqual(sorted(self.listed_ids()), sorted(kept))

    def test_the_dossier_lists_every_fact_with_its_source(self):
        official = self.add_ok(PUMP_URL, pump_fact())
        weak = self.add_ok(REVIEW_URL, pump_fact(attribute="weight", value="8 kg",
                                                 quote="It weighed 8 kg on our scale", source_kind="review"))
        cli("finish", self.folder)
        d = self.dossier()
        for fid, needles in ((official, ("maximum pressure", "6 bar", "official", PUMP_URL)),
                             (weak, ("weight", "8 kg", "review", REVIEW_URL))):
            self.assertTrue(any(all(n.lower() in line.lower() for n in needles) for line in id_lines(d, fid)),
                            f"{fid} with {needles}:\n{d}")


# ---------------------------------------------------------------- condition 4: the dossier holds only facts with
# sources, what was left out with its reason, the sources list and what was not found

class Dossier(DocCase):
    def setUp(self):
        super().setUp()
        self.save(PUMP_URL, PUMP_TEXT)
        self.add_ok(PUMP_URL, pump_fact())  # F1, 6 bar

    def gap(self, text: str) -> list[str]:
        return cli("gap", self.folder, stdin=text)

    def test_a_gap_is_listed_under_not_found(self):
        self.assertEqual(self.gap("The noise level of the pump"), ["ok"])
        # no number or fact-id check on a gap
        self.assertEqual(self.gap("How long the pump lasts at 3 hours a day, which F9 does not say"), ["ok"])
        cli("finish", self.folder)
        items = section(self.dossier(), "## Not found")
        self.assertIn("- The noise level of the pump", items, self.dossier())
        self.assertIn("- How long the pump lasts at 3 hours a day, which F9 does not say", items)

    def test_an_empty_gap_is_rejected(self):
        for text in ("", "   \n  "):
            with self.subTest(repr(text)):
                out = self.gap(text)
                self.assertEqual(len(out), 1, out)
                self.assertTrue(out[0].startswith("rejected:"), out)
        cli("finish", self.folder)
        items = [line for line in section(self.dossier(), "## Not found") if line.startswith("-")]
        self.assertEqual([line for line in items if not line[1:].strip()], [], "an empty gap was listed")

    def test_the_sources_list(self):
        self.save("https://garden.example/copied", f"A page a reader copied by hand. {LONG_PARAGRAPH}")
        cli("finish", self.folder)
        rows = section(self.dossier(), "## Sources")
        self.assertTrue(rows, self.dossier())
        for url, needle, via_webfetch in ((PUMP_URL, "maximum pressure of 6 bar", True),
                                          ("https://garden.example/copied", "copied by hand", True)):
            with self.subTest(url):
                mine = [line for line in rows if url in line]
                self.assertEqual(len(mine), 1, rows)
                self.assertIn(self.file_with(needle).name, mine[0])
                self.assertTrue(any(d in mine[0] for d in today_dates()), mine[0])
                self.assertEqual("WebFetch" in mine[0], via_webfetch, mine[0])

    def test_a_fetched_page_is_not_marked_webfetch(self):
        site = Site({"/pump": (200, page_html(f"<p>{LONG_PARAGRAPH}</p>"))})
        self.addCleanup(site.close)
        url = site.url("/pump")
        cli("fetch", self.folder, url)
        cli("finish", self.folder)
        mine = [line for line in section(self.dossier(), "## Sources") if url in line]
        self.assertEqual(len(mine), 1, self.dossier())
        self.assertNotIn("WebFetch", mine[0])

    def test_every_fact_line_is_a_kept_fact_with_its_url_or_a_dropped_one_with_its_reason(self):
        self.save(REVIEW_URL, REVIEW_TEXT)
        self.add_ok(REVIEW_URL, pump_fact(value="8 bar", quote="it reached a maximum pressure of 8 bar",
                                          source_kind="review"))  # dropped: weaker source
        self.add_ok(PUMP_URL, pump_fact(type="price", attribute="price", value="129 euros",
                                        quote="It costs 129 euros"))
        self.gap("The noise level of the pump")
        cli("finish", self.folder)
        kept = set(self.listed_ids())
        reasons = ("conflict: weaker source", "disputed: equal sources disagree")
        seen = set()
        for line in self.dossier().splitlines():
            for fid in re.findall(r"\b(F\d+)\b", line):
                seen.add(fid)
                with self.subTest(line=line):
                    if fid in kept:
                        self.assertTrue(PUMP_URL in line or REVIEW_URL in line, "a kept fact with no url")
                    else:
                        self.assertTrue(any(r in line for r in reasons), "a fact not in the base, with no reason")
        self.assertEqual(seen, {"F1", "F2", "F3"})


# ---------------------------------------------------------------- the gate sources-conflict

class SourcesConflictGate(DocCase):
    def setUp(self):
        super().setUp()
        self.save(PUMP_URL, PUMP_TEXT)
        self.save(REVIEW_URL, REVIEW_TEXT)
        self.add_ok(PUMP_URL, pump_fact())
        self.dropped = self.add_ok(REVIEW_URL, pump_fact(value="8 bar", quote="it reached a maximum pressure of 8 bar",
                                                         source_kind="review"))

    def hand_dossier(self):
        (self.folder / "FACTS.md").write_text("# Facts\n\nWritten by hand.\n", encoding="utf-8")

    def test_before_the_dossier_nothing_fails(self):
        self.assertEqual(sources_conflict_gate()(self.folder), [])

    def test_a_conflict_left_in_the_base_fails_once_the_dossier_exists(self):
        self.hand_dossier()
        fs = sources_conflict_gate()(self.folder)
        self.assertTrue(fs)
        self.assertEqual({f.gate for f in fs}, {"sources-conflict"})
        self.assertTrue(all(f.line().startswith("[sources-conflict]") for f in fs))

    def test_the_gate_uses_the_same_rule_of_same_values(self):
        cli("finish", self.folder)
        self.add_ok(PUMP_URL, pump_fact(type="price", attribute="full set price", value="1,250 EUR",
                                        quote="The full set costs 1,250 EUR"))
        self.add_ok(REVIEW_URL, pump_fact(type="price", attribute="full set price", value="1250 EUR",
                                          quote="We paid 1250 EUR for the full set", source_kind="review"))
        cli("finish", self.folder)  # facts added after the dossier make it stale (see the stale-dossier test)
        self.assertEqual(sources_conflict_gate()(self.folder), [])
        self.add_ok(PUMP_URL, pump_fact(type="price", attribute="spare hose price", value="35 EUR",
                                        quote="A spare hose costs 35 EUR"))
        self.add_ok(REVIEW_URL, pump_fact(type="price", attribute="spare hose price", value="35 USD",
                                          quote="Abroad a spare hose costs 35 USD", source_kind="review"))
        self.assertIn("sources-conflict", [f.gate for f in sources_conflict_gate()(self.folder)])

    def test_a_fact_added_after_the_dossier_makes_it_stale(self):
        # added to the contract by the implementer: FACTS.md is the dossier of the base as it stands, so a fact the
        # planner would not see fails until `finish` runs again
        cli("finish", self.folder)
        self.add_ok(PUMP_URL, pump_fact(type="price", attribute="full set price", value="1,250 EUR",
                                        quote="The full set costs 1,250 EUR"))
        self.assertIn("sources-conflict", [f.gate for f in sources_conflict_gate()(self.folder)])
        cli("finish", self.folder)
        self.assertEqual(sources_conflict_gate()(self.folder), [])

    def test_after_finish_it_passes(self):
        cli("finish", self.folder)
        self.assertEqual(sources_conflict_gate()(self.folder), [])
        self.assertEqual(fact_quoted_gate()(self.folder), [])

    def test_a_dropped_fact_missing_from_the_dossier_fails(self):
        cli("finish", self.folder)
        d = self.dossier()
        kept = [line for line in d.splitlines() if "8 bar" not in line and not re.search(rf"\b{self.dropped}\b", line)]
        self.assertNotEqual(len(kept), len(d.splitlines()))
        (self.folder / "FACTS.md").write_text("\n".join(kept) + "\n", encoding="utf-8")
        self.assertIn("sources-conflict", [f.gate for f in sources_conflict_gate()(self.folder)])


# ---------------------------------------------------------------- the hook

def run_hook(payload: dict) -> dict | None:
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                       timeout=200)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def bash_payload(command: str, cwd: str) -> dict:
    d = json.loads(RECORDED.read_text())
    d["tool_name"] = "Bash"
    d["cwd"] = cwd
    d["tool_input"] = {"command": command, "description": "Run the research CLI"}
    d["tool_response"] = {"stdout": "", "stderr": "", "interrupted": False}
    return d


def write_payload(path: Path) -> dict:
    d = json.loads(RECORDED.read_text())
    d["tool_name"] = "Write"
    d["tool_input"]["file_path"] = str(path)
    d["tool_response"]["filePath"] = str(path)
    return d


def ctx(out: dict | None) -> str:
    assert out is not None, "the hook said nothing"
    return out["hookSpecificOutput"]["additionalContext"]


class Hook(DocCase):
    def setUp(self):
        super().setUp()
        self.save(PUMP_URL, PUMP_TEXT)
        self.add_ok(PUMP_URL, pump_fact())

    def cmd(self, sub: str) -> str:
        return f"python3 {RESEARCH} {sub} {self.folder} --url {PUMP_URL} <<'EOF'\n{{}}\nEOF"

    def test_a_research_command_runs_fact_quoted(self):
        self.assertIsNone(run_hook(bash_payload(self.cmd("add"), self.tmp)), "passing gates must print nothing")
        self.edit_facts_json("It reaches a maximum pressure of 6 bar", "It reaches a top pressure of 6 bar")
        for sub in ("fetch", "save", "add", "merge", "merge-attribute", "gap", "finish"):
            with self.subTest(sub):
                self.assertIn("[fact-quoted]", ctx(run_hook(bash_payload(self.cmd(sub), self.tmp))))
        with self.subTest("folder relative to cwd"):
            self.assertIn("[fact-quoted]", ctx(run_hook(bash_payload(f"python3 {RESEARCH} finish doc", self.tmp))))
        for sub in ("list", "entities", "duplicates"):
            with self.subTest(f"{sub} changes nothing"):
                self.assertIsNone(run_hook(bash_payload(f"python3 {RESEARCH} {sub} {self.folder}", self.tmp)))
        with self.subTest("a folder with no BRIEF.md"):
            (self.folder / "BRIEF.md").unlink()
            self.assertIsNone(run_hook(bash_payload(self.cmd("add"), self.tmp)))

    def test_a_write_of_facts_json_runs_fact_quoted(self):
        facts = self.folder / "research" / "facts.json"
        self.assertIsNone(run_hook(write_payload(facts)))
        self.edit_facts_json("6 bar", "7 bar")
        self.assertIn("[fact-quoted]", ctx(run_hook(write_payload(facts))))
        self.assertIn("[fact-quoted]", ctx(run_hook({**write_payload(facts), "tool_name": "Edit"})))

    def test_a_conflict_left_after_the_dossier_names_sources_conflict(self):
        self.save(REVIEW_URL, REVIEW_TEXT)
        cli("finish", self.folder)
        self.assertIsNone(run_hook(bash_payload(f"python3 {RESEARCH} finish {self.folder}", self.tmp)))
        # a review's value under another name, merged into the pump after the dossier was written: a conflict
        self.add_ok(REVIEW_URL, pump_fact(entity="The Garden Pump", value="8 bar",
                                          quote="it reached a maximum pressure of 8 bar", source_kind="review"))
        cli("merge", self.folder, "Garden Pump", "The Garden Pump")
        out = run_hook(bash_payload(f"python3 {RESEARCH} merge {self.folder} 'Garden Pump' 'The Garden Pump'",
                                    self.tmp))
        self.assertIn("[sources-conflict]", ctx(out))
        cli("finish", self.folder)
        self.assertIsNone(run_hook(bash_payload(f"python3 {RESEARCH} finish {self.folder}", self.tmp)))


class Library(unittest.TestCase):
    def test_both_fact_base_gates_are_on_with_their_scripts(self):
        rows = {}
        for line in LIBRARY.read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0] in ("fact-quoted", "sources-conflict"):
                rows[cells[0]] = cells
        self.assertEqual(rows["fact-quoted"][2], "on")
        self.assertIn("scripts/fact_quoted.py", rows["fact-quoted"][3])
        self.assertEqual(rows["sources-conflict"][2], "on")
        self.assertIn("scripts/sources_conflict.py", rows["sources-conflict"][3])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- holes the code review found (added by the implementer)

class ReviewFindings(DocCase):
    def setUp(self):
        super().setUp()
        self.save(PUMP_URL, PUMP_TEXT)
        self.save(REVIEW_URL, "Listing: the spare hose is from 35. Abroad: 35 USD. Here: 35 EUR. "
                  "Elsewhere: 35 PLN. Prices may change in 2026. 3 models launched in 2026. " + FILLER)
        self.save(CATALOGUE_URL, "Dates: 12 maja 2026; 5 de septiembre de 2026; 5 de setembro de 2026; "
                  "5 de noviembre de 2026; on 2 May 2026; 03.04.2026. " + FILLER)

    def test_a_corrupt_base_is_never_written_over(self):
        self.add_ok(PUMP_URL, pump_fact())
        path = self.folder / "research" / "facts.json"
        broken = path.read_text(encoding="utf-8")[:-5]
        path.write_text(broken, encoding="utf-8")
        files = {p: p.read_bytes() for p in self.source_files()}
        for args, stdin in ((("add", self.folder, "--url", PUMP_URL), json.dumps(pump_fact(attribute="weight",
                             value="7 kg", quote="The pump weighs 7 kg"))),
                            (("save", self.folder, "https://garden.example/new"), f"New page. {LONG_PARAGRAPH}"),
                            (("finish", self.folder), "")):
            out = cli(*args, stdin=stdin)
            self.assertTrue(out and out[0].startswith("refused"), out)
        self.assertEqual(path.read_text(encoding="utf-8"), broken)
        self.assertEqual({p: p.read_bytes() for p in self.source_files()}, files)
        self.assertFalse((self.folder / "FACTS.md").exists())
        self.assertEqual([f.gate for f in fact_quoted_gate()(self.folder)], ["fact-quoted"])

    def _price(self, value, url=REVIEW_URL, kind="media"):
        quote = {"35": "the spare hose is from 35", "35 EUR": "Here: 35 EUR", "35 PLN": "Elsewhere: 35 PLN"}[value]
        return self.add_ok(url, pump_fact(type="price", attribute="spare hose price", value=value, quote=quote,
                                          source_kind=kind))

    def _bare_value_case(self, order):
        for v in order:
            self._price(v)
        cli("finish", self.folder)
        kept = [ln for ln in section(self.dossier(), "### Garden Pump") if "spare hose price" in ln]
        self.assertEqual(kept, [], order)  # equal sources: «35 EUR» and «35 PLN» disagree, so no value stays

    def test_a_bare_value_does_not_join_two_currencies(self):
        self._bare_value_case(("35", "35 EUR", "35 PLN"))

    def test_a_bare_value_does_not_join_two_currencies_in_another_order(self):
        self._bare_value_case(("35 EUR", "35 PLN", "35"))

    def test_a_fact_injected_by_script_stops_finish(self):
        self.add_ok(PUMP_URL, pump_fact())
        path = self.folder / "research" / "facts.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["facts"].append({**data["facts"][0], "id": "F99", "value": "99 m", "quote": "invented"})
        path.write_text(json.dumps(data), encoding="utf-8")
        out = cli("finish", self.folder)
        self.assertTrue(out[0].startswith("refused"), out)
        self.assertFalse((self.folder / "FACTS.md").exists())

    def test_month_names_and_numeric_dates(self):
        ok = (("2026-05-12", "12 maja 2026"), ("2026-09-05", "5 de septiembre de 2026"),
              ("2026-09-05", "5 de setembro de 2026"), ("2026-11-05", "5 de noviembre de 2026"),
              ("2026-05-02", "on 2 May 2026"), ("2026-04-03", "03.04.2026"))
        for value, quote in ok:
            with self.subTest(quote=quote):
                out = self.add(CATALOGUE_URL, pump_fact(type="date", attribute=f"date {quote}", value=value,
                                                        quote=quote))
                self.assertRegex(out[0], r"^ok F\d+$")
        bad = (("2026-05", "Prices may change in 2026"), ("2026-03", "3 models launched in 2026"))
        for value, quote in bad:
            with self.subTest(quote=quote):
                out = self.add(REVIEW_URL, pump_fact(type="date", attribute=f"date {quote}", value=value,
                                                     quote=quote))
                self.assertTrue(out[0].startswith("rejected"), out)

    def test_a_hand_written_claim_without_attribute_fails_and_does_not_crash(self):
        cli("finish", self.folder)
        path = self.folder / "research" / "facts.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["facts"].append({"id": "F7", "entity": "Garden Pump", "entity_kind": "product", "type": "claim",
                              "value": "light", "quote": "invented", "source_url": PUMP_URL,
                              "source_kind": "official"})
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(sources_conflict_gate()(self.folder), [])
        self.assertEqual([f.gate for f in fact_quoted_gate()(self.folder)], ["fact-quoted"])

    def test_zero_decimals_are_no_number_of_their_own(self):
        self.save(NEWS_URL, "The full set now costs 1.250,00 EUR at the market. " + FILLER)
        self.add_ok(PUMP_URL, pump_fact(type="price", attribute="full set price", value="1,250 EUR",
                                        quote="The full set costs 1,250 EUR"))
        self.add_ok(NEWS_URL, pump_fact(type="price", attribute="full set price", value="1.250,00 EUR",
                                        quote="The full set now costs 1.250,00 EUR", source_kind="media"))
        out = cli("finish", self.folder)
        self.assertIn("0 dropped", out[0])

    def dossier(self) -> str:
        return (self.folder / "FACTS.md").read_text(encoding="utf-8")


class ParallelFetch(DocCase):
    def test_two_fetches_at_once_keep_the_budget(self):
        pages = {f"/p{i}": (200, page_html(f"<p>Page number {i}. {LONG_PARAGRAPH}</p>", junk=False))
                 for i in range(12)}
        site = Site(pages)
        self.addCleanup(site.close)
        for i in range(9):
            self.save(f"https://garden.example/page{i}", f"Saved page {i}. {LONG_PARAGRAPH}")
        procs = [subprocess.Popen([sys.executable, str(RESEARCH), "fetch", str(self.folder), site.url(f"/p{i}")],
                                  stdout=subprocess.PIPE, text=True, env=ENV) for i in (10, 11)]
        for p in procs:
            p.communicate(timeout=60)
        data = json.loads((self.folder / "research" / "facts.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["sources"]), BUDGET)


class SecondReviewFindings(DocCase):
    def setUp(self):
        super().setUp()
        self.save(PUMP_URL, PUMP_TEXT)
        self.save(REVIEW_URL, "Listing: the spare hose is from 35. Abroad: 35 USD. Here: 35 EUR. "
                  "Elsewhere: 35 PLN. Version 5 released in March 2024. The junior plan 2024. "
                  "The small model weighs 1.5 kg. " + FILLER)
        self.save(NEWS_URL, "Our shop: the spare hose is from 35 at the counter. " + FILLER)

    def price(self, value, url, kind):
        quote = {"35": "the spare hose is from 35", "35 EUR": "Here: 35 EUR", "35 PLN": "Elsewhere: 35 PLN"}[value]
        return self.add_ok(url, pump_fact(type="price", attribute="spare hose price", value=value, quote=quote,
                                          source_kind=kind))

    def test_a_strong_bare_value_leaves_one_value_and_the_gate_passes(self):
        strong = self.price("35", NEWS_URL, "official")
        self.price("35 EUR", REVIEW_URL, "media")
        self.price("35 PLN", REVIEW_URL, "media")
        cli("finish", self.folder)
        text = (self.folder / "FACTS.md").read_text(encoding="utf-8")
        kept = [ln for ln in section(text, "### Garden Pump") if "spare hose price" in ln]
        self.assertEqual([ln.split()[1] for ln in kept], [strong])
        self.assertEqual(sources_conflict_gate()(self.folder), [])

    def test_a_dossier_without_a_base_fails(self):
        (self.folder / "research" / "facts.json").unlink()
        (self.folder / "FACTS.md").write_text("# Facts\n\n- F1 weight: 99 kg\n", encoding="utf-8")
        self.assertEqual([f.gate for f in sources_conflict_gate()(self.folder)], ["sources-conflict"])

    def test_a_bash_write_of_facts_json_runs_the_gates(self):
        self.add_ok(PUMP_URL, pump_fact())
        path = self.folder / "research" / "facts.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["facts"][0]["quote"] = "invented words"
        path.write_text(json.dumps(data), encoding="utf-8")
        cmd = f"python3 -c 'pass' > /dev/null; cat {path} > {path}.bak; cp {path}.bak {path}"
        self.assertIn("[fact-quoted]", ctx(run_hook(bash_payload(cmd, self.tmp))))
        self.assertIsNone(run_hook(bash_payload(f"cat {self.folder}/FACTS.md", self.tmp)),
                          "reading the dossier runs nothing")

    def test_a_record_without_id_or_attribute_is_refused_not_a_crash(self):
        path = self.folder / "research" / "facts.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["facts"].append({"entity": "Garden Pump", "entity_kind": "product", "type": "claim",
                              "value": "built for small gardens",
                              "quote": "The Garden Pump GP is built for small gardens", "source_url": PUMP_URL,
                              "source_kind": "official"})
        path.write_text(json.dumps(data), encoding="utf-8")
        r = subprocess.run([sys.executable, str(RESEARCH), "finish", str(self.folder)], capture_output=True,
                           text=True, env=ENV)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("refused"), r.stdout)
        out = cli("remove", self.folder, "F1", "--reason", "x")
        self.assertTrue(out[0].startswith("no fact"), out)

    def test_remove_takes_a_fact_out(self):
        fid = self.add_ok(PUMP_URL, pump_fact())
        self.assertTrue(cli("remove", self.folder, fid, "--reason", "added by mistake")[0].startswith("ok"))
        self.assertNotIn(fid, " ".join(cli("list", self.folder)))

    def test_tighter_value_checks(self):
        cases = (
            pump_fact(type="price", attribute="spare hose price", value="35 EUR", quote="Elsewhere: 35 PLN"),
            pump_fact(type="number", attribute="weight", value="5.1 kg", quote="The small model weighs 1.5 kg"),
            pump_fact(type="date", attribute="release", value="2024-03-05", quote="Version 5 released in March 2024"),
            pump_fact(type="date", attribute="plan", value="2024-06", quote="The junior plan 2024"),
            pump_fact(type="claim", attribute=None, value="from 35", quote="from 35"),
        )
        for f in cases:
            with self.subTest(f=f["value"]):
                out = self.add(REVIEW_URL, f)
                self.assertTrue(out[0].startswith("rejected"), out)
