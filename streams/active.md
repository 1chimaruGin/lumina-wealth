---
status: none
name: null
slug: null
rung: null
started: null
cycle_days: 90
goal: null
weekly_metric: null
revenue_jpy: 0
gate_passed: false
next_actions: []
log: []
---

# Active stream — none

No stream is active. Exactly one may be, by design.

Pick a candidate from `ideas/inbox/` (the weekly digest ranks the top 5 for you)
and activate it:

```bash
python scripts/stream.py activate \
  --name "Postgres performance audits for Japanese startups" \
  --rung 1-skills \
  --goal "¥100,000 in the first 90 days" \
  --metric "outreach conversations per week"
```

Then every day:

```bash
python scripts/stream.py log --action "drafted 3 outreach messages" --minutes 12
python scripts/stream.py log --revenue 15000 --note "first invoice paid"
```

The gate rule, enforced by `scripts/stream.py`, is in the README. Short version:
you cannot start a second stream until this one has earned its first yen with a
routine that held, or has run 90 days and been written off on purpose.
