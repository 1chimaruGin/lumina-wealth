---
id: tim-08
title: Hyperbolic discounting, with the arithmetic
track: time
track_name: Time & Patience
scope: How steeply people discount the future, measured — and why the curve is worse
  at short horizons.
key_idea: You discount near-term future rewards 10–20× steeper than exponential decay
  predicts, making compound growth mathematically invisible.
hard_truth: 'This is neurological, not a choice flaw. The curve bends at present,
  not future. For the capital-poor, it is devastating: you''re forced to grab immediate
  small earnings exactly when your bias is strongest, ensuring you stay poor.'
check: 'Find your bank''s current savings interest rate on your statement (typical
  major Japanese bank: 0.05% annually). Calculate: How many years until ¥100,000 becomes
  ¥200,000? Use n = log(2) / log(1.0005). At 0.05%, this is approximately 1,386 years.
  Now calculate the same for 7% annual return (typical…'
relevance: Your discount curve makes you hunger for the small immediate win and devalue
  the compound return — exactly backward when capital is scarce.
written_by: claude-code
---

# Hyperbolic discounting, with the arithmetic

Hyperbolic discounting is how humans discount future value — and it bends sharply near the present, not smoothly throughout time.

Standard economic models assume exponential discounting: a constant-rate decay. The value of ¥100 in one year decays at the same proportional rate as ¥100 in two years. Reality is different. The curve bends sharply near now. Offered ¥100,000 today versus ¥110,000 in one week, most people take ¥100,000. Offered ¥100,000 in 52 weeks versus ¥110,000 in 53 weeks, most choose ¥110,000. Same one-week delay; different choices. That inconsistency is hyperbolic discounting.

The arithmetic is straightforward. Perceived value = A / (1 + k·D), where A is amount, D is delay in days, k is discount factor. Studies consistently find k ≈ 0.01–0.05 for money over days and weeks. Using k = 0.02: ¥100,000 in 1 day is worth ~¥98,000 today; in 7 days, ~¥87,000; in 365 days, ~¥21,000. Reverse the timeline: ¥100,000 in 365 days is ~¥21,000; in 372 days, ~¥20,000. Under exponential discounting, your preference should be identical in both cases. It won't be. The curve bends at the origin.

The operational cost is compounding death. A ¥100,000 investment at 7% annual return becomes ¥196,700 in 10 years. But hyperbolic discounting makes that future ¥196,700 feel far less valuable than ¥100,000 now. You're neurologically tuned to reject the trade — not because you are weak, but because the discount curve is sharpest at the start, exactly when investing matters most.

The curve is steeper for smaller amounts. Someone choosing between ¥5,000 now and ¥6,000 in one week discounts more steeply than someone with ¥500,000 choosing the same ratio. Time perception scales with reward size relative to existing wealth. This is why the poor discount most steeply and stay poor.

**Key idea.** You discount near-term future rewards 10–20× steeper than exponential decay predicts, making compound growth mathematically invisible.

**Hard truth.** This is neurological, not a choice flaw. The curve bends at present, not future. For the capital-poor, it is devastating: you're forced to grab immediate small earnings exactly when your bias is strongest, ensuring you stay poor.

**Check it yourself:** Find your bank's current savings interest rate on your statement (typical major Japanese bank: 0.05% annually). Calculate: How many years until ¥100,000 becomes ¥200,000? Use n = log(2) / log(1.0005). At 0.05%, this is approximately 1,386 years. Now calculate the same for 7% annual return (typical…
