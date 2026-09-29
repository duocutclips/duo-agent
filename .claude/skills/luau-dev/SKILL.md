---
name: luau-dev
description: Write and test Roblox Luau code through the Roblox Studio MCP server, following our game design doc. Use for any Roblox scripting, bug fix or playtest task.
---

# Luau dev

Setup: in Roblox Studio, enable the MCP server in Assistant settings, then connect Claude Code (Studio lists it under quick-connect clients).

1. Read `game/design.md` first. The core loop and the scope list there win over new ideas.
2. Explore the data model before editing. Keep server logic in ServerScriptService, shared modules in ReplicatedStorage, and never trust the client for currency, damage or purchases.
3. After each change, start play mode through MCP, run the check the task needs, and report what you saw.
4. For monetization (game passes, developer products), write the code but leave prices and publishing to a person.
5. Log every change in `game/changelog.md` in player-facing words, so the clip lane can turn it into devlog content.

Never publish the place. A person publishes from Studio.
