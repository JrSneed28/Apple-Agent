Status: needs-triage

## Parent

- PRD: `.scratch/apple-agent-v1/PRD.md`

## What to build

Write the README with installation instructions, usage examples, confidence-tier explanations, Windows/Mac limitation language, and the optional one-liner bootstrap. The installation path is: copy `SKILL.md` and `apple-agent.py` into `~/.claude/skills/apple/`. The README should also document the JSON schema so that CI integrators can use the CLI standalone without Claude Code.

## Acceptance criteria

- [ ] README explains the two-file manual installation.
- [ ] README includes a one-liner PowerShell/curl convenience option for downloading from a GitHub release.
- [ ] README documents all five `/apple` commands with examples.
- [ ] README explains confidence tiers (`verified`, `heuristic`, `requires_macos`) and why they matter.
- [ ] README documents the CLI JSON output schema for standalone/CI use.
- [ ] README clearly states that Xcode/Simulator/macOS validation is not performed on Windows.

## Blocked by

- `.scratch/apple-agent-v1/issues/05-skill-readonly-commands.md`
