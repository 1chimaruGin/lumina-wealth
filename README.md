# Lumina Daily

**Dashboard: https://1chimarugin.github.io/lumina-wealth/**

A briefing system with two jobs: rewire how I think about money, and find one
income stream at a time worth actually building.

Every morning at **11:17 JST** a GitHub Action writes `daily/YYYY-MM-DD.md` and
commits it. On Sunday it writes a weekly digest. A dashboard renders all of it
at a glance.

> **On the schedule.** GitHub runs `schedule` events on a best-effort basis:
> they are delayed under load and sometimes dropped entirely. Observed here —
> 2026-09-24 fired 5h19m late and 2026-09-25 never fired. So the daily workflow
> avoids the top of the hour (the most contended slot) and books two retry
> slots later in the day. The job exits early if today's brief already exists,
> so the retries cost nothing on a normal day and rescue a missed one.
>
> If a day is still missed, `python scripts/backfill.py --days 2` fills it in,
> or trigger the workflow by hand from the Actions tab.

```
         ──── 11:17 JST ──────── Sunday 11:47 JST
               daily brief         weekly digest
               2 lessons + reading top 5 ideas for the next slot
```

## The brief

1. **Money school** — two lessons from the syllabus, written for me.
2. **Today's reading** — one piece summarised, plus a few links worth a few minutes.
3. **Opportunities** — a count, not a list. See below.
4. **Principle** — one idea resurfaced from `curriculum/principles.md`, spaced so
   nothing repeats inside three weeks.
5. **Today's action** — one 5–15 minute task for the active stream.
6. **Stream status** — day N of 90, revenue so far, this week's metric.

A section with nothing worth showing says so. Filler would cost the time the
brief exists to save.

### Why lessons and not just feeds

Feeds are recency-driven, and they run dry. Four of the five original Mind
sources published weekly or monthly; 2026-09-18 produced no Mind item at all.

So the spine is a **syllabus** — 152 topics across five tracks, starting in
3000 BC — and the feeds are the supplement. A syllabus teaches in sequence and
never runs out.

| Day | Track | The question |
|---|---|---|
| Mon | Psychology | How do I behave with money? |
| Tue | Intelligence | How does money actually work? |
| Wed | History & Stories | Who did this before, and what happened? |
| Thu | Financing | Where does capital come from, and what does it cost? |
| Fri | Management | How do I run what I have? |
| Sat | History & Stories | The long-read slot |
| Sun | — | Digest day |

One lesson comes from the weekday's track; the rest come from whichever track
is furthest behind, so coverage evens out without anyone managing it. Lessons
are written once, cached in `curriculum/lessons/`, and accumulate into a
personal textbook — which also makes rebuilding an old brief free and
deterministic.

Change the pace in `config/settings.yaml`:

```yaml
curriculum:
  lessons_per_day: 2
```

### Why opportunities are a count, not a list

Income-stream candidates are still collected, scored and filed to
`ideas/inbox/` every day — capture stays free. They are simply **not shown**
daily. Looking at candidates you are not allowed to start is the exact pressure
the one-stream rule exists to remove.

They surface in the **Sunday digest**, ranked. Set
`select.show_streams_in_daily: true` if you disagree.

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

# Scoring runs through the Claude Code CLI on your Claude subscription.
# No API key. If you can run `claude` you are already authenticated.
npm install -g @anthropic-ai/claude-code   # if you don't have it

python scripts/collect.py                # per-source report, writes nothing
python scripts/compose.py --dry-run      # build today's brief to stdout
python scripts/compose.py                # build and write it
python scripts/weekly.py                 # this week's digest
python scripts/backfill.py --days 7      # rebuild the last 7 days
python scripts/site.py --open            # build the dashboard, print a file:// URL
python -m pytest tests/ -q               # 73 tests, no network
```

## Scoring backends

There is no `ANTHROPIC_API_KEY` in this project. Scoring goes through the
**Claude Code CLI**, which authenticates against a Claude subscription.

Set `model.backend` in `config/settings.yaml`:

| Backend | What it needs | Billing |
|---|---|---|
| `claude-code` *(default)* | The `claude` CLI, signed in | Your Claude subscription — nothing per call |
| `api` | `ANTHROPIC_API_KEY` | Per token |
| `offline` | Nothing at all | Free, and much blunter |
| `auto` | — | CLI if present, else a key if present, else offline |

Override for one run with `LUMINA_BACKEND=offline python scripts/compose.py`.

An unavailable backend **degrades to the next one instead of failing the run**,
and every brief names the scorer that actually produced it in its Run notes.
The offline scorer never fakes a summary: it shows the feed's own excerpt,
labelled as an excerpt.

### In GitHub Actions

The workflows install the CLI and authenticate with a long-lived token. Making
that token is a **local** step — GitHub has no way to log into your Claude
account, so it cannot be done from the repo.

**1. On your own machine,** in any normal terminal:

```bash
claude setup-token
```

It opens a browser, you approve with your Claude account, and it prints a
long-lived token.

**2. Give that token to GitHub** as the repo secret
**`CLAUDE_CODE_OAUTH_TOKEN`** — either through the web UI
(Settings → Secrets and variables → Actions → New repository secret) or from
the same terminal:

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo 1chimaruGin/lumina-wealth
```

`gh` prompts for the value so the token never lands in your shell history.

That is the only secret the system needs. It is a credential to your Claude
account: treat it like a password, and if it leaks, run `claude setup-token`
again to issue a new one and overwrite the secret.

The workflows check for it before doing anything and fail with a clear error if
it is missing, rather than quietly falling back to the offline scorer.

### Cost control on a subscription

A subscription is not billed per call, so the dollar ceilings in
`config/settings.yaml` are ignored on this backend and **`max_calls_per_run`**
is the ceiling that matters — calls are what a rate limit actually counts. A
day costs 2 calls (one Mind summary, one batch of stream scores); the default
allows 12. Crossing it stops scoring and still writes the brief, saying so.

`data/usage.json` records tokens per run and reports the CLI's equivalent API
price as `equivalent_usd_not_charged`, named so a subscription run is never
misread as a bill.

### Rebuilding

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

Four views:

| Tab | What it is |
|---|---|
| **Daily** | One brief at a time, with a date picker and arrow-key navigation |
| **Weekly** | The Sunday digest, where opportunities are ranked |
| **River** | One continuous reverse-chronological scroll of every lesson and reading, filterable by track or kind and searchable |
| **Library** | Every lesson written so far, grouped by track — the textbook as it accumulates |

The rail carries the gate's checklist, the ranked inbox, a 21-day activity
strip, syllabus progress per track, and source health.

`python scripts/site.py` builds `site/index.html` — one self-contained file with
the data inlined, so it works from GitHub Pages, from `file://`, or anywhere else
you drop it. It shows the active stream as a 90-tick cycle rail, the gate's
checklist, the ranked inbox, a 21-day activity strip, which principles have been
resurfaced, and source health. The `Dashboard` workflow deploys it to Pages on
every push that changes content.

`site/` is not committed — it is a build artifact, rebuilt from the repo.

### Three ways to read it

| | How | Good for |
|---|---|---|
| **Local** | `python scripts/site.py --open` | Day to day. Builds from the repo you already have and opens it. |
| **CI artifact** | Download `dashboard` from any Daily run summary | Reading it from a machine without the repo checked out. |
| **GitHub Pages** | Off by default — see below | A real URL, if you ever want one. |

### About Pages

The dashboard rebuilds **after** the Daily brief, Weekly digest and Backfill
workflows, not from their pushes. That is not a stylistic choice: a push made
with `GITHUB_TOKEN` does not trigger other workflows — GitHub blocks it to
prevent recursion — so the bot's daily commit never fired a `push` trigger, and
the dashboard sat frozen on the date of the last *human* push while the repo
moved on. `workflow_run` is the documented way around it.

Pages is live at **https://1chimarugin.github.io/lumina-wealth/**, rebuilt by
the `Dashboard` workflow whenever content changes.

The workflow is gated on the repository variable `PAGES_ENABLED`. That exists
because Pages does not work on a private repo on the free plan, and a deploy
that cannot succeed should be **skipped, not failed** — otherwise every push
shows a red build for a reason no code change can fix. If you ever take this
repo private again, unset the variable:

```bash
gh variable unset PAGES_ENABLED
```

## What is public

This repo is public, so everything in it is world-readable — including things
that accumulate rather than things you wrote once:

| Path | What ends up there |
|---|---|
| `daily/`, `digests/` | Every brief, with the opportunities you were shown |
| `ideas/inbox/` | Every scored idea, including ones you have not acted on |
| `streams/active.md` | The active stream's name, goal, **revenue figures** and daily log |
| `streams/running/`, `streams/archive/` | What worked, what you killed, and why |
| `config/profile.yaml` | Your role, city, skills, weekly hours and capital |
| `data/usage.json` | Token counts per run |

Nothing here is a credential — `CLAUDE_CODE_OAUTH_TOKEN` is a GitHub secret and
never touches the repo. But revenue numbers and unacted-on ideas are genuinely
yours, and they become visible the moment you log them. If you would rather
keep the money private while keeping the system public, the smallest change is
to log revenue as a relative metric instead of an absolute one, or to move
`streams/` into a private sibling repo and read it in via a submodule.

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
| `CLAUDE_CODE_OAUTH_TOKEN` | Scoring. Make it with `claude setup-token`. **The only one you need** |
| `ANTHROPIC_API_KEY` | Only if you switch `model.backend` to `api` |
| `SLACK_WEBHOOK_URL` | Only if `notify.channel: slack` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | Only if `notify.channel: email` |
| `PRODUCTHUNT_TOKEN`, `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Optional; upgrades those sources to their APIs |

`GITHUB_TOKEN` is supplied by Actions — the workflows only need `contents: write`.

## Cost

Scoring uses Haiku in batches of eight, behind a two-stage filter: a local
heuristic picks the plausible candidates, and only those reach the model. A
typical day is two calls. On the default `claude-code` backend that is
subscription usage, not a bill — see **Scoring backends** above for the
ceilings that apply.

## Copyright

Only titles, links, short excerpts used transiently for scoring, and generated
summaries are stored. Full article text never is — `lumina/collect.py` caps every
excerpt at 60 words on the way in, and a test enforces it.

## Layout

```
config/       settings.yaml, sources.yaml, profile.yaml
curriculum/   syllabus.yaml (152 topics), principles.md, books.md, lessons/ (generated)
lumina/       the package — collect, classify, score, compose, streams, site
              (claude_cli.py is the subscription-backed scoring backend)
scripts/      thin CLI entry points, including stream.py
templates/    daily.md.j2, weekly.md.j2, site/index.html.j2
daily/        generated briefs
digests/      weekly digests
ideas/inbox/  scored opportunities, captured not activated
streams/      active.md · running/ (graduated) · archive/ (killed or pivoted)
data/         seen.json, usage.json, principles.json, curriculum.json, river.jsonl, runs.jsonl
tests/        73 tests, no network
```

Data flows one way: `collect → classify → prefilter → score → select → compose →
save → notify`. Each stage is a module you can run on its own.
