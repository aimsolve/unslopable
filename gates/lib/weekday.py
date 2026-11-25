#!/usr/bin/env python3
"""The weekday of a date: the tool of the judge gate-date-weekday (library: a date and weekday agree with the
calendar).

  python3 weekday.py 2026-11-23 2026-03-02     ->  2026-11-23 Monday
                                                   2026-03-02 Monday
Dates are ISO `YYYY-MM-DD`; anything else prints `<arg> not a date`.
"""
import sys
from datetime import date


def main(args: list) -> None:
    if not args:
        print("usage: weekday.py YYYY-MM-DD [YYYY-MM-DD …]")
        return
    for a in args:
        try:
            print(f"{a} {date.fromisoformat(a.strip()):%A}")
        except ValueError:
            print(f"{a} not a date (write it as YYYY-MM-DD)")


if __name__ == "__main__":
    main(sys.argv[1:])
