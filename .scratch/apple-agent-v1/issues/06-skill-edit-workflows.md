Status: needs-triage

## Parent

- PRD: `.scratch/apple-agent-v1/PRD.md`

## What to build

Extend `SKILL.md` with the edit workflow for `/apple fix` and `/apple polish`. Orchestration: run CLI `audit` to get `suggested_actions`, present an edit plan with exact files, finding IDs, risk levels, and behavior-preservation summaries, ask for explicit user approval, edit only approved files via Claude Code's native `Edit` tool, run CLI `validate`, and present a final report with diff summary and remaining risks. Enforce the protected-file policy: `Info.plist`, `*.entitlements`, `project.pbxproj`, `Package.swift`, `*.xcconfig`, signing configs, StoreKit configs, auth/payment/security files, and generated files are report-only unless the user initiates a separate explicit approval round. The skill must reject scope creep: if the user approved `ProfileView.swift`, the agent must not also touch navigation or plist files.

## Acceptance criteria

- [ ] `/apple fix <target>` produces an edit plan before any edits occur.
- [ ] User approval is required; the agent does not auto-edit even when `safe_to_autofix` is true.
- [ ] Only files returned by the CLI in the resolved scope are edited.
- [ ] Protected files are never edited without a separate explicit approval round.
- [ ] Post-edit, the CLI `validate` command runs and a diff summary is presented.
- [ ] The final report always includes: what changed, what was validated, what was inferred, what requires macOS/Xcode, what risky areas were avoided, and what remains to do.

## Blocked by

- `.scratch/apple-agent-v1/issues/05-skill-readonly-commands.md`

## Type

HITL — the approval interaction design, wording, and protected-file behavior should be reviewed before implementation.
