---
id: tim-20
title: Seasonality and calendar effects
track: time
track_name: Time & Patience
scope: Sell in May, the January effect. What survives out-of-sample testing, which
  is almost nothing.
key_idea: Calendar patterns exist in old data but vanish under forward testing; trading
  costs make them unprofitable even if they were real.
hard_truth: Effect magnitude is 1–2% in-sample, zero out-of-sample. Arbitrageurs and
  trading costs destroy any remaining edge. For someone without capital, this is irrelevant—you
  cannot trade to generate returns.
check: 'Compute S&P 500 average May return minus other-month average (2015–2025).
  Subtract: brokerage, spread, and 20.315% Japanese tax on listed gains (confirm current
  rate with NTA). Is edge positive?'
relevance: Calendar trading is noise. With no capital, studying seasonal patterns
  wastes time better spent understanding what actually builds wealth.
written_by: claude-code
---

# Seasonality and calendar effects

"Sell in May and go away" is the oldest calendar pattern in markets: historical data from UK and US markets show May–September typically underperforming other months. January is supposed to see abnormal returns. These patterns are real in historical datasets. They are almost entirely absent in new data.

How they worked: traders noticed May–September had lower average returns across 100+ years of data. Some posted the pattern, argued it had economic explanations (tax-loss harvesting, fund manager holidays). The pattern encouraged people to sell in May and buy back in October.

Why they vanished: once published, any exploitable pattern gets arbitraged away. If many traders buy in October and sell in May, those trades become crowded. October buying pressure drives prices up earlier. May selling comes sooner. The seasonal pattern erodes. Schwert (2003) documented this decay: publicized anomalies weaken or disappear within a year of publication.

The numbers: over the S&P 500 from 1990–2025, May does show slightly lower average returns than June–October, but the difference is roughly 1–2% annualized and sits entirely within noise. January averages 1.8% since 1950, but so do several other months. Out-of-sample, these effects do not reliably predict future returns.

Why they persist in conversation: data-mining bias is powerful. Given enough historical data and enough calendar combinations, you will find patterns by accident. Testing the same data that generated the hypothesis biases results upward. True out-of-sample tests—applying a rule discovered in 1950–2000 data to 2000–2025 data—show these effects collapse.

The cost: even if a 1% edge existed, transaction costs in Japan (20.315% tax on listed equity gains, plus brokerage fees and bid-ask spread) would erase it instantly. Your actual return from "sell in May" would be negative.

**Key idea.** Calendar patterns exist in old data but vanish under forward testing; trading costs make them unprofitable even if they were real.

**Hard truth.** Effect magnitude is 1–2% in-sample, zero out-of-sample. Arbitrageurs and trading costs destroy any remaining edge. For someone without capital, this is irrelevant—you cannot trade to generate returns.

**Check it yourself:** Compute S&P 500 average May return minus other-month average (2015–2025). Subtract: brokerage, spread, and 20.315% Japanese tax on listed gains (confirm current rate with NTA). Is edge positive?
