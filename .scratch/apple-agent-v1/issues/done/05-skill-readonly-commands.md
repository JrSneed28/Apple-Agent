Status: needs-triage

## Parent

- PRD: `.scratch/apple-agent-v1/PRD.md`

## What to build

Create `SKILL.md` for the Claude Code skill with read-only routing: `/apple scan`, `/apple audit`, and `/apple shipcheck`. The skill must detect the user's intent, map plain-English modifiers (e.g., `focus on privacy`, `quick pass`, `this folder only`) into structured scope/focus/risk parameters, call the CLI with the matching subcommand, parse the JSON report, and present findings to the user using the reporting contract. The skill must always state what was verified, what was inferred, and what requires macOS/Xcode.

## Acceptance criteria

- [ ] `/apple scan` detects the project type and prints a readable project map.
- [ ] `/apple audit` presents categorized findings (Critical/High/Medium/Low) with file paths.
- [ ] `/apple shipcheck` presents launch-readiness findings aligned with App Review, privacy, and StoreKit concerns.
- [ ] Plain-English modifiers are interpreted and passed to the CLI as flags or scope filters.
- [ ] Every response includes: verified checks, inferred checks, macOS-required checks, and recommended next steps.

## Blocked by

- `.scratch/apple-agent-v1/issues/04-audit-shipcheck-validate.md`
