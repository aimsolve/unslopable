"""date-tense and date-weekday (both): finds every sentence with something that looks like a date, in any form;
the judges check the tense against today and the weekday against the calendar."""
from __future__ import annotations

import re

from docs import Doc
from common import Unit, flagged


_MONTH = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December|"
          r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.?")
_WEEKDAY = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|Sat|Sun)"
DATE = re.compile(
    r"(?<![\w.-])(?:\d{4}-\d{1,2}-\d{1,2}"                                     # 2026-03-02
    r"|\d{4}[./]\d{1,2}[./]\d{1,2}"                                             # 2026/03/02, 2026.03.02
    r"|\d{1,2}[./]\d{1,2}[./](?:\d{4}|\d{2})"                                    # 02.03.2026, 2/3/26
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH + r"(?:,?\s+\d{4})?"      # 2 March 2026, 2nd of March
    r"|" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?(?![\d:])(?:,?\s+\d{4})?"       # March 2, 2026
    r"|" + _MONTH + r"\s+\d{4}"                                                 # March 2026
    r"|" + _WEEKDAY + r",?\s+\d{1,2}[./]\d{1,2}"                                # Monday 2.3
    r"|(?i:Q[1-4]|H[12])\s+\d{4}"                                               # Q3 2026
    r"|(?i:spring|summer|autumn|fall|winter)\s+(?:of\s+)?(?:19|20)\d{2}"           # spring 2026
    r"|(?i:in|since|by|until|till|before|after|from|during|through|early|late|mid-?|end of|start of)\s+(?:19|20)\d{2}"
    r")(?![\w-])")


def date_hits(doc: Doc) -> list[tuple[Unit, str]]:
    """Every sentence (paragraph sentence, list item, table cell) with something that looks like a date."""
    return flagged(doc, DATE)
