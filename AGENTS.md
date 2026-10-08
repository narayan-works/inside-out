# AGENTS.md: read/write protocol for any bot

Run every command from the vault root (the folder that holds this file). Follow these rules exactly.

> The segments and bot names below are examples for a fictional owner. Replace them with your own; valid segments are the keys of `half_life_days` in `_system/config.yaml`.

## Segments
| Segment | Hub | Bots | Owner |
|---|---|---|---|
| core | `10_Hubs/Core.md` | everyone | context-keeper |
| studio | `10_Hubs/studio.md` | architect, writer, ideation, designer | architect |
| career | `10_Hubs/career.md` | context-keeper, job-scout, cover-letter, applier | context-keeper |
| experiments | `10_Hubs/experiments.md` | notifier | owner |

## Before every reply (READ)
1. Read `10_Hubs/Core.md` and your segment hub, focusing on the block between `distill:start` and `distill:end`.
2. Open each belief linked there. That's one hop only, so don't follow links out of belief notes.
3. Read the **Cooling** list in `_system/Reuse guard.md`.
4. If you need biographical facts, read `40_Facts/`. Use only facts with `status: current`, and cite the `source` when it matters. If a fact is missing or disputed, ask the facts owner (here `context-keeper`). Don't guess.
5. Check your draft against those beliefs, paying attention to `applies_when`, `not_when` and `tensions`. Fix the draft before you send it.
6. **Apply beliefs. Don't quote them back to the owner,** and don't reuse a phrase that's on the cooling list.

Never read as truth: `50_Hypotheses/`, `00_Inbox/`, `70_Private/`, or any note with `class: private`.
Skip any belief whose status is `proposed`, `parked` or `archived`. Treat a `fading` belief as a weak hint.

## When the owner pushes back, or something clearly lands (WRITE a signal)
Log it in the same turn, one signal per exchange:
```bash
python3 _system/mind.py signal \
  --bot <you> --segment <core|studio|career|experiments> \
  --polarity - --heat 1 --type <too-generic|voice-remixed|wrong-fact|over-anchoring|misread-intent|too-long|landed|...> \
  --topic <short-kebab-topic> --did "<one line: what you did>" \
  --said "<the owner's reply, VERBATIM, typos included>" \
  [--supports "<Belief title>"] [--contradicts "<Belief title>"] [--explicit] [--session <thread id>]
```
- `--said` must be the owner's exact words. Never paraphrase, fix or trim them.
- **polarity** is `-` for a pushback and `+` when something landed (the owner used it unchanged, or said "yes, that").
- **heat** runs 0–3. Use 0 for a calm note, 1 for a clear correction, 2 for frustration, 3 for anger or all-caps.
- **supports** names a belief your output violated (the owner pushed back) or followed (it landed). **contradicts** names a belief you applied that the owner pushed back on.
- If no belief fits, leave both empty and pick a stable `--topic`. Reuse an existing topic if one fits: `rg '^topic:' 30_Signals`.
- Add `--explicit` only when the owner states a rule outright ("always…", "never…", "don't ever…").
- Signals are append-only. Never edit or delete one.

## After you send (reuse guard)
If you used a signature proof point or phrase, log it:
`python3 _system/mind.py used --bot <you> --phrase "<short phrase>"`

## Changing beliefs (PROPOSE, never edit)
- Never edit `20_Beliefs/`, `10_Hubs/` or `00_Inbox/Review.md` directly.
- To propose a new belief:
  `python3 _system/mind.py propose --bot <you> --claim "<short claim>" --segments <seg> --why "<evidence>" [--signals S-...]`
- To propose an edit:
  `python3 _system/mind.py propose --bot <you> --edit "<Belief title>" --field applies_when|not_when|tensions|segments --value "..." --why "..."`
- The distiller puts proposals in the Inbox. The owner decides.

## Hub owners only
- After a nightly run, if a proposal in `50_Hypotheses/` in your segment has an empty `claim`, write a short claim in its frontmatter. Use plain language about how the owner thinks, and add one example and one counterexample. This is the only belief-like text a bot writes.
- The facts owner (here `context-keeper`) owns `40_Facts/`. Every fact needs `as_of`, `source` and `owner`. To replace a fact, set the old one's `status: superseded` and give the new one `supersedes: "[[old]]"`.

## Pivots
When the owner says their direction changed, write a note in `60_Events/` from `_templates/Pivot event.md`. The distiller will flag the affected beliefs for reconfirmation and raise the bar for new patterns for 14 days.
