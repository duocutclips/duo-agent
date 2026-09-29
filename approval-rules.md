# Human approval gates (hard rules for the agent)

The agent drafts. A person approves. These actions ALWAYS stop and wait for a person to say yes in writing:

| Area | Agent may do alone | Needs a person's explicit OK |
|---|---|---|
| Posting | Cut clips, write captions, fill the approval queue, prepare a posting checklist | Uploading or publishing anything to TikTok, YouTube, Instagram, X, Roblox |
| Email and DMs | Draft into Gmail drafts, fill the CRM sheet | Sending any message to anyone outside the team |
| Money | Read exports, categorize, build reports, draft invoices | Sending invoices, paying, refunding, buying tools or ads, moving money, any trade |
| Accounts | Read settings and analytics through connectors | Creating accounts, changing passwords, adding payment methods, accepting terms |
| Clients | Draft proposals, scopes, handover docs | Sending quotes, signing, touching a client's production system |
| Code | Write code on `claude/` branches, open PRs | Merging to main, publishing a Roblox place update |

Why: platform rules. TikTok's Content Posting API keeps unaudited apps private-only and lists "a utility tool to help upload contents to the account(s) you or your team manages" as a use it will not approve. YouTube uploads from unverified API projects are forced private. Instagram publishing needs Meta app review and a Professional account. Content Rewards bans fake engagement and acts on all linked accounts at once. So posting stays manual (or goes through the platforms' own schedulers).

Secrets: API keys live in the cloud environment's credentials or a local `.env` that is git-ignored. Never in CLAUDE.md, skills, memory or chat.
