---
name: outreach-drafter
description: Research a local business and draft a short personalized outreach email or DM offering one specific automation. Use when a person asks for outreach drafts for rows in data/leads.csv.
---

# Outreach drafter

For each lead with status `new`:
1. Read their website and public reviews (web search or the browser). Note one concrete, visible pain: slow replies, no online booking, missed-call complaints, manual quote requests.
2. Pick ONE automation from our demo list that fixes it (lead capture to CRM, missed-call text-back, booking reminders, review requests, AI inbox triage).
3. Draft a message under 90 words: their name, the pain you noticed with evidence, the fix, a 2-minute demo video offer, one question. No hype, no fake familiarity.
4. Save the draft as a Gmail draft (Gmail connector) or into `queue/outreach/<business>.md`, and set status to `drafted` in `data/leads.csv`.

Never send. A person reads and sends each one.
