#!/usr/bin/env python3
"""mind.py: the write path for bots. Log a signal, log a phrase use, or propose a belief change.

  mind.py signal  --bot B --segment S --polarity - --heat 1 --type T --topic X --did "..." --said "verbatim" [--supports "Belief"] [--contradicts "Belief"] [--explicit] [--session ID]
  mind.py used    --bot B (--phrase "..." | --belief "Belief")
  mind.py propose --bot B --claim "..." --segments S [S..] --why "..." [--signals S-..]
  mind.py propose --bot B --edit "Belief" --field applies_when --value "..." --why "..."
Use --said - to read his words from stdin (multi-line).
"""
import argparse
import datetime as dt
import secrets
import sys
from pathlib import Path

from vaultlib import SEGMENTS, VAULT, read_note, slug, write_note

EDITABLE = {"applies_when", "not_when", "tensions", "segments", "topics"}


def belief_names():
    return {p.stem for p in (VAULT / "20_Beliefs").glob("*.md")}


def check_beliefs(names):
    known = belief_names()
    bad = [n for n in names if n not in known]
    if bad:
        sys.exit(f"Unknown belief(s): {bad}\nKnown: {sorted(known)}")


def cmd_signal(a):
    if a.segment not in SEGMENTS:
        sys.exit(f"--segment must be one of {SEGMENTS}")
    pol = {"-": "-", "+": "+", "neg": "-", "pos": "+"}.get(a.polarity)
    if not pol:
        sys.exit("--polarity must be - or +")
    if not 0 <= a.heat <= 3:
        sys.exit("--heat must be 0-3")
    said = sys.stdin.read() if a.said == "-" else a.said
    if not said.strip():
        sys.exit("--said is required (his exact words)")
    check_beliefs(a.supports + a.contradicts)
    now = dt.datetime.now()
    sid = f"S-{now:%Y%m%d-%H%M}-{slug(a.bot)}-{secrets.token_hex(2)}"
    fm = {
        "class": "signal", "id": sid, "date": now.strftime("%Y-%m-%dT%H:%M"),
        "bot": slug(a.bot), "segment": a.segment, "session": a.session or "",
        "type": slug(a.type), "topic": slug(a.topic), "polarity": pol, "heat": a.heat,
        "explicit": a.explicit,
        "supports": [f"[[{n}]]" for n in a.supports],
        "contradicts": [f"[[{n}]]" for n in a.contradicts],
        "example": False,
    }
    quoted = "\n".join("> " + line for line in said.rstrip("\n").split("\n"))
    body = f"**Bot did:** {a.did}\n\n**He said (verbatim):**\n{quoted}\n"
    if a.context:
        body += f"\n**Context:** {a.context}\n"
    path = VAULT / "30_Signals" / f"{now:%Y-%m}" / f"{sid}-{slug(a.topic) or 'signal'}.md"
    write_note(path, fm, body)
    print(path)


def cmd_used(a):
    if not (a.phrase or a.belief):
        sys.exit("give --phrase or --belief")
    if a.belief:
        check_beliefs([a.belief])
    item = f'phrase: "{a.phrase.strip()}"' if a.phrase else f"belief: [[{a.belief}]]"
    line = f"- {dt.date.today():%Y-%m-%d} | {slug(a.bot)} | {item}\n"
    with open(VAULT / "_system" / "Reuse guard.md", "a", encoding="utf-8") as f:
        f.write(line)
    print(line.strip())


def cmd_propose(a):
    today = dt.date.today().isoformat()
    if a.edit:
        check_beliefs([a.edit])
        if a.field not in EDITABLE:
            sys.exit(f"--field must be one of {sorted(EDITABLE)}")
        if a.value is None:
            sys.exit("--value required for --edit")
        pid = f"P-edit-{slug(a.edit)[:30]}-{slug(a.field)}-{secrets.token_hex(2)}"
        fm = {"class": "proposal", "id": pid, "kind": "edit", "status": "proposed", "origin": slug(a.bot),
              "proposed_on": today, "target": f"[[{a.edit}]]", "field": a.field, "value": a.value, "why": a.why}
        body = f"**Proposed edit** to [[{a.edit}]] · `{a.field}` →\n> {a.value}\n\n**Why:** {a.why}\n"
    else:
        if not a.claim:
            sys.exit("give --claim (new belief) or --edit (change)")
        segs = a.segments or []
        if any(s not in SEGMENTS for s in segs) or not segs:
            sys.exit(f"--segments must be from {SEGMENTS}")
        pid = f"P-{slug(a.claim)[:40]}"
        fm = {"class": "proposal", "id": pid, "kind": "new", "status": "proposed", "origin": slug(a.bot),
              "proposed_on": today, "claim": a.claim, "segments": segs, "topics": [slug(t) for t in a.topics],
              "applies_when": "", "not_when": "", "tensions": [], "why": a.why,
              "signals": [f"[[{s}]]" for s in a.signals]}
        body = (f"**Claim:** {a.claim}\n\n**Why:** {a.why}\n\n**Example:** \n\n**Counterexample:** \n")
    path = VAULT / "50_Hypotheses" / f"{pid}.md"
    if path.exists():
        sys.exit(f"Already proposed: {path}")
    write_note(path, fm, body)
    print(path)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("signal")
    s.add_argument("--bot", required=True)
    s.add_argument("--segment", required=True)
    s.add_argument("--polarity", required=True)
    s.add_argument("--heat", type=int, default=1)
    s.add_argument("--type", default="")
    s.add_argument("--topic", default="")
    s.add_argument("--did", required=True)
    s.add_argument("--said", required=True)
    s.add_argument("--supports", action="append", default=[])
    s.add_argument("--contradicts", action="append", default=[])
    s.add_argument("--explicit", action="store_true")
    s.add_argument("--session", default="")
    s.add_argument("--context", default="")
    u = sub.add_parser("used")
    u.add_argument("--bot", required=True)
    u.add_argument("--phrase")
    u.add_argument("--belief")
    r = sub.add_parser("propose")
    r.add_argument("--bot", required=True)
    r.add_argument("--claim")
    r.add_argument("--segments", nargs="*")
    r.add_argument("--topics", nargs="*", default=[])
    r.add_argument("--signals", nargs="*", default=[])
    r.add_argument("--edit")
    r.add_argument("--field")
    r.add_argument("--value")
    r.add_argument("--why", required=True)
    a = p.parse_args()
    {"signal": cmd_signal, "used": cmd_used, "propose": cmd_propose}[a.cmd](a)


if __name__ == "__main__":
    main()
