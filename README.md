# duo-agent

The DuoCut team's AI agent: Claude Code plus the skills in `.claude/skills/`, with `CLAUDE.md` as its memory and `approval-rules.md` as its hard limits.

- **DuoCut Studio** (`app.py`): local web app for the clip pipeline. Campaign page → transcript → Claude picks moments → you approve → captioned 9:16 clips → you post → views tracked.
- **Setup:** see [SETUP.md](SETUP.md).
- **Command line:** `python scripts/duocut.py --help`.

Nothing in this repo posts, sends, pays or logs in anywhere. A person does that.
