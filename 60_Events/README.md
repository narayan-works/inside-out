---
class: index
---
> [!example] Explains the folder. No real events are included.

# Events

A **pivot** is a declared change of direction (the "puberty alarm" from the research doc). When the owner says their direction changed, a bot creates a note here from `_templates/Pivot event.md` with `class: event` and `kind: pivot`. On its next run the distiller:

- flags affected beliefs `needs_reconfirm` and asks about each one in `00_Inbox/Review.md`;
- raises the bar for new patterns by +1 weight for `pivot_bump_days` (14 by default).

Example frontmatter (fictional):

```yaml
class: event
kind: pivot
date: "2026-11-01"
from: "freelance illustration"
to: "full-time product design"
segments: [career]
affects: []          # empty = every approved belief in `segments`
threshold_bump_until: ""
source: "owner, in chat with context-keeper"
```

This README has `class: index`, so the distiller ignores it.
