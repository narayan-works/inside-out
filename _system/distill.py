#!/usr/bin/env python3
"""
distill.py: nightly consolidation for an inside-out vault (v0, no LLM).

Order of work:
  1. Apply the owner's Inbox decisions (yes / not now / no).
  2. Process new pivot events, which flag beliefs for reconfirmation.
  3. Score every belief from signals: heat cooling, decay, contradictions.
  4. Find repeat patterns among unlinked signals and turn them into proposals or hypotheses.
  5. Enforce the change cap, then write the Inbox, Hypotheses, hub summaries,
     reuse guard and a dated changelog.

  python3 distill.py --dry-run              # report only, writes nothing
  python3 distill.py                        # apply
  python3 distill.py --now 2026-10-09T23:00 # pretend it's another time (testing)
  python3 distill.py --include-examples     # count signals marked example: true
"""
import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vaultlib import (VAULT, as_list, link_name, load_config, parse_day, parse_when,  # noqa: E402
                      read_note, replace_block, slug, write_note)

# ----------------------------------------------------------------------------- setup
CFG = load_config()
P = {k: VAULT / v for k, v in {
    "inbox": "00_Inbox/Review.md", "hubs": "10_Hubs", "beliefs": "20_Beliefs", "signals": "30_Signals",
    "facts": "40_Facts", "hyp": "50_Hypotheses", "events": "60_Events", "reuse": "_system/Reuse guard.md",
    "state": "_system/state.json", "changelog": "_system/changelog"}.items()}
PRIORITY = {"revise": 0, "new-explicit": 1, "new": 2, "edit": 3, "status": 4, "fading": 4,
            "archive": 5, "revive": 6, "resurface": 7}


class Run:
    """Collects every intended write so --dry-run can show it without touching disk."""

    def __init__(self, now, dry):
        self.now, self.today, self.dry = now, now.date(), dry
        self.writes = {}          # path -> text
        self.log = defaultdict(list)

    def write(self, path, fm, body):
        from vaultlib import dump_note
        self.writes[Path(path)] = dump_note(fm, body)

    def write_text(self, path, text):
        self.writes[Path(path)] = text

    def move(self, src, dst):
        self.log["_moves"].append((Path(src), Path(dst)))

    def flush(self):
        if self.dry:
            return
        for src, dst in self.log["_moves"]:
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dst)
        for path, text in self.writes.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")


def days(a, b):
    return (a - b).total_seconds() / 86400 if isinstance(a, dt.datetime) else (a - b).days


# ----------------------------------------------------------------------------- load
def load_state():
    if P["state"].exists():
        return json.loads(P["state"].read_text())
    return {"last_run": None, "next_q": 1, "open": {}, "processed_events": [], "decided": []}


def extract(body, label):
    """Pull '**Bot did:** x' line or the '> ' quote block after '**He said (verbatim):**'."""
    if label == "said":
        m = re.search(r"\*\*He said \(verbatim\):\*\*\s*\n((?:>.*\n?)+)", body)
        return "\n".join(l[1:].lstrip() for l in m.group(1).splitlines()) if m else ""
    m = re.search(r"\*\*Bot did:\*\*\s*(.*)", body)
    return m.group(1).strip() if m else ""


def load_signals(run, include_examples):
    sigs, skipped = [], defaultdict(list)
    for path in sorted(P["signals"].rglob("*.md")):
        fm, body = read_note(path)
        if fm is None or fm.get("class") != "signal":
            skipped["malformed"].append(path.name)
            continue
        if fm.get("example") and not include_examples:
            skipped["example"].append(path.stem)
            continue
        when = parse_when(fm.get("date"))
        if when is None or when > run.now:
            skipped["bad or future date"].append(path.stem)
            continue
        pol = {"-": "-", "+": "+", "neg": "-", "pos": "+"}.get(str(fm.get("polarity", "")).strip())
        if pol is None:
            skipped["bad polarity"].append(path.stem)
            continue
        heat = int(fm.get("heat") or 0)
        age_h = (run.now - when).total_seconds() / 3600
        cooling = heat >= CFG["cooling_min_heat"] and age_h < CFG["cooling_hours"]
        bot = slug(fm.get("bot"))
        sigs.append({
            "name": path.stem, "path": path, "when": when, "day": when.date(), "bot": bot,
            "segment": fm.get("segment") or "", "session": str(fm.get("session") or f"{bot}:{when.date()}"),
            "type": slug(fm.get("type")), "topic": slug(fm.get("topic")) or slug(fm.get("type")),
            "pol": pol, "heat": heat, "explicit": bool(fm.get("explicit")), "cooling": cooling,
            "w": CFG["cooling_weight"] if cooling else 1.0,
            "supports": {link_name(x) for x in as_list(fm.get("supports")) if link_name(x)},
            "contradicts": {link_name(x) for x in as_list(fm.get("contradicts")) if link_name(x)},
            "said": extract(body, "said"), "did": extract(body, "did"),
        })
    return sigs, skipped


def load_dir(folder, cls):
    out = {}
    for path in sorted(folder.glob("*.md")):
        fm, body = read_note(path)
        if fm and fm.get("class") == cls:
            out[path.stem] = {"path": path, "fm": fm, "body": body, "name": path.stem}
    return out


# ----------------------------------------------------------------------------- LLM HOOKS
# ==== LLM HOOK 1: clustering =================================================
# v0 groups unlinked signals by their `topic` tag. To add semantic clustering,
# return {cluster_key: [signal, ...]} here (e.g. embed `said` + `did`, cluster,
# name each cluster with a kebab topic). Returning None keeps topic grouping.
def llm_cluster(unlinked_signals):
    return None


# ==== LLM HOOK 2: claim drafting =============================================
# Given a topic and its signals, return a short first-person claim, e.g.
# "Don't over-anchor on one message." Must not quote him. None = leave blank
# for the hub owner bot to fill.
def llm_draft_claim(topic, signals):
    return None


# ==== LLM HOOK 3: hub sense-of-self ==========================================
# Given a hub's approved beliefs, return ~150 words of prose that keeps the
# tensions visible. None = use the deterministic list summary.
def llm_hub_summary(segment, beliefs):
    return None


# ----------------------------------------------------------------------------- scoring
def half_life(segs, pinned):
    if pinned:
        return float("inf")
    hl = [CFG["half_life_days"].get(s, 60) for s in segs] or [60]
    return max(hl)


def decay(age_days, hl):
    return 1.0 if hl == float("inf") else 0.5 ** (max(age_days, 0) / hl)


def score(b, sigs, run):
    fm = b["fm"]
    name, topics = b["name"], set(as_list(fm.get("topics")))
    pinned = bool(fm.get("pinned"))
    hl = half_life(as_list(fm.get("segments")), pinned)
    first = parse_day(fm.get("first_seen")) or run.today
    anchor = max(first, parse_day(fm.get("reconfirmed_on")) or first)
    prior = CFG["priors"].get(fm.get("source", "signals"), CFG["priors"]["signals"])
    val = prior * decay(days(run.today, anchor), hl)
    sup = [s for s in sigs if name not in s["contradicts"] and (name in s["supports"] or (s["topic"] in topics and not s["supports"] and not s["contradicts"]))]
    answered = parse_day(fm.get("reconfirmed_on")) or dt.date.min   # he said "still accurate" after these
    con_all = [s for s in sigs if name in s["contradicts"]]
    con = [s for s in con_all if s["day"] > answered]
    for s in sup:
        val += CFG["support_step"] * s["w"] * (CFG["explicit_multiplier"] if s["explicit"] else 1) * decay(days(run.now, s["when"]), hl)
    for s in con:
        val -= CFG["contra_step"] * s["w"] * (CFG["explicit_multiplier"] if s["explicit"] else 1) * decay(days(run.now, s["when"]), hl)
    if pinned:
        val = max(val, prior)
    last = max([first] + [s["day"] for s in sup])
    return round(min(1.0, max(0.0, val)), 2), sup, con, con_all, last


# ----------------------------------------------------------------------------- inbox decisions
DECISION_RE = re.compile(r"^- \[[xX]\] (yes|not now|no)\s*$", re.M)


def read_decisions():
    if not P["inbox"].exists():
        return {}
    text = P["inbox"].read_text(encoding="utf-8")
    out = {}
    for block in re.split(r"(?m)^### ", text)[1:]:
        qid = block.split()[0]
        picks = DECISION_RE.findall(block)
        if len(picks) == 1:
            out[qid] = picks[0]
        elif len(picks) > 1:
            out[qid] = "conflict"
    return out


def apply_decisions(run, state, beliefs, props):
    later = (run.today + dt.timedelta(days=CFG["resurface_days"])).isoformat()
    for qid, choice in read_decisions().items():
        item = state["open"].get(qid)
        if not item:
            continue
        if choice == "conflict":
            run.log["decisions"].append(f"{qid}: more than one box ticked, so it was left open")
            continue
        kind, target = item["kind"], item["target"]
        if kind in ("new", "edit"):
            pr = props.get(target)
            if not pr:
                run.log["decisions"].append(f"{qid}: proposal {target} not found, so it was dropped")
            elif choice == "yes":
                promote(run, pr, beliefs) if kind == "new" else apply_edit(run, pr, beliefs)
            else:
                pr["fm"]["status"] = "parked"
                pr["fm"]["parked_on"] = run.today.isoformat()
                pr["fm"]["parked_mode"] = "date" if choice == "not now" else "evidence"
                pr["fm"]["resurface_on"] = later if choice == "not now" else ""
                pr["fm"]["parked_signal_count"] = item.get("evidence", 0)
                pr["dirty"] = True
        else:  # questions about an existing belief: is it still accurate?
            b = beliefs.get(target)
            if not b:
                continue
            fm = b["fm"]
            if choice == "yes":
                fm["status"] = "approved"
                fm["reconfirmed_on"] = run.today.isoformat()
                fm["needs_reconfirm"] = False
                fm.pop("fading_since", None)
            elif choice == "no":
                fm["status"] = "archived"
                fm["archived_on"] = run.today.isoformat()
                fm["needs_reconfirm"] = False
            else:
                fm["ask_again_on"] = later
            b["dirty"] = True
        state["open"].pop(qid)
        state["decided"] = ([{"q": qid, "kind": kind, "target": target, "choice": choice,
                              "date": run.today.isoformat()}] + state["decided"])[:20]
        run.log["decisions"].append(f"{qid} {kind} '{target}' → {choice}")


def promote(run, pr, beliefs):
    fm = pr["fm"]
    title = (fm.get("claim") or fm.get("topics", ["untitled"])[0].replace("-", " ").capitalize()).strip()
    title = re.sub(r'[\\/:*?"<>|#^\[\]]', "", title)[:90]
    n = 1 + max([int(str(b["fm"].get("id", "B-0"))[2:] or 0) for b in beliefs.values()] + [0])
    nfm = {"class": "belief", "id": f"B-{n:03d}", "status": "approved", "strength": CFG["priors"]["signals"],
           "signal_count": 0, "contra_count": 0, "first_seen": fm.get("first_evidence") or run.today.isoformat(),
           "last_seen": run.today.isoformat(), "pinned": False, "segments": as_list(fm.get("segments")),
           "topics": as_list(fm.get("topics")), "applies_when": fm.get("applies_when", ""),
           "not_when": fm.get("not_when", ""), "tensions": as_list(fm.get("tensions")),
           "source": "signals",
           "source_ref": f"approved by owner {run.today} from [[{pr['name']}]]"
                         + (" (explicit always/never statement)" if fm.get("explicit") else ""), "needs_reconfirm": False}
    dst = P["beliefs"] / f"{title}.md"
    body = re.sub(r"<!-- distill:evidence:start -->.*?<!-- distill:evidence:end -->", "", pr["body"], flags=re.S)
    body = re.sub(r"(?m)^\*\*Claim:\*\*.*$", f"**In practice:** {fm.get('claim') or '_(write what this means in practice)_'}", body)
    body = re.sub(r"(?m)^_Quarantined:.*$\n?", "", body).rstrip() + "\n"
    run.write(dst, nfm, body)
    beliefs[title] = {"path": dst, "fm": nfm, "body": body, "name": title, "dirty": True}
    pr["fm"]["status"] = "approved"
    pr["fm"]["became"] = f"[[{title}]]"
    pr["dirty"] = True
    run.log["status"].append(f"NEW BELIEF [[{title}]] (approved by owner)")


def apply_edit(run, pr, beliefs):
    fm = pr["fm"]
    b = beliefs.get(link_name(fm.get("target")))
    if not b:
        run.log["decisions"].append(f"edit target {fm.get('target')} missing")
        return
    field, value = fm.get("field"), fm.get("value")
    if field in ("tensions", "segments", "topics"):
        value = [v.strip() for v in str(value).split(",") if v.strip()]
        if field == "tensions":
            value = [f"[[{link_name(v)}]]" for v in value]
    old = b["fm"].get(field)
    b["fm"][field] = value
    b["dirty"] = True
    pr["fm"]["status"] = "approved"
    pr["dirty"] = True
    run.log["status"].append(f"EDIT [[{b['name']}]] {field}: {old!r} → {value!r} (approved by owner)")


# ----------------------------------------------------------------------------- pivots
def process_events(run, state, beliefs):
    bump = False
    for name, ev in load_dir(P["events"], "event").items():
        fm = ev["fm"]
        if fm.get("kind") != "pivot":
            continue
        when = parse_day(fm.get("date")) or run.today
        until = parse_day(fm.get("threshold_bump_until")) or when + dt.timedelta(days=CFG["pivot_bump_days"])
        if when <= run.today <= until:
            bump = True
        if name in state["processed_events"]:
            continue
        segs = set(as_list(fm.get("segments")))
        targets = [link_name(x) for x in as_list(fm.get("affects"))] or [
            n for n, b in beliefs.items() if b["fm"].get("status") in ("approved", "fading")
            and (not segs or "core" in segs or segs & set(as_list(b["fm"].get("segments"))))]
        for t in targets:
            if t in beliefs:
                beliefs[t]["fm"]["needs_reconfirm"] = True
                beliefs[t]["dirty"] = True
                open_item(run, state, "reconfirm", t, f"Pivot [[{name}]]: is this still accurate after the change?", 0)
        state["processed_events"].append(name)
        run.log["events"].append(f"pivot [[{name}]] flagged {len(targets)} belief(s) for reconfirmation")
    return bump


# ----------------------------------------------------------------------------- inbox items
def open_item(run, state, kind, target, why, evidence, quotes=()):
    if any(i["kind"] == kind and i["target"] == target for i in state["open"].values()):
        return None
    qid = f"Q-{state['next_q']:04d}"
    state["next_q"] += 1
    state["open"][qid] = {"kind": kind, "target": target, "why": why, "evidence": evidence,
                          "quotes": list(quotes)[:3], "created": run.today.isoformat()}
    return qid


def quote_list(sigs):
    return [f"\"{s['said'][:160]}\" ({s['bot']}, {s['day']:%m-%d})" for s in sorted(sigs, key=lambda s: s["when"])[-3:]]


# ----------------------------------------------------------------------------- main pass
def distill(run, include_examples):
    state = load_state()
    sigs, skipped = load_signals(run, include_examples)
    beliefs = load_dir(P["beliefs"], "belief")
    props = load_dir(P["hyp"], "proposal")
    new_since = [s for s in sigs if not state["last_run"] or s["when"] > parse_when(state["last_run"])]

    apply_decisions(run, state, beliefs, props)
    bump = process_events(run, state, beliefs)
    candidates = []   # (priority, -weight, kind, target, payload)

    # --- score beliefs
    for name, b in beliefs.items():
        fm = b["fm"]
        st = fm.get("status")
        strength, sup, con, con_all, last = score(b, sigs, run)
        changes = {"strength": strength, "signal_count": len(sup), "contra_count": len(con_all), "last_seen": last.isoformat()}
        diffs = {k: (fm.get(k), v) for k, v in changes.items() if str(fm.get(k)) != str(v)}
        if diffs:
            fm.update(changes)
            b["dirty"] = True
            run.log["numbers"].append(f"[[{name}]] " + ", ".join(f"{k} {o}→{n}" for k, (o, n) in diffs.items()))
        ev = "\n".join(f"- [[{s['name']}]] {s['day']} · {s['bot']} · {s['pol']}{' (cooling)' if s['cooling'] else ''} · “{s['said'][:90]}”"
                       for s in sorted(sup + con_all, key=lambda s: s["when"]))
        ev = ("**Evidence** (regenerated by distill.py)\n" + ev) if ev else "_No signals yet._"
        nb = replace_block(b["body"], "distill:evidence", ev)
        if nb != b["body"]:
            b["body"], b["dirty"] = nb, True
        b["strength"] = strength
        asked_later = parse_day(fm.get("ask_again_on"))
        if asked_later and asked_later > run.today:
            continue
        pinned, core = bool(fm.get("pinned")), "core" in as_list(fm.get("segments"))
        since = parse_day(fm.get("reconfirmed_on")) or dt.date.min
        recent_con = [s for s in con if days(run.today, s["day"]) <= CFG["contradiction_window_days"] and s["day"] > since]
        cw = sum(s["w"] for s in recent_con)
        if st in ("approved", "fading") and (cw >= CFG["contradiction_flag_weight"] or any(s["explicit"] and not s["cooling"] for s in recent_con)):
            candidates.append((PRIORITY["revise"], -cw, "revise", name,
                               {"why": f"{len(recent_con)} pushback(s) against this belief in {CFG['contradiction_window_days']}d. Still accurate?",
                                "quotes": quote_list(recent_con), "evidence": len(recent_con)}))
        if st == "approved" and not pinned and strength < CFG["fading_below"]:
            if core:
                candidates.append((PRIORITY["fading"], strength, "fading", name,
                                   {"why": f"Core belief faded to {strength} with no recent reinforcement. Still accurate?", "evidence": len(sup)}))
            else:
                candidates.append((PRIORITY["status"], strength, "status", name, {"to": "fading"}))
        elif st == "fading":
            if strength >= CFG["revive_above"]:
                candidates.append((PRIORITY["status"], -strength, "status", name, {"to": "approved"}))
            elif days(run.today, parse_day(fm.get("fading_since")) or run.today) >= CFG["archive_after_fading_days"]:
                candidates.append((PRIORITY["archive"], strength, "archive", name,
                                   {"why": f"Fading for {CFG['archive_after_fading_days']}+ days (strength {strength}). Still accurate? 'no' archives it (kept, revivable).", "evidence": len(sup)}))
        elif st == "archived":
            gone = parse_day(fm.get("archived_on")) or dt.date.min
            fresh = [s for s in sup if s["day"] > gone]
            if fresh:
                candidates.append((PRIORITY["revive"], -len(fresh), "revive", name,
                                   {"why": f"{len(fresh)} new signal(s) since it was archived. Accurate again?", "quotes": quote_list(fresh), "evidence": len(fresh)}))

    # --- unlinked signals -> patterns
    claimed = {t: n for n, b in beliefs.items() for t in as_list(b["fm"].get("topics"))}
    ptopic = {t: n for n, p in props.items() for t in as_list(p["fm"].get("topics"))}
    known = set(beliefs) | set(props)
    unlinked = [s for s in sigs if not ((s["supports"] | s["contradicts"]) & known) and s["topic"] not in claimed]
    groups = llm_cluster(unlinked)
    if groups is None:
        groups = defaultdict(list)
        for s in unlinked:
            groups[s["topic"] or "untagged"].append(s)
    threshold = CFG["pattern_min_weight"] + (1 if bump else 0)
    hyps, hints, holds = [], [], []
    for topic, g in sorted(groups.items()):
        W = round(sum(s["w"] for s in g), 2)
        bots, dayset = {s["bot"] for s in g}, {s["day"] for s in g}
        share = max(sum(s["w"] for s in g if s["session"] == ss) for ss in {s["session"] for s in g}) / W if W else 0
        meta = f"{len(g)} signal(s), weight {W}, {len(bots)} bot(s), {len(dayset)} day(s), +{sum(s['pol'] == '+' for s in g)}/-{sum(s['pol'] == '-' for s in g)}"
        if topic in ptopic:     # already a proposal: maybe resurface
            pr = props[ptopic[topic]]
            pfm = pr["fm"]
            pr["group"] = g
            if pfm.get("status") == "parked":
                due = parse_day(pfm.get("resurface_on"))
                newer = [s for s in g if s["day"] > (parse_day(pfm.get("parked_on")) or dt.date.min)]
                if (pfm.get("parked_mode") == "date" and due and due <= run.today) or \
                   (pfm.get("parked_mode") == "evidence" and len(newer) >= CFG["resurface_new_signals"]):
                    candidates.append((PRIORITY["resurface"], -W, "resurface", pr["name"],
                                       {"why": f"Parked {pfm.get('parked_on')}; back because {'its date came up' if pfm.get('parked_mode') == 'date' else f'{len(newer)} new signals arrived'}. {meta}",
                                        "quotes": quote_list(g), "evidence": len(g)}))
            continue
        live = [s for s in g if not s["cooling"]]
        explicit = any(s["explicit"] for s in live)
        variety = len(bots) >= CFG["variety_min"] or len(dayset) >= CFG["variety_min"]
        if topic != "untagged" and explicit:
            candidates.append((PRIORITY["new-explicit"], -W, "new", topic, {"why": f"Explicit always/never statement. {meta}", "group": g, "explicit": True}))
        elif topic != "untagged" and W >= threshold and variety:
            if share > CFG["burst_share"]:
                holds.append(f"`{topic}`: {meta}. Held because {share:.0%} of it came from one session (burst guard)")
            else:
                candidates.append((PRIORITY["new"], -W, "new", topic, {"why": f"Repeated pattern. {meta}", "group": g}))
        elif W >= CFG["hypothesis_min_weight"]:
            hyps.append(f"`{topic}`: {meta}{' (needs variety: more bots or days)' if not variety else ''}{' (pivot bump active)' if bump else ''}")
        else:
            hints.append(f"`{topic}`: {meta}. One-off, so it's a conversation hint only")

    # --- bot-made proposals waiting for review
    in_inbox = {i["target"] for i in state["open"].values()}
    for n, pr in props.items():
        if pr["fm"].get("status") == "proposed" and pr["fm"].get("origin") != "distiller" and n not in in_inbox:
            candidates.append((PRIORITY["edit"] if pr["fm"].get("kind") == "edit" else PRIORITY["new"], 0,
                               pr["fm"].get("kind", "new") + "-bot", n, {"why": f"Proposed by {pr['fm'].get('origin')}: {pr['fm'].get('why', '')}"}))

    # --- change cap
    candidates.sort(key=lambda c: (c[0], c[1]))
    applied, deferred = 0, []
    for prio, _, kind, target, pay in candidates:
        if any(i["target"] in (target, f"P-{target}") and i["kind"] != "reconfirm" for i in state["open"].values()):
            continue  # already waiting on the owner
        if applied >= CFG["change_cap"]:
            deferred.append(f"{kind} → {target}")
            continue
        applied += 1
        if kind == "status":
            b = beliefs[target]
            b["fm"]["status"] = pay["to"]
            if pay["to"] == "fading":
                b["fm"]["fading_since"] = run.today.isoformat()
            else:
                b["fm"].pop("fading_since", None)
            b["dirty"] = True
            run.log["status"].append(f"[[{target}]] → {pay['to']} (strength {b['strength']})")
        elif kind == "new":
            pname = make_proposal(run, props, target, pay)
            open_item(run, state, "new", pname, pay["why"], len(pay["group"]), quote_list(pay["group"]))
            run.log["proposals"].append(f"[[{pname}]]: {pay['why']}")
        elif kind in ("new-bot", "edit-bot"):
            open_item(run, state, kind[:-4], target, pay["why"], 0)
            run.log["proposals"].append(f"[[{target}]]: {pay['why']}")
        elif kind == "resurface":
            props[target]["fm"]["status"] = "proposed"
            props[target]["dirty"] = True
            open_item(run, state, "new", target, pay["why"], pay["evidence"], pay["quotes"])
            run.log["proposals"].append(f"[[{target}]] resurfaced: {pay['why']}")
        else:  # revise / fading / archive / revive: questions
            open_item(run, state, kind, target, pay["why"], pay.get("evidence", 0), pay.get("quotes", []))
            run.log["questions"].append(f"{kind} [[{target}]]: {pay['why']}")
    run.log["deferred"] = deferred

    # --- refresh evidence on open distiller proposals
    for n, pr in props.items():
        if "group" in pr and pr["fm"].get("status") in ("proposed", "parked"):
            nb = replace_block(pr["body"], "distill:evidence", proposal_evidence(pr["group"]))
            if nb != pr["body"]:
                pr["body"], pr["dirty"] = nb, True

    # --- write everything
    for coll in (beliefs, props):
        for x in coll.values():
            if x.get("dirty"):
                run.write(x["path"], x["fm"], x["body"])
    write_hubs(run, beliefs, sigs)
    write_inbox(run, state, beliefs, props)
    write_hypotheses(run, hyps, holds, deferred, props, bump)
    cooling = write_reuse(run)
    lint = lint_facts()
    state["last_run"] = run.now.isoformat(timespec="minutes")
    if not run.dry:
        run.write_text(P["state"], json.dumps(state, indent=2, default=str))
    report = build_report(run, sigs, skipped, new_since, hints, hyps, holds, cooling, lint, applied)
    if not run.dry:
        cl = P["changelog"] / f"{run.today}.md"
        prev = cl.read_text() if cl.exists() else f"---\nclass: changelog\ndate: \"{run.today}\"\n---\n"
        run.write_text(cl, prev.rstrip() + "\n\n" + report + "\n")
    run.flush()
    return report


def proposal_evidence(g):
    return "**Evidence** (regenerated by distill.py)\n" + "\n".join(
        f"- [[{s['name']}]] {s['day']} · {s['bot']} · {s['pol']} · heat {s['heat']}\n  > {s['said'][:200]}" for s in sorted(g, key=lambda s: s["when"]))


def make_proposal(run, props, topic, pay):
    g = pay["group"]
    pname = f"P-{topic}"
    claim = llm_draft_claim(topic, g) or ""
    segs = sorted({s["segment"] for s in g if s["segment"]}) or ["core"]
    fm = {"class": "proposal", "id": pname, "kind": "new", "status": "proposed", "origin": "distiller",
          "proposed_on": run.today.isoformat(), "claim": claim, "segments": segs, "topics": [topic],
          "applies_when": "", "not_when": "", "tensions": [], "explicit": bool(pay.get("explicit")),
          "first_evidence": min(s["day"] for s in g).isoformat(), "why": pay["why"]}
    note = " Signals span more than one segment, so consider Core." if len(segs) > 1 else ""
    body = (f"**Claim:** _(empty. The hub owner bot writes one short claim in frontmatter `claim`)_\n\n"
            f"**Example:** \n\n**Counterexample:** \n\n_Quarantined: agents don't read this until the owner says yes.{note}_\n\n"
            + "<!-- distill:evidence:start -->\n" + proposal_evidence(g) + "\n<!-- distill:evidence:end -->\n")
    path = P["hyp"] / f"{pname}.md"
    run.write(path, fm, body)
    props[pname] = {"path": path, "fm": fm, "body": body, "name": pname, "group": g}
    return pname


# ----------------------------------------------------------------------------- generated notes
def write_hubs(run, beliefs, sigs):
    for name, hub in load_dir(P["hubs"], "hub").items():
        seg, cap = hub["fm"].get("segment"), int(hub["fm"].get("cap") or CFG["hub_cap"])
        members = sorted([b for b in beliefs.values() if seg in as_list(b["fm"].get("segments"))
                          and b["fm"].get("status") in ("approved", "fading")], key=lambda b: -b["fm"].get("strength", 0))
        shown, over = members[:cap], members[cap:]
        bots = set(as_list(hub["fm"].get("bots")))
        recent = [s for s in sigs if days(run.now, s["when"]) <= 30 and ("all" in bots or s["segment"] == seg or s["bot"] in bots)]
        lines = [f"_Regenerated {run.now:%Y-%m-%d %H:%M} PT by distill.py · {len(shown)}/{cap} beliefs · last 30d: "
                 f"{sum(s['pol'] == '-' for s in recent)} pushbacks, {sum(s['pol'] == '+' for s in recent)} landed_", ""]
        prose = llm_hub_summary(seg, shown)
        if prose:
            lines += [prose, ""]
        lines.append("**Beliefs** (strongest first; apply them, don't quote them)")
        for b in shown:
            f = b["fm"]
            tag = " · ⚠ fading" if f.get("status") == "fading" else ""
            tag += " · ⚠ needs reconfirm" if f.get("needs_reconfirm") else ""
            tag += " · 📌" if f.get("pinned") else ""
            scope = "; ".join(x for x in [f"when: {f['applies_when']}" if f.get("applies_when") else "",
                                          f"not when: {f['not_when']}" if f.get("not_when") else ""] if x)
            lines.append(f"- [[{b['name']}]] · {f.get('strength')}{tag}" + (f"  \n  {scope}" if scope else ""))
        if not shown:
            lines.append("- _none yet_")
        names = {b["name"] for b in shown}
        pairs = sorted({tuple(sorted((b["name"], link_name(t)))) for b in shown for t in as_list(b["fm"].get("tensions"))})
        pairs = [p for p in pairs if p[0] in names or p[1] in names]
        if pairs:
            lines += ["", "**In tension** (both hold. `applies_when` decides which one wins)"]
            lines += [f"- [[{a}]] ↔ [[{c}]]" for a, c in pairs]
        if over:
            lines += ["", f"**Over cap** ({len(over)} weakest not linked; merge or drop them): " + ", ".join(b["name"] for b in over)]
        run.write(hub["path"], hub["fm"], replace_block(hub["body"], "distill", "\n".join(lines)))


def write_inbox(run, state, beliefs, props):
    out = ["---", "class: inbox", "---", "# Review",
           "One question per item: **is this accurate?** It's about accuracy, not whether you like it. Tick one box. "
           "The distiller applies your answer on its next run.",
           "- **yes**: it becomes, or stays, a belief.",
           f"- **not now**: parked, and it comes back in {CFG['resurface_days']} days.",
           "- **no**: parked or archived. It only comes back if new evidence shows up, and nothing is deleted.", ""]
    if not state["open"]:
        out.append("_Nothing to review._")
    labels = {"new": "new belief?", "edit": "edit", "revise": "pushback against a belief", "fading": "core belief fading",
              "archive": "archive?", "revive": "revive?", "reconfirm": "reconfirm after pivot"}
    for qid, it in sorted(state["open"].items()):
        t = it["target"]
        if it["kind"] in ("new", "edit"):
            pfm = props.get(t, {}).get("fm", {})
            stmt = pfm.get("claim") or (f"Edit [[{link_name(pfm.get('target'))}]] · {pfm.get('field')} → {pfm.get('value')}" if it["kind"] == "edit"
                                        else f"(claim not written yet. Judge from the quotes) topic `{', '.join(as_list(pfm.get('topics')))}`")
            ref = f"[[{t}]]"
        else:
            stmt, ref = t, f"[[{t}]] (strength {beliefs.get(t, {}).get('fm', {}).get('strength', '?')})"
        out += [f"### {qid} · {labels.get(it['kind'], it['kind'])}", f"**Statement:** {stmt}  ", f"{ref} · {it['why']}"]
        out += [f"> {q}" for q in it.get("quotes", [])]
        out += ["- [ ] yes", "- [ ] not now", "- [ ] no", ""]
    if state["decided"]:
        out += ["## Recently decided"] + [f"- {d['date']} {d['q']} {d['kind']} `{d['target']}` → **{d['choice']}**" for d in state["decided"][:10]]
    run.write_text(P["inbox"], "\n".join(out) + "\n")


def write_hypotheses(run, hyps, holds, deferred, props, bump):
    parked = [f"- [[{n}]] · {p['fm'].get('parked_mode')} · back on {p['fm'].get('resurface_on') or 'new evidence'}"
              for n, p in props.items() if p["fm"].get("status") == "parked"]
    sec = lambda title, xs: [f"## {title}"] + ([f"- {x}" if not x.startswith("- ") else x for x in xs] or ["- _none_"]) + [""]
    out = ["---", "class: hypotheses", "---", "# Hypotheses (quarantine)",
           "**Agents: don't read this as truth.** These are weak patterns the distiller noticed. They only count once they turn into Inbox items and the owner says yes.",
           f"_Regenerated {run.now:%Y-%m-%d %H:%M} PT{' · pivot bump active: patterns need +1 weight' if bump else ''}_", ""]
    out += sec("Weak patterns", hyps) + sec("Held by burst guard", holds) + sec("Deferred by change cap (retried next run)", deferred)
    out += sec("Parked proposals", parked)
    out += ["## LLM hook", "_v0 groups signals by `topic` tag only. Semantic clustering and claim drafting plug in at `llm_cluster` and `llm_draft_claim` in `_system/distill.py`._"]
    run.write_text(P["hyp"] / "Hypotheses.md", "\n".join(out) + "\n")


USE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) \| ([^|]+?) \| (phrase|belief): (.+?)\s*$", re.M)


def write_reuse(run):
    path = P["reuse"]
    if not path.exists():
        return []
    fm, body = read_note(path)
    rc = CFG["reuse"]
    per_bot, total, last = defaultdict(int), defaultdict(int), {}
    for d, bot, kind, val in USE_RE.findall(body.split("## Log", 1)[-1]):
        day = parse_day(d)
        if not day or days(run.today, day) > rc["window_days"]:
            continue
        key = (kind, link_name(val).strip('"').lower() if kind == "belief" else val.strip().strip('"').lower())
        per_bot[(key, bot.strip())] += 1
        total[key] += 1
        last[key] = max(last.get(key, day), day)
    hot = {k for (k, b), n in per_bot.items() if n > rc["per_bot_max"]} | {k for k, n in total.items() if n > rc["all_bots_max"]}
    hot = {k for k in hot if k[0] == "phrase"}   # beliefs are meant to be applied; phrases are what wear out
    cooling = [f'- "{k[1]}": used {total[k]}× in {rc["window_days"]}d. Don\'t use it until {last[k] + dt.timedelta(days=rc["cool_days"])}' for k in sorted(hot)]
    top = sorted(((n, k) for k, n in total.items() if k[0] == "belief"), reverse=True)[:5]
    block = [f"_Regenerated {run.now:%Y-%m-%d %H:%M} PT_", "", "**Cooling**"] + (cooling or ["- _nothing cooling_"])
    if top:
        block += ["", f"**Most-applied beliefs ({rc['window_days']}d)**"] + [f"- [[{k[1]}]] ×{n}" for n, k in top]
    run.write(path, fm or {"class": "system"}, replace_block(body, "distill", "\n".join(block)))
    return cooling


def lint_facts():
    issues, keys = [], defaultdict(list)
    for name, f in load_dir(P["facts"], "fact").items():
        fm = f["fm"]
        missing = [k for k in ("as_of", "source", "owner") if not fm.get(k)]
        if missing:
            issues.append(f"[[{name}]] missing {', '.join(missing)}")
        if fm.get("status") == "current" and fm.get("key"):
            keys[fm["key"]].append(name)
    issues += [f"two current facts share key `{k}`: {', '.join(v)}" for k, v in keys.items() if len(v) > 1]
    return issues


def build_report(run, sigs, skipped, new_since, hints, hyps, holds, cooling, lint, applied):
    L = [f"## Run {run.now:%Y-%m-%d %H:%M} PT{' (DRY RUN, nothing written)' if run.dry else ''}",
         f"- Signals counted: {len(sigs)} ({len(new_since)} new since last run, {sum(s['cooling'] for s in sigs)} still cooling)"]
    for why, xs in skipped.items():
        L.append(f"- Skipped ({why}): {len(xs)} → {', '.join(xs[:6])}")
    L.append(f"- Belief changes used: {applied}/{CFG['change_cap']}")
    for title, key in [("Your decisions applied", "decisions"), ("Pivot events", "events"), ("Status changes", "status"),
                       ("New Inbox proposals", "proposals"), ("New Inbox questions", "questions"),
                       ("Deferred by cap", "deferred"), ("Bookkeeping (strength / counts)", "numbers")]:
        if run.log.get(key):
            L += [f"\n**{title}**"] + [f"- {x}" for x in run.log[key]]
    if hyps or holds:
        L += ["\n**Hypotheses (quarantined)**"] + [f"- {x}" for x in hyps + holds]
    if hints:
        L += ["\n**One-off hints (no action)**"] + [f"- {x}" for x in hints]
    if cooling:
        L += ["\n**Reuse guard cooling**"] + cooling
    if lint:
        L += ["\n**Fact lint**"] + [f"- {x}" for x in lint]
    if run.dry:
        changed = [p for p, t in run.writes.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        L += ["\n**Would write (changed files)**"] + ([f"- {p.relative_to(VAULT)}" for p in changed] or ["- _nothing_"])
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now", help="override current time, e.g. 2026-10-09T23:00")
    ap.add_argument("--include-examples", action="store_true")
    a = ap.parse_args()
    now = parse_when(a.now) if a.now else dt.datetime.now().replace(second=0, microsecond=0)
    print(distill(Run(now, a.dry_run), a.include_examples))


if __name__ == "__main__":
    main()
