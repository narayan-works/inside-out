# inside-out

A self-learning memory for a personal fleet of AI agents.

If you use several assistants (one for writing, one for research, one for job applications, and so on), each one forgets what you told the others. You end up correcting the same things again and again, and the output stays generic. This repo is a small, file-based memory they all share. It learns from your reactions slowly and only changes with your approval, so it doesn't swing on a single message.

It's an Obsidian vault plus two Python scripts. Everything is plain Markdown with YAML frontmatter.

> **All personal content here is example data** about a fictional person, Sam Example. Replace it with your own.

## The idea, borrowed from Pixar's *Inside Out*

| In the films | In this vault |
|---|---|
| Memory orbs, one per experience | **Signals**: one note per pushback or per thing that landed, words kept verbatim (`30_Signals/`) |
| Nightly trip to long-term memory | **Distiller**: `_system/distill.py`, run once a night |
| Core memories | **Beliefs**: short notes about how you think and want to be worked with (`20_Beliefs/`) |
| Islands of personality | **Segment hubs**: one per group of bots, linking the beliefs that apply to it (`10_Hubs/`) |
| Facts and opinions crates | Facts (`40_Facts/`) kept separate from beliefs |
| Dream Productions | Hypotheses, quarantined, never read as truth (`50_Hypotheses/`) |
| Vault of Secrets | `70_Private/`, which agents skip by default |

`docs/` has the full research write-up behind the design, including where the analogy breaks.

## The loop
1. **Signal.** When you push back on a bot, or its output lands, the bot logs a signal with `mind.py`.
2. **Distill.** Each night the distiller scores signals, spots patterns repeated across bots or days, lets unused beliefs fade, and writes at most 3 proposed changes to `00_Inbox/Review.md`.
3. **Review.** For each item you answer one question, *is this accurate?*, by ticking **yes / not now / no**.
4. **Read.** Before replying, every bot reads the Core hub plus its own segment hub and the beliefs linked there. `AGENTS.md` is the protocol bots follow.

## Guardrails
- One-off pushbacks stay hints. Only repeated patterns (different bots or days) or explicit "always/never" statements become proposals.
- Heated signals count at reduced weight for the first 24 hours.
- Max 3 belief changes per run. Bots propose; only you approve.
- Nothing is deleted. "Not now" parks a proposal for 21 days; "no" parks it until new evidence appears. Faded beliefs are archived and can come back.
- Beliefs carry `applies_when`, `not_when` and `tensions`, so contradictions stay visible instead of being resolved by force.
- A reuse guard puts overused phrases on a cooling list.
- Strength runs 0–1 and decays with a per-segment half-life unless pinned. All numbers live in `_system/config.yaml`.

## Folder map
| Folder | What's in it | Who writes |
|---|---|---|
| `00_Inbox/Review.md` | Questions waiting for you | distiller (you tick boxes) |
| `10_Hubs/` | Core plus one hub per segment; links to beliefs only | distiller regenerates the summary block |
| `20_Beliefs/` | One note per belief | you; distiller updates numbers and status |
| `30_Signals/YYYY-MM/` | Raw evidence, append-only, one note per signal | any bot, via `mind.py` |
| `40_Facts/` | Sourced biographical facts, one owner bot | facts owner |
| `50_Hypotheses/` | Proposals and weak patterns (quarantine) | distiller and bots |
| `60_Events/` | Pivots that flag beliefs for reconfirmation | you or the facts owner |
| `70_Private/` | Skipped by agents and the distiller | you |
| `_system/` | `distill.py`, `mind.py`, `vaultlib.py`, `config.yaml`, reuse guard, changelog, state | scripts |
| `_templates/` | Obsidian templates for each note type | — |
| `docs/` | Design research | — |

## Run it
Needs Python 3.9+ and PyYAML (`pip install pyyaml`). Run from the vault root.

```bash
python3 _system/distill.py --dry-run                     # show what would change, write nothing
python3 _system/distill.py --dry-run --include-examples  # also count the example signals (shows a pattern forming)
python3 _system/distill.py                               # apply; appends to _system/changelog/<date>.md
```

Bots log through `mind.py`:

```bash
python3 _system/mind.py signal --bot writer --segment studio --polarity - --heat 1 \
  --type too-formal --topic too-formal --did "Drafted a stiff client email" --said "too stiff"
python3 _system/mind.py used --bot writer --phrase "short signature phrase"
python3 _system/mind.py propose --bot writer --claim "Short claim" --segments core --why "evidence"
python3 _system/mind.py --help
```

Schedule the real run nightly (cron, launchd, or your agent platform's scheduler), for example `0 3 * * * cd /path/to/vault && python3 _system/distill.py`.

## Make it yours
1. Delete the example notes (anything with `example: true` or an `[!example]` callout).
2. Set your segments as the keys of `half_life_days` in `_system/config.yaml`, and create one hub per segment from `_templates/Segment hub.md`.
3. Seed a few beliefs you'd state outright (`source: explicit statement`), add sourced facts, and point each bot at `AGENTS.md`.
4. Keep your real vault in a **private** repo. It will hold verbatim quotes and personal facts.

The distiller has stub hooks (`llm_cluster`, `llm_draft_claim`, `llm_hub_summary`) for adding semantic clustering or claim drafting later; v0 groups signals by their `topic` tag.
