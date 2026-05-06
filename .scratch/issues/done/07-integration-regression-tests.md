Status: needs-triage

## Parent

- PRD: `.scratch/apple-agent-v1/PRD.md`

## What to build

A cross-project integration and regression test suite using realistic Apple project skeletons (SPM package, Xcode project with `.pbxproj`, mixed UIKit/SwiftUI flat directory). Each skeleton exercises the full CLI pipeline: `scan` → `audit` → `shipcheck` → `validate`. Tests assert on report completeness, confidence labeling, and graceful fallback behavior. The suite also tests the skill-to-CLI JSON contract via subprocess invocations. Tests use Python `unittest` (standard library only).

## Acceptance criteria

- [ ] A representative SPM skeleton is scanned and the report contains expected targets and dependencies.
- [ ] A representative Xcode skeleton with a real `.pbxproj` is scanned and the report contains expected target names.
- [ ] A malformed `.pbxproj` skeleton triggers the lexer fallback without crashing the CLI.
- [ ] A mixed UIKit/SwiftUI flat-directory skeleton yields findings for both UI frameworks.
- [ ] The skill-to-CLI subprocess contract is verified: the skill can invoke the CLI and parse the resulting JSON.
- [ ] All tests pass with `python -m unittest` using only the standard library.

## Blocked by

- `.scratch/apple-agent-v1/issues/04-audit-shipcheck-validate.md`
