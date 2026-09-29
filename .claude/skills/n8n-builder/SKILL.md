---
name: n8n-builder
description: Turn a client scope into an importable n8n workflow JSON plus a test plan and handover doc. Use when a scope in clients/<name>/scope.md is approved.
---

# n8n builder

1. Read `clients/<name>/scope.md`. Restate the trigger, each step, and the result in plain words; list any credential the client must create themselves.
2. Write `clients/<name>/workflow.json` in n8n's import format. Use built-in nodes where possible; use an HTTP Request node plus the Anthropic API only where language understanding is needed, with Haiku 4.5 or Sonnet 5.5 to keep cost low.
3. Put no secrets in the JSON. Reference n8n credentials by name only.
4. Write `clients/<name>/test-plan.md`: 5 test inputs including one bad input, and the expected result of each.
5. Write `clients/<name>/handover.md` for the business owner: what it does, how to pause it, who to call, monthly cost.

The client owns their n8n (or Make/Zapier) account and their credentials. We never hold their passwords.
