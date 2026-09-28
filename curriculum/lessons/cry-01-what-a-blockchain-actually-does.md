---
id: cry-01
title: What a blockchain actually does
track: crypto
track_name: Crypto
scope: An append-only ledger with no admin. What that buys you and what it costs.
key_idea: Immutability comes from distributing control via cryptographic hashing and
  consensus; the costs are privacy loss, slow settlement, no recourse, and significant
  energy.
hard_truth: 'A blockchain only solves the problem you face if you distrust all intermediaries
  more than math. In Japan, crypto taxation is worse than equities: progressive 雑所得
  rates (up to ~45%) versus flat 20.315% on listed stocks. No refunds for mistakes.'
check: On mempool.space (Bitcoin) or etherscan.io (Ethereum), find the current median
  transaction fee. Look up the current JPY/BTC or JPY/ETH rate. Calculate the fee
  in JPY and compare to your bank's wire fee.
relevance: Shows whether blockchain's immutability and transparency solve actual problems
  you face, or whether they're just adding cost and tax disadvantage versus existing
  alternatives.
written_by: claude-code
---

# What a blockchain actually does

A blockchain is an append-only ledger protected by cryptographic hashing. Each block contains transactions and a hash of the previous block. Changing any transaction retroactively would change that block's hash, which invalidates every block after it. On systems like Bitcoin (proof-of-work), an attacker would need to rebuild the entire chain faster than the network extends it—meaning controlling >50% of the hashing power. This is computationally expensive: Bitcoin's annual electricity use is approximately 130–150 TWh (check Cambridge Bitcoin Electricity Consumption Index for current figures).

What you actually get: immutability (reversing a confirmed transaction requires outcomputing the entire network), transparency (anyone can audit the full transaction history), and independence from a single trusted operator. These are real properties with real costs.

What you do not get: privacy (all transactions and amounts are visible by default), speed (Bitcoin takes ~10 minutes per block; practical irreversibility takes hours of subsequent blocks), or freedom from intermediaries (you still need an exchange to enter the system, a wallet provider to custody funds, and taxation applies—in Japan, 仮想通貨 gains are 雑所得 taxed progressively at approximately 15-45% depending on income level, versus 上場株式 gains at flat 20.315%; confirm current rules with NTA). No one will reverse a mistake. No one will recover lost private keys.

The mechanical benefit—append-only with distributed consensus—is real but narrow: it prevents any single party from secretly rewriting history. That benefit is useful only if you distrust all intermediaries more than you trust mathematics and distributed systems. For most people and most transactions, a regulated bank with legal liability is faster and cheaper.

**Key idea.** Immutability comes from distributing control via cryptographic hashing and consensus; the costs are privacy loss, slow settlement, no recourse, and significant energy.

**Hard truth.** A blockchain only solves the problem you face if you distrust all intermediaries more than math. In Japan, crypto taxation is worse than equities: progressive 雑所得 rates (up to ~45%) versus flat 20.315% on listed stocks. No refunds for mistakes.

**Check it yourself:** On mempool.space (Bitcoin) or etherscan.io (Ethereum), find the current median transaction fee. Look up the current JPY/BTC or JPY/ETH rate. Calculate the fee in JPY and compare to your bank's wire fee.
