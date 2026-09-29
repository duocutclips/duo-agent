---
name: finance-ledger
description: Import payout and expense exports into data/ledger.csv, categorize them by lane, and produce the monthly profit and partner-split report. Use at month end or when a person drops a CSV export in inbox/.
---

# Finance ledger (read-only)

1. Read exports a person placed in `inbox/` (Whop payouts CSV, Stripe export, bank CSV). Also read Stripe through its connector if connected, read-only.
2. Append each transaction to `data/ledger.csv` once (match on date + amount + description to avoid duplicates). Lane is one of: clips, automation, roblox, shared.
3. Monthly report in `reports/<yyyy-mm>.md`: income and costs per lane, profit, profit per human hour (hours from `data/hours.csv` if present), each partner's share per the agreed split, and the tax set-aside at the rate in CLAUDE.md (a person sets it with their accountant).
4. List anything unusual: a missing payout, a charge nobody recognizes, a subscription nobody uses.
5. Draft invoices only as drafts.

Never pay, refund, transfer, trade, buy, or send an invoice. Never ask for or store bank logins.
