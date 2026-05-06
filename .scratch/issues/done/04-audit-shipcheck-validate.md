Status: needs-triage

## Parent

- PRD: `.scratch/apple-agent-v1/PRD.md`

## What to build

Add the remaining CLI subcommands: `audit --target <path>` (scoped re-run of all analyzers), `shipcheck` (launch-readiness report combining all analyzers with App Review risk weighting), and `validate` (identical analysis but semantically labeled for post-edit use). Finalize the JSON contract so the schema is stable: `findings`, `suggested_actions`, `validation.performed`, `validation.skipped`, `validation.requires_macos`, and `summary` severity counts. Include schema/contract tests that assert every subcommand produces the expected top-level keys.

## Acceptance criteria

- [ ] `audit --target Sources/App/Profile` returns findings scoped to the target directory.
- [ ] `shipcheck` returns a report with launch-blocker, App Review risk, privacy risk, and StoreKit risk sections.
- [ ] `validate` produces the same JSON shape as `scan` but is distinguishable by context for post-edit reporting.
- [ ] The JSON contract is versioned and consistent across all four subcommands.
- [ ] Schema tests verify all required top-level keys exist and have the correct types.

## Blocked by

- `.scratch/apple-agent-v1/issues/02-deterministic-platform-analyzers.md`
- `.scratch/apple-agent-v1/issues/03-swift-heuristic-scanner.md`
