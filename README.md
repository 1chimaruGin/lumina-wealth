# Lumina Daily

A private briefing system with two jobs: rewire how I think about money, and
find one income stream at a time worth actually building.

Every morning at **11:00 JST** a GitHub Action writes `daily/YYYY-MM-DD.md` and
commits it. On Sunday it writes a weekly digest. A dashboard renders all of it
at a glance.

```
06:00 ──────── 11:00 JST ──────── Sunday 11:30 JST
               daily brief         weekly digest
               ~10 min read        top 5 ideas for the next slot
```

## The brief

Five sections, in this order, every day:

1. **Mind** — one money-psychology piece: summary, key idea, and a reflection
   question aimed at my actual behaviour this week.
2. **Streams** — 2–3 income-stream signals, each scored against the rubric below
   with a one-line verdict.
3. **Principle** — one idea resurfaced from `curriculum/principles.md`, spaced so
   nothing repeats inside three weeks.
4. **Today's action** — one 5–15 minute task for the active stream.
5. **Stream status** — day N of 90, revenue so far, this week's metric.

A section with nothing worth showing says so. Filler would cost the ten minutes
the brief exists to save.

## The rule that matters

**One stream at a time.** Ideas are captured freely into `ideas/inbox/`; nothing
activates itself. `streams/active.md` holds exactly one active stream, and
`scripts/stream.py` refuses to start a second until the current one passes a gate:

| Route | Condition | What it means |
|---|---|---|
| **A** | First revenue **and** a routine that held (14+ days logged, 10+ actions in the last 21) | It works. `graduate` moves it to `streams/running/` and frees the slot. |
| **B** | The 90-day cycle is complete **and** a written kill/pivot decision is filed | It is over. `archive` writes the decision to `streams/archive/` and frees the slot. |

There is no third route. Route A needs both halves on purpose — revenue without a
routine is luck, and a routine without revenue is a hobby.

```bash
python scripts/stream.py status        # what is running, how far in
python scripts/stream.py activate --name "..." --rung 1-skills \
    --goal "¥100,000 in 90 days" --metric "conversations per week"
python scripts/stream.py log --action "messaged 3 CTOs" --minutes 12
python scripts/stream.py log --revenue 15000 --note "first invoice paid"
python scripts/stream.py gate-check    # exit 0 if you may start something new
python scripts/stream.py graduate --reason "..."          # route A
python scripts/stream.py archive --decision kill --reason "..."   # route B
```

`activate` exits `2` and explains itself when the slot is taken. `--force` exists
for retiring a stream early, and prints what it is you are doing before it does it.

## The scoring rubric

Every stream signal is scored 1–10 on six criteria and reduced to one weighted number.

| Criterion | Weight | Question |
|---|---|---|
| Skill fit | 25% | Can my engineering/AI skills deliver this now? |
| Capital needed | 20% | Can it start at ~¥0? |
| Time to first yen | 20% | Could it earn within ~30 days? |
| Proof of demand | 20% | Are people already paying for something similar? |
| Recurring potential | 10% | Could it become monthly income? |
| Time cost | 5% | Does it fit around a full-time job? |

Each one is also tagged with a ladder rung:
`1-skills` (freelance) → `2-productized` (fixed scope) → `3-product` → `4-assets`.

Weights live in `lumina/rubric.py`; the thresholds that decide what reaches the
brief live in `config/settings.yaml` under `select`.

## Running it locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export ANTHROPIC_API_KEY=sk-ant-...      # optional; see "Without a key" below

python scripts/collect.py                # per-source report, writes nothing
python scripts/compose.py --dry-run      # build today's brief to stdout
python scripts/compose.py                # build and write it
python scripts/weekly.py                 # this week's digest
python scripts/backfill.py --days 7      # rebuild the last 7 days
python scripts/site.py --open            # build the dashboard, print a file:// URL
python -m pytest tests/ -q               # 44 tests, no network
```

### Without a key

Everything runs. `--no-llm`, a missing `ANTHROPIC_API_KEY`, a rate limit, or a
blown budget all fall through to the offline scorer: real sources, real
selection, real structure — heuristic scores, and Mind pieces shown as the feed's
own excerpt, **labelled as such rather than passed off as a summary**. The brief
always states which scorer produced it.

To upgrade offline briefs once a key is set:

```bash
python scripts/backfill.py --days 7 --overwrite
```

Rebuilding a date is idempotent: it forgets what that run had marked as seen
first, so you get the same brief back rather than a thinner one made of leftovers.

## Adding a source

Add an entry under `mind:` or `streams:` in `config/sources.yaml`:

```yaml
  - id: my_source           # unique; used in state and logs
    name: My Source         # shown in the brief
    kind: rss               # rss | hn_algolia | reddit_rss | producthunt_rss
    url: https://example.com/feed
    section: streams        # mind | streams
    enabled: true
    backfill: true          # can it return items for a past date?
    auth: none              # none | optional | required
    weight: 1.0             # nudges the pre-filter ranking
    notes: "What you checked, and when."
```

Then `python scripts/collect.py` to confirm it returns items. Before adding one,
check three things: that it is still publishing, that it has an RSS feed or an
official API, and that its terms allow automated access. If they do not, set
`enabled: false` with a `disabled_reason` — a recorded decision is worth more
than a silently missing source.

`backfill: true` is the one that matters for history. Only sources with real
date-range queries can rebuild a past day; everything else can only report
"now", and the backfill says so in its Run notes rather than quietly padding.

### Source status, verified 2026-09-23

| Source | Status |
|---|---|
| Collaborative Fund | ✅ via `feeds.feedburner.com/collabfund` (the site's own `/rss/` 404s) |
| Of Dollars and Data, A Wealth of Common Sense, Farnam Street, Behavioral Scientist | ✅ RSS |
| Hacker News (Show HN / Ask HN) | ✅ Algolia API, no key, **supports date ranges** |
| Reddit (r/SideProject, r/SaaS, r/EntrepreneurRideAlong) | ⚠️ public `.rss` works but covers ~3 hours and rate-limits hard from CI; no backfill |
| Product Hunt | ⚠️ public feed covers ~1 day; `PRODUCTHUNT_TOKEN` would unlock the API and backfill |
| Indie Hackers | ❌ no feed any more, no public API — off, not scraped |
| Starter Story | ❌ no feed, mostly paywalled — off, not scraped |
| Acquire.com | ❌ login-walled, terms forbid automated access — off by design |

A failing source never fails a run. It is skipped, and named at the bottom of the
brief under Run notes.

## The dashboard

`python scripts/site.py` builds `site/index.html` — one self-contained file with
the data inlined, so it works from GitHub Pages, from `file://`, or anywhere else
you drop it. It shows the active stream as a 90-tick cycle rail, the gate's
checklist, the ranked inbox, a 21-day activity strip, which principles have been
resurfaced, and source health. The `Dashboard` workflow deploys it to Pages on
every push that changes content.

`site/` is not committed — it is a build artifact, rebuilt from the repo on deploy.

## Configuration

| File | What it is for |
|---|---|
| `config/settings.yaml` | Schedule, model, budget, selection thresholds, notifier, gate rule |
| `config/sources.yaml` | Every source, with why the disabled ones are disabled |
| `config/profile.yaml` | **Yours to fill in.** Skills, constraints, goals. Pre-filled only with what you stated; every `TODO:` is a deliberate blank |
| `curriculum/principles.md` | The principle pool. Add your own with the next free `P<NN>` id |

## Secrets

Set these in **Settings → Secrets and variables → Actions**. Nothing is ever
hardcoded, and the repo runs without any of them.

| Secret | Needed for |
|---|---|
| `ANTHROPIC_API_KEY` | Real scoring and summaries. Without it, briefs build offline |
| `SLACK_WEBHOOK_URL` | Only if `notify.channel: slack` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | Only if `notify.channel: email` |
| `PRODUCTHUNT_TOKEN`, `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Optional; upgrades those sources to their APIs |

`GITHUB_TOKEN` is supplied by Actions — the workflows only need `contents: write`.

## Cost

Scoring uses Claude Haiku 4.5 in batches of eight, behind a two-stage filter: a
local heuristic picks the plausible candidates, and only those reach the API. A
typical day is a handful of calls. `config/settings.yaml` sets hard ceilings on
input tokens, output tokens, and dollars per run; crossing one **stops scoring and
still writes the brief**, noting the stop. Spend is logged per run to
`data/usage.json`.

## Copyright

Only titles, links, short excerpts used transiently for scoring, and generated
summaries are stored. Full article text never is — `lumina/collect.py` caps every
excerpt at 60 words on the way in, and a test enforces it.

## Layout

```
config/       settings.yaml, sources.yaml, profile.yaml
curriculum/   principles.md, books.md
lumina/       the package — collect, classify, score, compose, streams, site
scripts/      thin CLI entry points, including stream.py
templates/    daily.md.j2, weekly.md.j2, site/index.html.j2
daily/        generated briefs
digests/      weekly digests
ideas/inbox/  scored opportunities, captured not activated
streams/      active.md · running/ (graduated) · archive/ (killed or pivoted)
data/         seen.json, usage.json, principles.json, runs.jsonl
tests/        44 tests, no network
```

Data flows one way: `collect → classify → prefilter → score → select → compose →
save → notify`. Each stage is a module you can run on its own.
